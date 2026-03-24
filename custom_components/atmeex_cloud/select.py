import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DAMPER_OPEN = "open"
DAMPER_MIXED = "mixed"
DAMPER_CLOSED = "closed"

DAMPER_OPTIONS = [DAMPER_OPEN, DAMPER_MIXED, DAMPER_CLOSED]

DAMPER_POS_MAP = {
    DAMPER_OPEN: 0,
    DAMPER_MIXED: 1,
    DAMPER_CLOSED: 2,
}

DAMPER_POS_REVERSE_MAP = {v: k for k, v in DAMPER_POS_MAP.items()}


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexDamperSelectEntity(device, coordinator) for device in coordinator.devices.values()])


class AtmeexDamperSelectEntity(AtmeexBaseEntity, SelectEntity):

    _attr_options = DAMPER_OPTIONS
    _attr_icon = "mdi:air-filter"
    _attr_translation_key = "damper_position"

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_damper"

    async def async_select_option(self, option: str):
        """Change the selected option."""
        damp_pos = DAMPER_POS_MAP.get(option)
        if damp_pos is None:
            _LOGGER.error("Unknown damper option: %s", option)
            return

        await self.device.set_damp_pos(damp_pos)
        self._sync_update()

    @property
    def current_option(self) -> str | None:
        return DAMPER_POS_REVERSE_MAP.get(self.device.model.settings.u_damp_pos)

    def _update_state(self):
        self._attr_available = True
