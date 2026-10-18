"""Narrow native HA executor; transport is separate and cannot dispatch services.

All methods run on HA's event loop. Every request rechecks current options,
entity state and native capabilities; only individual light/switch targets can
be addressed. No raw attributes, service names, areas or network URLs escape.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

_LOGGER = logging.getLogger(__name__)
ENTITY = re.compile(r"^(light|switch)\.[a-z0-9_]+$")
MAX_REQUEST_MS = 15_000
# A slow HA clock must not reject an otherwise fresh gateway request. Allow
# at most five seconds of lag at admission; never extend a locally expired
# deadline or the relative execution budget supplied by the gateway.
CLOCK_LAG_MS = 5_000


class Denied(Exception):
    def __init__(self, code):
        self.code = code


def validate_exposure(options):
    reads = options.get("read_entities", [])
    if len(reads) > 1000 or any(
        not isinstance(e, str) or not ENTITY.fullmatch(e) for e in reads
    ):
        raise Denied("INVALID_ARGUMENT")
    for key in ("turn_on_entities", "turn_off_entities", "brightness_entities"):
        if not set(options.get(key, [])).issubset(reads):
            raise Denied("INVALID_ARGUMENT")
    if any(not e.startswith("light.") for e in options.get("brightness_entities", [])):
        raise Denied("INVALID_ARGUMENT")


class Executor:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.active = True
        # Correlation ids remain recorded across reconnects for their whole
        # validity window. When full, reject new requests instead of evicting a
        # potentially replayable write. Process restart drops the old WSS.
        self.seen = {}

    def _state(self, entity_id):
        if not self.active:
            raise Denied("DISCONNECTED")
        if not isinstance(entity_id, str) or not ENTITY.fullmatch(entity_id):
            raise Denied("INVALID_ARGUMENT")
        if entity_id not in self.entry.options.get("read_entities", []):
            raise Denied("NOT_EXPOSED")
        state = self.hass.states.get(entity_id)
        if state is None:
            raise Denied("ENTITY_UNAVAILABLE")
        return state

    def _actions(self, state):
        if state.state in ("unavailable", "unknown"):
            return []
        domain = state.entity_id.split(".", 1)[0]
        return [
            a
            for a in ("turn_on", "turn_off")
            if state.entity_id in self.entry.options.get(f"{a}_entities", [])
            and self.hass.services.has_service(domain, a)
        ]

    def _brightness(self, state):
        modes = state.attributes.get("supported_color_modes", [])
        return bool(
            state.entity_id.startswith("light.")
            and any(mode not in ("onoff", "unknown") for mode in modes)
        )

    def _describe(self, state):
        result = {
            "entity_id": state.entity_id,
            "state": state.state,
            "actions": self._actions(state),
            "brightness_allowed": bool(
                self._brightness(state)
                and "turn_on" in self._actions(state)
                and state.entity_id in self.entry.options.get("brightness_entities", [])
            ),
        }
        if state.entity_id.startswith("light."):
            value = state.attributes.get("brightness")
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= 255
            ):
                result["brightness"] = value
        return result

    async def execute(self, message):
        try:
            if (
                not isinstance(message, dict)
                or message.get("v") != 1
                or message.get("type") != "request"
            ):
                raise Denied("INVALID_ARGUMENT")
            correlation = message.get("correlation_id")
            expiry = message.get("expires_at_ms")
            timeout = message.get("timeout_ms")
            now = time.time() * 1000
            if (
                not isinstance(correlation, str)
                or not 1 <= len(correlation) <= 128
                or type(expiry) is not int
                or type(timeout) is not int
                or not 0 < timeout <= MAX_REQUEST_MS
            ):
                raise Denied("INVALID_ARGUMENT")
            if not now < expiry <= now + MAX_REQUEST_MS + CLOCK_LAG_MS:
                raise Denied("DEADLINE_EXCEEDED")
            monotonic_now = time.monotonic()
            self.seen = {k: v for k, v in self.seen.items() if v > monotonic_now}
            if correlation in self.seen:
                raise Denied("DUPLICATE_REQUEST")
            if len(self.seen) >= 1000:
                raise Denied("BUSY")
            # Retain the ID for the maximum accepted envelope lifetime, even
            # after its shorter execution timeout or a wall-clock correction.
            self.seen[correlation] = (
                monotonic_now + (MAX_REQUEST_MS + CLOCK_LAG_MS) / 1000
            )
            body = message.get("body")
            if (
                not isinstance(body, dict)
                or body.get("instance_id") != self.entry.data["device_id"]
            ):
                raise Denied("INSTANCE_MISMATCH")
            if set(body) != {"instance_id", "action", "params"}:
                raise Denied("INVALID_ARGUMENT")
            params = body.get("params")
            if not isinstance(params, dict) or not self.active:
                raise Denied("DISCONNECTED")
            validate_exposure(self.entry.options)
            async with asyncio.timeout(min(timeout, expiry - now) / 1000):
                return await self._execute(body["action"], params)
        except Denied as exc:
            return {"error": {"code": exc.code}}
        except TimeoutError:
            return {"error": {"code": "DEADLINE_EXCEEDED", "outcome": "uncertain"}}
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — contain native integration failures without leaking data
            # Never put raw entity attributes, exceptions or user payloads in logs.
            _LOGGER.warning("Home Assistant toolkit native action failed")
            return {"error": {"code": "EXECUTION_ERROR", "outcome": "uncertain"}}

    async def _execute(self, action, params):
        if action == "list_entities":
            if set(params) - {"offset", "limit"}:
                raise Denied("INVALID_ARGUMENT")
            offset, limit = params.get("offset", 0), params.get("limit", 50)
            if (
                type(offset) is not int
                or offset < 0
                or type(limit) is not int
                or not 1 <= limit <= 100
            ):
                raise Denied("INVALID_ARGUMENT")
            exposed = sorted(
                e
                for e in set(self.entry.options.get("read_entities", []))
                if self.hass.states.get(e) is not None
            )
            entities = [
                self._describe(self._state(e)) for e in exposed[offset : offset + limit]
            ]
            return {
                "entities": entities,
                "total": len(exposed),
                "next_offset": offset + limit
                if offset + limit < len(exposed)
                else None,
            }
        entity_id = params.get("entity_id")
        state = self._state(entity_id)
        if action == "get_entity_state" and set(params) == {"entity_id"}:
            return self._describe(state)
        if action != "control_entity" or set(params) - {
            "entity_id",
            "action",
            "brightness",
        }:
            raise Denied("INVALID_ARGUMENT")
        service = params.get("action")
        if service not in self._actions(state):
            raise Denied("ACTION_NOT_ALLOWED")
        data = {"entity_id": entity_id}
        if "brightness" in params:
            brightness = params["brightness"]
            if (
                type(brightness) is not int
                or not 1 <= brightness <= 255
                or service != "turn_on"
                or not self._describe(state)["brightness_allowed"]
            ):
                raise Denied("ACTION_NOT_ALLOWED")
            data["brightness"] = brightness
        # Native call targets exactly one entity. No area/device/group expansion
        # beyond whatever behaviour the user's explicitly selected HA entity has.
        _LOGGER.info("Home Assistant toolkit authorized %s for %s", service, entity_id)
        await self.hass.services.async_call(
            entity_id.split(".")[0], service, data, blocking=True
        )
        return self._describe(self._state(entity_id))
