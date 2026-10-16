"""Connection status only; this integration does not create control entities."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, STATUS_SIGNAL


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ConnectionSensor(entry)])


class ConnectionSensor(SensorEntity):
    _attr_should_poll = False
    _attr_name = "Home Assistant toolkit connection"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-sync"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connection"

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{STATUS_SIGNAL}_{self.entry.entry_id}",
                self.async_write_ha_state,
            )
        )

    @property
    def native_value(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]["status"]

    @property
    def extra_state_attributes(self):
        return {
            "instance_id": self.entry.data["device_id"],
            "environment": self.entry.data["environment"],
        }
