import logging
from functools import partial

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity, async_add_entities_when_reported
from .const import DOMAIN, HUMIDIFIER_READING

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

# Option index is the humidification stage (u_hum_stg)
HUMIDIFIER_OPTIONS = ["off", "stage_1", "stage_2", "stage_3"]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexDamperSelectEntity(device, coordinator) for device in coordinator.devices.values()])

    async_add_entities_when_reported(coordinator, config_entry, async_add_entities, {
        HUMIDIFIER_READING: partial(AtmeexHumidifierSelectEntity, coordinator=coordinator),
    })


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

        await self._async_call_with_auth_check(self.device.set_damp_pos(damp_pos))
        self._sync_update()

    @property
    def current_option(self) -> str | None:
        return DAMPER_POS_REVERSE_MAP.get(self.device.model.settings.u_damp_pos)

    def _update_state(self):
        self._attr_available = True


class AtmeexHumidifierSelectEntity(AtmeexBaseEntity, SelectEntity):

    _attr_options = HUMIDIFIER_OPTIONS
    _attr_icon = "mdi:air-humidifier"
    _attr_translation_key = "humidifier"

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_humidifier"

    async def async_select_option(self, option: str):
        """Change the humidification stage."""
        await self._async_call_with_auth_check(self._async_set_params(u_hum_stg=HUMIDIFIER_OPTIONS.index(option)))
        self._sync_update()

    @property
    def current_option(self) -> str | None:
        stage = self.device.model.settings.u_hum_stg
        if stage not in range(len(HUMIDIFIER_OPTIONS)):
            return None

        return HUMIDIFIER_OPTIONS[stage]

    def _update_state(self):
        pass
