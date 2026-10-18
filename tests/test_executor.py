import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.toolforest.executor import Denied, Executor, validate_exposure


@pytest.fixture
def executor():
    states = {
        name: SimpleNamespace(
            entity_id=name,
            state="off",
            attributes={
                "supported_color_modes": ["brightness"],
                "brightness": 0,
                "access_token": "MUST-NOT-LEAK",
                "friendly_name": "private name",
            },
        )
        for name in (
            "light.allowed",
            "switch.allowed",
            "light.hidden",
            "lock.front_door",
        )
    }
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get),
        services=SimpleNamespace(
            has_service=lambda domain, action: domain in ("light", "switch"),
            async_call=AsyncMock(),
        ),
    )
    entry = SimpleNamespace(
        data={"device_id": "instance-1"},
        options={
            "read_entities": ["light.allowed", "switch.allowed"],
            "turn_on_entities": ["light.allowed", "switch.allowed"],
            "turn_off_entities": ["light.allowed"],
            "brightness_entities": ["light.allowed"],
        },
    )
    return Executor(hass, entry)


def request(action="get_entity_state", params=None, **updates):
    body = {
        "instance_id": "instance-1",
        "action": action,
        "params": params if params is not None else {"entity_id": "light.allowed"},
    }
    return {
        "v": 1,
        "type": "request",
        "correlation_id": str(time.monotonic_ns()),
        "timeout_ms": 1000,
        "expires_at_ms": int(time.time() * 1000) + 1000,
        "body": body,
        **updates,
    }


@pytest.mark.asyncio
async def test_inventory_only_exposed_paginated_no_raw_attributes(executor):
    page = await executor.execute(request("list_entities", {"offset": 0, "limit": 1}))
    assert [e["entity_id"] for e in page["entities"]] == ["light.allowed"]
    assert page["next_offset"] == 1 and page["total"] == 2
    assert "MUST-NOT-LEAK" not in str(page) and "private name" not in str(page)
    page2 = await executor.execute(request("list_entities", {"offset": 1, "limit": 1}))
    assert page2["entities"][0]["entity_id"] == "switch.allowed"
    assert page2["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity,code",
    [
        ("light.hidden", "NOT_EXPOSED"),
        ("lock.front_door", "INVALID_ARGUMENT"),
        ("camera.front", "INVALID_ARGUMENT"),
        ("alarm_control_panel.home", "INVALID_ARGUMENT"),
        ("cover.garage", "INVALID_ARGUMENT"),
        ("light.allowed,light.hidden", "INVALID_ARGUMENT"),
    ],
)
async def test_denied_targets(executor, entity, code):
    result = await executor.execute(request(params={"entity_id": entity}))
    assert result["error"]["code"] == code
    executor.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_exposes_nothing(executor):
    executor.entry.options = {}
    assert (await executor.execute(request("list_entities", {})))["entities"] == []
    assert (await executor.execute(request()))["error"]["code"] == "NOT_EXPOSED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity,action,brightness",
    [
        ("light.allowed", "turn_on", 100),
        ("light.allowed", "turn_off", None),
        ("switch.allowed", "turn_on", None),
    ],
)
async def test_narrow_native_call(executor, entity, action, brightness):
    params = {"entity_id": entity, "action": action}
    if brightness is not None:
        params["brightness"] = brightness
    result = await executor.execute(request("control_entity", params))
    assert "error" not in result
    args = {"entity_id": entity}
    if brightness is not None:
        args["brightness"] = brightness
    executor.hass.services.async_call.assert_awaited_once_with(
        entity.split(".")[0], action, args, blocking=True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"entity_id": "switch.allowed", "action": "turn_off"},
        {"entity_id": "light.allowed", "action": "toggle"},
        {"entity_id": "light.allowed", "action": "turn_on", "brightness": True},
        {"entity_id": "light.allowed", "action": "turn_on", "brightness": 256},
        {"entity_id": "light.allowed", "action": "turn_on", "service": "unlock"},
        {"entity_id": "switch.allowed", "action": "turn_on", "brightness": 10},
    ],
)
async def test_denied_actions_and_injection(executor, params):
    assert "error" in await executor.execute(request("control_entity", params))
    executor.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_capabilities_and_options_rechecked_at_execution(executor):
    executor.entry.options["turn_on_entities"] = []
    assert (
        await executor.execute(
            request(
                "control_entity", {"entity_id": "light.allowed", "action": "turn_on"}
            )
        )
    )["error"]["code"] == "ACTION_NOT_ALLOWED"
    executor.entry.options["turn_on_entities"] = ["light.allowed"]
    executor.hass.states.get("light.allowed").attributes["supported_color_modes"] = [
        "onoff"
    ]
    assert "error" in await executor.execute(
        request(
            "control_entity",
            {"entity_id": "light.allowed", "action": "turn_on", "brightness": 10},
        )
    )
    executor.hass.states.get("light.allowed").state = "unavailable"
    assert "error" in await executor.execute(
        request("control_entity", {"entity_id": "light.allowed", "action": "turn_on"})
    )


@pytest.mark.asyncio
async def test_instance_deadline_dedup_and_shutdown(executor):
    msg = request("control_entity", {"entity_id": "light.allowed", "action": "turn_on"})
    assert "error" not in await executor.execute(msg)
    assert (await executor.execute(msg))["error"]["code"] == "DUPLICATE_REQUEST"
    msg = request()
    msg["body"]["instance_id"] = "other-instance"
    assert (await executor.execute(msg))["error"]["code"] == "INSTANCE_MISMATCH"
    assert (await executor.execute(request(expires_at_ms=0)))["error"][
        "code"
    ] == "DEADLINE_EXCEEDED"
    executor.active = False
    assert (await executor.execute(request()))["error"]["code"] == "DISCONNECTED"
    assert executor.hass.services.async_call.await_count == 1


@pytest.mark.asyncio
async def test_native_deadline_reports_uncertain(executor):
    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    executor.hass.services.async_call.side_effect = slow
    msg = request(
        "control_entity",
        {"entity_id": "light.allowed", "action": "turn_on"},
        timeout_ms=10,
    )
    result = await executor.execute(msg)
    assert result["error"] == {"code": "DEADLINE_EXCEEDED", "outcome": "uncertain"}
    assert await executor.execute(msg) == {"error": {"code": "DUPLICATE_REQUEST"}}
    assert executor.hass.services.async_call.await_count == 1


@pytest.mark.parametrize("brightness", [0, -1])
async def test_brightness_cannot_bypass_turn_off_permission(executor, brightness):
    executor.entry.options["turn_off_entities"] = []
    result = await executor.execute(
        request(
            "control_entity",
            {
                "entity_id": "light.allowed",
                "action": "turn_on",
                "brightness": brightness,
            },
        )
    )
    assert result == {"error": {"code": "ACTION_NOT_ALLOWED"}}
    executor.hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("brightness", [1, 255])
async def test_brightness_boundaries_do_not_require_turn_off_permission(
    executor, brightness
):
    executor.entry.options["turn_off_entities"] = []
    result = await executor.execute(
        request(
            "control_entity",
            {
                "entity_id": "light.allowed",
                "action": "turn_on",
                "brightness": brightness,
            },
        )
    )
    assert "error" not in result
    executor.hass.services.async_call.assert_awaited_once()


@pytest.mark.parametrize("lag_ms", [0, 300, 1000, 5000])
async def test_gateway_shaped_deadline_tolerates_clock_lag(
    executor, monkeypatch, lag_ms
):
    # Gateway spent 150ms before dispatch; delivery took 50ms. A fresh
    # request still has 14.8s of the original gateway deadline remaining.
    sent_ms = 1_000_000
    monkeypatch.setattr(
        "custom_components.toolforest.executor.time.time",
        lambda: (sent_ms + 50 - lag_ms) / 1000,
    )
    msg = request(timeout_ms=14850, expires_at_ms=sent_ms + 14850)
    assert "error" not in await executor.execute(msg)


@pytest.mark.parametrize("expiry_offset", [-1, 0, 20001])
async def test_expired_or_excessively_future_deadlines_are_denied(
    executor, monkeypatch, expiry_offset
):
    monkeypatch.setattr("custom_components.toolforest.executor.time.time", lambda: 1000)
    result = await executor.execute(request(expires_at_ms=1_000_000 + expiry_offset))
    assert result == {"error": {"code": "DEADLINE_EXCEEDED"}}


@pytest.mark.parametrize(
    "updates",
    [
        {"correlation_id": None},
        {"correlation_id": ""},
        {"timeout_ms": True},
        {"timeout_ms": 0},
        {"timeout_ms": 15001},
        {"expires_at_ms": "tomorrow"},
    ],
)
async def test_malformed_envelope_is_not_reported_as_expired(executor, updates):
    assert await executor.execute(request(**updates)) == {
        "error": {"code": "INVALID_ARGUMENT"}
    }


async def test_clock_lag_does_not_extend_relative_execution_timeout(
    executor, monkeypatch
):
    now = time.time()
    monkeypatch.setattr(
        "custom_components.toolforest.executor.time.time", lambda: now - 1
    )

    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    executor.hass.services.async_call.side_effect = slow
    result = await executor.execute(
        request(
            "control_entity",
            {"entity_id": "light.allowed", "action": "turn_on"},
            timeout_ms=10,
            expires_at_ms=int(now * 1000) + 14850,
        )
    )
    assert result == {"error": {"code": "DEADLINE_EXCEEDED", "outcome": "uncertain"}}


async def test_dedupe_survives_short_timeout_and_wall_clock_correction(
    executor, monkeypatch
):
    wall, monotonic = [1000.0], [100.0]
    monkeypatch.setattr(
        "custom_components.toolforest.executor.time.time", lambda: wall[0]
    )
    # Patch the executor's clock reference, without replacing the event loop's
    # global monotonic clock, which would affect pytest/asyncio timeout handling.
    from types import SimpleNamespace

    monkeypatch.setattr(
        "custom_components.toolforest.executor.time",
        SimpleNamespace(time=lambda: wall[0], monotonic=lambda: monotonic[0]),
    )
    msg = request(timeout_ms=100, expires_at_ms=1000100)
    assert "error" not in await executor.execute(msg)
    wall[0], monotonic[0] = 999, 101
    assert await executor.execute(msg) == {"error": {"code": "DUPLICATE_REQUEST"}}
    # A correction in the opposite direction must not evict the ID either.
    wall[0], monotonic[0] = 1000.05, 102
    assert await executor.execute(msg) == {"error": {"code": "DUPLICATE_REQUEST"}}


async def test_full_dedupe_cache_does_not_evict_live_requests(executor):
    executor.seen = {str(i): time.monotonic() + 20 for i in range(1000)}
    assert await executor.execute(request()) == {"error": {"code": "BUSY"}}
    executor.seen = {"expired": time.monotonic() - 1}
    assert "error" not in await executor.execute(request())


def test_options_cannot_expose_restricted_entities():
    with pytest.raises(Denied):
        validate_exposure({"read_entities": ["lock.front_door"]})
    with pytest.raises(Denied):
        validate_exposure({"read_entities": [], "turn_on_entities": ["light.allowed"]})
