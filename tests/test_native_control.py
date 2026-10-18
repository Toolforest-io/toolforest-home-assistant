"""Verify permissions against HA's actual light service implementation."""

import time
from uuid import uuid4

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.components.light.const import DATA_COMPONENT
from homeassistant.setup import async_setup_component

from custom_components.toolforest.executor import Executor


class VirtualLight(LightEntity):
    _attr_name = "Virtual review light"
    _attr_should_poll = False
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_is_on = True
    _attr_brightness = 100

    def __init__(self):
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self.off_calls = 0

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self._attr_brightness = kwargs.get("brightness", self._attr_brightness)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self.off_calls += 1
        self._attr_is_on = False
        self.async_write_ha_state()


async def test_brightness_zero_cannot_reach_native_turn_off(hass, config_entry):
    assert await async_setup_component(hass, "light", {})
    light = VirtualLight()
    await hass.data[DATA_COMPONENT].async_add_entities([light])
    await hass.async_block_till_done()
    entity_id = light.entity_id
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            "read_entities": [entity_id],
            "turn_on_entities": [entity_id],
            "brightness_entities": [entity_id],
            "turn_off_entities": [],
        },
    )
    executor = Executor(hass, config_entry)

    async def call(action, **params):
        return await executor.execute(
            {
                "v": 1,
                "type": "request",
                "correlation_id": uuid4().hex,
                "timeout_ms": 1000,
                "expires_at_ms": int(time.time() * 1000) + 1000,
                "body": {
                    "instance_id": "old-instance",
                    "action": "control_entity",
                    "params": {"entity_id": entity_id, "action": action, **params},
                },
            }
        )

    assert await call("turn_on", brightness=0) == {
        "error": {"code": "ACTION_NOT_ALLOWED"}
    }
    assert hass.states.get(entity_id).state == "on"
    assert light.off_calls == 0
    assert "error" not in await call("turn_on", brightness=1)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["brightness"] == 1
    assert await call("turn_off") == {"error": {"code": "ACTION_NOT_ALLOWED"}}
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, "turn_off_entities": [entity_id]}
    )
    assert "error" not in await call("turn_off")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"
    assert light.off_calls == 1
