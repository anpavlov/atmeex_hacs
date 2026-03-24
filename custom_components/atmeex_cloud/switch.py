import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexPowerSwitchEntity(device, coordinator) for device in coordinator.devices.values()])


class AtmeexPowerSwitchEntity(AtmeexBaseEntity, SwitchEntity):

    _attr_icon = "mdi:power"
    _attr_translation_key = "power"

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_power"

    @property
    def is_on(self) -> bool:
        return self.device.model.settings.u_pwr_on

    async def async_turn_on(self, **kwargs):
        """Turn on the breezer."""
        await self.device.set_power_and_damp(True, 0)
        self._sync_update()

    async def async_turn_off(self, **kwargs):
        """Turn off the breezer."""
        await self.device.set_power_and_damp(False, 2)
        self._sync_update()

    def _update_state(self):
        pass
