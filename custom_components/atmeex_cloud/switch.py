import logging
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AtmeexModeSwitchEntityDescription(SwitchEntityDescription):
    """Key is the device setting the switch controls."""

    # Auto and night modes exclude each other, but the cloud stores both as on;
    # the Atmeex app turns the other one off, so do the same
    exclusive_with: str


MODE_SWITCHES = (
    AtmeexModeSwitchEntityDescription(
        key="u_auto", translation_key="auto_mode", icon="mdi:brightness-auto", exclusive_with="u_night",
    ),
    AtmeexModeSwitchEntityDescription(
        key="u_night", translation_key="night_mode", icon="mdi:weather-night", exclusive_with="u_auto",
    ),
)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexPowerSwitchEntity(device, coordinator) for device in coordinator.devices.values()])
    async_add_entities(
        AtmeexModeSwitchEntity(device, coordinator, description)
        for device in coordinator.devices.values()
        for description in MODE_SWITCHES
    )


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
        await self._async_call_with_auth_check(self.device.set_power_and_damp(True, 0))
        self._sync_update()

    async def async_turn_off(self, **kwargs):
        """Turn off the breezer."""
        await self._async_call_with_auth_check(self.device.set_power_and_damp(False, 2))
        self._sync_update()

    def _update_state(self):
        pass


class AtmeexModeSwitchEntity(AtmeexBaseEntity, SwitchEntity):

    entity_description: AtmeexModeSwitchEntityDescription

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator, description: AtmeexModeSwitchEntityDescription):
        self.entity_description = description
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_{description.translation_key}"

    @property
    def is_on(self) -> bool:
        return getattr(self.device.model.settings, self.entity_description.key)

    async def async_turn_on(self, **kwargs):
        description = self.entity_description
        await self._async_set_mode({description.key: True, description.exclusive_with: False})

    async def async_turn_off(self, **kwargs):
        await self._async_set_mode({self.entity_description.key: False})

    async def _async_set_mode(self, params: dict[str, bool]):
        await self._async_call_with_auth_check(self._async_set_params(**params))
        self._sync_update()

    def _update_state(self):
        pass
