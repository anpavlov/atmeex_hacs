from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfRatio, UnitOfTemperature

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .entity import AtmeexBaseEntity
from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class AtmeexSensorEntityDescription(SensorEntityDescription):
    """Sensor description, key is the reading name in the device condition."""

    divider: int = 1


SENSORS = (
    AtmeexSensorEntityDescription(
        key="temp_room",
        translation_key="temp_room",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        divider=10,
    ),
    AtmeexSensorEntityDescription(
        key="temp_in",
        translation_key="temp_in",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        divider=10,
    ),
    AtmeexSensorEntityDescription(
        key="hum_room",
        translation_key="hum_room",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    AtmeexSensorEntityDescription(
        key="co2_ppm",
        translation_key="co2_ppm",
        device_class=SensorDeviceClass.CO2,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
    ),
)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator: AtmeexDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    added: set[str] = set()

    # Not every device has every sensor, create only the ones it reports.
    # Readings may be missing on the first fetch (device offline), so check on every update.
    @callback
    def add_new_sensors():
        new_entities = []
        for device in coordinator.devices.values():
            for description in SENSORS:
                unique_id = f"{device.model.id}_{description.key}"
                if unique_id in added or coordinator.get_reading(device.model.id, description.key) is None:
                    continue

                added.add(unique_id)
                new_entities.append(AtmeexSensorEntity(device, coordinator, description))

        if new_entities:
            async_add_entities(new_entities)

    add_new_sensors()
    config_entry.async_on_unload(coordinator.async_add_listener(add_new_sensors))


class AtmeexSensorEntity(AtmeexBaseEntity, SensorEntity):

    entity_description: AtmeexSensorEntityDescription

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator, description: AtmeexSensorEntityDescription):
        # Base __init__ calls _update_state, which needs the description
        self.entity_description = description
        super().__init__(device, coordinator)

        self._attr_unique_id = f"{device.model.id}_{description.key}"

    def _update_state(self):
        description = self.entity_description
        self._attr_native_value = self.coordinator.get_reading(self.device_id, description.key, description.divider)
