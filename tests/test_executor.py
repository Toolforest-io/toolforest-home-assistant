import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ha_toolforest.executor import Denied, Executor, validate_exposure


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


def test_options_cannot_expose_restricted_entities():
    with pytest.raises(Denied):
        validate_exposure({"read_entities": ["lock.front_door"]})
    with pytest.raises(Denied):
        validate_exposure({"read_entities": [], "turn_on_entities": ["light.allowed"]})
