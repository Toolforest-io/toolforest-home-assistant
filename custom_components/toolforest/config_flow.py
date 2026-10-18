"""UI pairing and per-entity/action exposure; no separate local daemon."""

from __future__ import annotations

import time

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, ENVIRONMENTS, EXPOSURE_KEYS
from .device_auth import async_revoke_device
from .executor import Denied, validate_exposure


def exposure_schema(defaults=None):
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(key, default=defaults.get(key, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["light"]
                    if key == "brightness_entities"
                    else ["light", "switch"],
                    multiple=True,
                )
            )
            for key in EXPOSURE_KEYS
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.pairing = None
        self.settings = {}
        self.credentials = None
        self.next_poll = 0
        self.expires = 0
        self.reauth_entry = None
        self._removed = False

    async def _post(self, path, data):
        async with async_get_clientsession(self.hass).post(
            f"{ENVIRONMENTS[self.settings['environment']][0]}{path}",
            json=data,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            return await response.json()

    async def _start_pairing(self):
        self.pairing = await self._post(
            "/device/code",
            {"device_name": self.settings["name"], "capability": "home_assistant"},
        )
        if not self.pairing.get("device_code"):
            raise ValueError("invalid device code response")
        self.expires = time.monotonic() + self.pairing["expires_in"]
        self.next_poll = 0

    @callback
    def async_remove(self):
        """HA calls this on success as well as cancellation/abort."""
        self._removed = True
        if not self.credentials:
            return
        token = self.credentials["access_token"]
        self.credentials = None
        # Only a committed entry may take ownership of the minted credential.
        # Checking here also covers an abort while HA finishes entry creation.
        if any(
            entry.data.get("environment") == self.settings["environment"]
            and entry.data.get("access_token") == token
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        ):
            return
        self.hass.async_create_task(
            async_revoke_device(self.hass, self.settings["environment"], token),
            "toolforest-abandoned-pairing-revoke",
        )

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self.settings = user_input
            try:
                await self._start_pairing()
                return await self.async_step_pairing()
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "name", default=self.settings.get("name", "Home Assistant")
                    ): vol.All(str, vol.Length(min=1, max=64)),
                    vol.Required(
                        "environment", default=self.settings.get("environment", "prod")
                    ): vol.In(
                        {"dev": "Development", "test": "Test", "prod": "Production"}
                    ),
                }
            ),
        )

    async def async_step_pairing(self, user_input=None):
        errors = {}
        if time.monotonic() >= self.expires:
            return self.async_abort(reason="pairing_expired")
        if user_input is not None:
            if time.monotonic() < self.next_poll:
                errors["base"] = "authorization_pending"
            else:
                self.next_poll = time.monotonic() + self.pairing["interval"]
                try:
                    result = await self._post(
                        "/device/token", {"device_code": self.pairing["device_code"]}
                    )
                    if result.get("access_token") and result.get("device_id"):
                        # A user can close the flow while the token HTTP request
                        # is in flight, before async_remove has a token to clean.
                        if self._removed:
                            await async_revoke_device(
                                self.hass,
                                self.settings["environment"],
                                result["access_token"],
                            )
                            return self.async_abort(reason="pairing_expired")
                        self.credentials = result
                        if self.reauth_entry:
                            # Loaded entries already reload through their update
                            # listener. Scheduling another reload races setup
                            # against unload and can strand the new connection.
                            finish = (
                                self.async_update_and_abort
                                if self.reauth_entry.update_listeners
                                else self.async_update_reload_and_abort
                            )
                            return finish(
                                self.reauth_entry,
                                unique_id=f"{self.settings['environment']}:{result['device_id']}",
                                data_updates={
                                    **self.settings,
                                    "access_token": result["access_token"],
                                    "device_id": result["device_id"],
                                },
                            )
                        return await self.async_step_exposure()
                    if result.get("error") != "authorization_pending":
                        return self.async_abort(reason="pairing_expired")
                    errors["base"] = "authorization_pending"
                except (aiohttp.ClientError, TimeoutError, ValueError):
                    errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="pairing",
            errors=errors,
            data_schema=vol.Schema({}),
            description_placeholders={
                "url": self.pairing["verification_uri"],
                "code": self.pairing["user_code"],
            },
        )

    async def async_step_exposure(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                validate_exposure(user_input)
                await self.async_set_unique_id(
                    f"{self.settings['environment']}:{self.credentials['device_id']}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self.settings["name"],
                    data={
                        **self.settings,
                        "access_token": self.credentials["access_token"],
                        "device_id": self.credentials["device_id"],
                    },
                    options=user_input,
                )
            except Denied:
                errors["base"] = "invalid_exposure"
        return self.async_show_form(
            step_id="exposure", errors=errors, data_schema=exposure_schema()
        )

    async def async_step_reauth(self, entry_data):
        self.reauth_entry = self._get_reauth_entry()
        self.settings = {k: entry_data[k] for k in ("environment", "name")}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._start_pairing()
                return await self.async_step_pairing()
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                validate_exposure(user_input)
                return self.async_create_entry(title="", data=user_input)
            except Denied:
                errors["base"] = "invalid_exposure"
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=exposure_schema(self.config_entry.options),
        )
