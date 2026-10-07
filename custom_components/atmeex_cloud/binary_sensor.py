from functools import partial

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity, async_add_entities_when_reported
from .const import DOMAIN, HUMIDIFIER_READING


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities_when_reported(coordinator, config_entry, async_add_entities, {
        HUMIDIFIER_READING: partial(AtmeexNoWaterBinarySensorEntity, coordinator=coordinator),
    })


class AtmeexNoWaterBinarySensorEntity(AtmeexBaseEntity, BinarySensorEntity):

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-off"
    _attr_translation_key = "no_water"

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_no_water"

    def _update_state(self):
        no_water = self.coordinator.get_reading(self.device_id, "no_water")
        self._attr_is_on = None if no_water is None else bool(no_water)
