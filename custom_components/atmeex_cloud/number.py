from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity
from .const import DOMAIN, SPEEDS


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexFanSpeedNumberEntity(device, coordinator) for device in coordinator.devices.values()])


class AtmeexFanSpeedNumberEntity(AtmeexBaseEntity, NumberEntity):
    """Fan speed as 1-7, for those who prefer it to the fan entity percentage."""

    _attr_native_min_value = 1
    _attr_native_max_value = len(SPEEDS)
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:fan"
    _attr_translation_key = "fan_speed"

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_fan_speed"

    async def async_set_native_value(self, value: float):
        """Set the speed, like the climate fan mode: power stays as it is, auto mode turns off."""
        # The device counts speeds from 0
        await self._async_set_fan_speed(round(value) - 1)
        self._sync_update()

    def _update_state(self):
        speed = self.device.model.settings.u_fan_speed
        self._attr_native_value = speed + 1 if 0 <= speed < len(SPEEDS) else None
