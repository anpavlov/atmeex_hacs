import logging

from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PRECISION_HALVES, UnitOfTemperature, ATTR_TEMPERATURE

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity
from .const import DOMAIN, SPEEDS

_LOGGER = logging.getLogger(__name__)

# Preset modes for damper position
PRESET_SUPPLY = "supply"        # damp_pos=0, open damper
PRESET_MIXED = "mixed"          # damp_pos=1, mixed mode
PRESET_RECIRCULATION = "recirculation"  # damp_pos=2, closed damper

PRESET_MODES = [PRESET_SUPPLY, PRESET_MIXED, PRESET_RECIRCULATION]

DAMPER_TO_PRESET = {
    0: PRESET_SUPPLY,
    1: PRESET_MIXED,
    2: PRESET_RECIRCULATION,
}

PRESET_TO_DAMPER = {v: k for k, v in DAMPER_TO_PRESET.items()}


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexClimateEntity(device, coordinator) for device in coordinator.devices.values()])


class AtmeexClimateEntity(AtmeexBaseEntity, ClimateEntity):

    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF]
    _attr_min_temp = 10
    _attr_max_temp = 30
    _attr_fan_modes = SPEEDS
    _attr_preset_modes = PRESET_MODES
    _attr_precision = PRECISION_HALVES
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.FAN_MODE |
        ClimateEntityFeature.PRESET_MODE |
        ClimateEntityFeature.TURN_ON |
        ClimateEntityFeature.TURN_OFF
    )
    _attr_icon = 'mdi:air-purifier'
    _attr_translation_key = DOMAIN
    _attr_fan_mode: int
    _attr_name = None


    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        super().__init__(device, coordinator)

        self._attr_unique_id = str(device.model.id)

        self._last_mode = None
        self._last_temp = None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        """Set hvac mode."""
        _LOGGER.info("Need to set mode to %s, current mode is %s", hvac_mode, self.hvac_mode)
        if self.hvac_mode == hvac_mode:
            # Do nothing if mode is same
            _LOGGER.debug(f"{self.name} is asked for mode {hvac_mode}, but it is already in {self.hvac_mode}. Do "
                          f"nothing.")
            pass
        elif hvac_mode == HVACMode.OFF:
            self._last_mode = self.hvac_mode
            await self._async_call_with_auth_check(self.device.set_power_and_damp(False, 2))
        elif hvac_mode == HVACMode.HEAT:
            saved_target_temp = self.target_temperature
            if saved_target_temp is None:
                saved_target_temp = self._last_temp

            if saved_target_temp is None:
                saved_target_temp = self.device.model.settings.u_temp_room / 10
                if saved_target_temp == -100:
                    saved_target_temp = 10

            if self.hvac_mode == HVACMode.OFF:
                # Turn on with open damper for heating
                await self._async_call_with_auth_check(self.device.set_power_and_damp(True, 0))
            elif self.device.model.settings.u_damp_pos != 0:
                # Open damper for heating if it was closed/mixed
                await self._async_call_with_auth_check(self.device.set_damp_pos(0))

            await self._async_call_with_auth_check(self.device.set_heat_temp(saved_target_temp*10))
        elif hvac_mode == HVACMode.FAN_ONLY:
            if self.hvac_mode == HVACMode.OFF:
                # Breezer anyway opens damp when turning on power
                await self._async_call_with_auth_check(self.device.set_power_and_damp(True, 0))

            await self._async_call_with_auth_check(self.device.set_heat_temp(-1000))
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return

        self._sync_update()

    async def async_set_fan_mode(self, fan_mode: str):
        await self._async_call_with_auth_check(
            self.device.set_fan_speed(int(fan_mode.split("_")[1])-1)
        )

        self._sync_update()

    async def async_set_preset_mode(self, preset_mode: str):
        """Set preset mode (damper position)."""
        damp_pos = PRESET_TO_DAMPER.get(preset_mode)
        if damp_pos is None:
            _LOGGER.error("Unknown preset mode: %s", preset_mode)
            return

        await self._async_call_with_auth_check(self.device.set_damp_pos(damp_pos))
        self._sync_update()

    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._async_call_with_auth_check(self.device.set_heat_temp(temperature*10))

        self._sync_update()

    async def async_turn_on(self):
        if self.hvac_mode != HVACMode.OFF:
            # do nothing if we already working
            pass
        elif self._last_mode is None:
            await self.async_set_hvac_mode(HVACMode.FAN_ONLY)
        else:
            await self.async_set_hvac_mode(self._last_mode)

    async def async_turn_off(self):
        _LOGGER.debug(f"Turning off from {self.hvac_mode}")
        await self.async_set_hvac_mode(HVACMode.OFF)

    def _update_state(self):
        if self.device is None:
            return

        self._attr_fan_mode = "speed_" + str(self.device.model.settings.u_fan_speed+1)
        if self.device.model.settings.u_temp_room != -1000:
            self._attr_target_temperature = self.device.model.settings.u_temp_room/10
        else:
            if self.target_temperature is not None:
                self._last_temp = self.target_temperature
            self._attr_target_temperature = None

        # Determine HVAC mode based on power, damper position, and heating
        # damp_pos: 0=open, 1=mixed, 2=closed
        damp_pos = self.device.model.settings.u_damp_pos
        pwr_on = self.device.model.settings.u_pwr_on
        temp_room = self.device.model.settings.u_temp_room

        # Set preset mode based on damper position
        self._attr_preset_mode = DAMPER_TO_PRESET.get(damp_pos)

        if not pwr_on:
            self._attr_hvac_mode = HVACMode.OFF
        elif damp_pos == 2:
            # Closed damper = recirculation mode (indoor air ventilation)
            self._attr_hvac_mode = HVACMode.FAN_ONLY
        elif temp_room > 0:
            self._attr_hvac_mode = HVACMode.HEAT
        else:
            self._attr_hvac_mode = HVACMode.FAN_ONLY
