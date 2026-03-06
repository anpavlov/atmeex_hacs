import logging

from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PRECISION_HALVES, UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from atmeexpy.device import Device

from . import AtmeexDataCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([AtmeexClimateEntity(device, coordinator) for device in coordinator.devices.values()])

class AtmeexClimateEntity(CoordinatorEntity, ClimateEntity):

    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF]
    _attr_min_temp = 10
    _attr_max_temp = 30
    _attr_fan_modes = ["Скорость 1", "Скорость 2", "Скорость 3", "Скорость 4", "Скорость 5", "Скорость 6", "Скорость 7"]
    _attr_precision = PRECISION_HALVES
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
    _attr_icon = 'mdi:air-purifier'
    _attr_translation_key = DOMAIN
    _attr_fan_mode: int


    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        CoordinatorEntity.__init__(self, coordinator=coordinator)

        self.coordinator = coordinator
        self.device = device
        self.device_id = device.model.id

        self._attr_unique_id = str(device.model.id)

        self._last_mode = None
        self._last_temp = None
        self._update_state()

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
            await self.device.set_power(False)
        elif hvac_mode == HVACMode.HEAT:
            saved_target_temp = self.target_temperature
            if saved_target_temp is None:
                saved_target_temp = self._last_temp

            if saved_target_temp is None:
                saved_target_temp = self.device.model.settings.u_temp_room / 10
                if saved_target_temp == -100:
                    saved_target_temp = 10

            if self.hvac_mode == HVACMode.OFF:
                await self.device.set_power(True)

            await self.device.set_heat_temp(saved_target_temp*10)
        elif hvac_mode == HVACMode.FAN_ONLY:
            if self.hvac_mode == HVACMode.OFF:
                await self.device.set_power(True)

            await self.device.set_heat_temp(-1000)
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return

        self._sync_update()

    async def async_set_fan_mode(self, fan_mode: str):
        await self.device.set_fan_speed(int(fan_mode.split(" ")[1])-1)

        self._sync_update()

    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.device.set_heat_temp(temperature*10)

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

    def _handle_coordinator_update(self) -> None:
        updated_device = self.coordinator.devices.get(self.device_id, None)

        if updated_device is None:
            self._attr_available = False
            return

        if self.device.model.settings == updated_device.model.settings:
            return

        self.device = updated_device
        self._update_state()

        self.async_write_ha_state()

    def _update_state(self):
        self._attr_fan_mode = "Скорость " + str(self.device.model.settings.u_fan_speed+1)
        if self.device.model.settings.u_temp_room != -1000:
            self._attr_target_temperature = self.device.model.settings.u_temp_room/10
        else:
            if self.target_temperature is not None:
                self._last_temp = self.target_temperature
            self._attr_target_temperature = None
        self._attr_hvac_mode = HVACMode.OFF if not self.device.model.settings.u_pwr_on else \
            HVACMode.HEAT if self.device.model.settings.u_temp_room > 0 else HVACMode.FAN_ONLY


    def _sync_update(self):
        self._update_state()
        self.async_write_ha_state()

        self.coordinator.devices[self.device_id].model.settings = self.device.model.settings
        self.coordinator.async_update_listeners()
