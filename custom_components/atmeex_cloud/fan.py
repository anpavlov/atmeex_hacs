import logging

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity
from .const import DOMAIN, SPEEDS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexFanEntity(device, coordinator) for device in coordinator.devices.values()])


class AtmeexFanEntity(AtmeexBaseEntity, FanEntity):

    _attr_speed_count = 7
    _attr_translation_key = "fan"

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_fan"

    @property
    def supported_features(self) -> FanEntityFeature:
        return FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    @property
    def is_on(self) -> bool:
        return self.device.model.settings.u_pwr_on

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        if not self.is_on:
            return 0

        speed_index = self.device.model.settings.u_fan_speed
        if speed_index < 0 or speed_index > 6:
            return None

        speed_name = SPEEDS[speed_index]
        return ordered_list_item_to_percentage(SPEEDS, speed_name)

    async def async_set_percentage(self, percentage: int):
        """Set the speed percentage."""
        if percentage == 0:
            await self.async_turn_off()
            return

        speed_name = percentage_to_ordered_list_item(SPEEDS, percentage)
        speed_index = SPEEDS.index(speed_name)

        # Turn on if off
        if not self.is_on:
            await self.device.set_power_only(True)

        await self.device.set_fan_speed(speed_index)
        self._sync_update()

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs):
        """Turn on the fan."""
        if not self.is_on:
            await self.device.set_power_only(True)

        if percentage is not None:
            speed_name = percentage_to_ordered_list_item(SPEEDS, percentage)
            speed_index = SPEEDS.index(speed_name)
            await self.device.set_fan_speed(speed_index)

        self._sync_update()

    async def async_turn_off(self, **kwargs):
        """Turn off the fan."""
        await self.device.set_power_only(False)
        self._sync_update()

    def _update_state(self):
        pass
