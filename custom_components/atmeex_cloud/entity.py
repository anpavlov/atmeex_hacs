"""Base entity class for Atmeex entities."""

import logging
from abc import abstractmethod

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from atmeexpy.device import Device

from .coordinator import AtmeexDataCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AtmeexBaseEntity(CoordinatorEntity):
    """Base class for Atmeex entities with common coordinator update handling."""

    _attr_has_entity_name = True

    def __init__(self, device: Device, coordinator: AtmeexDataCoordinator):
        """Initialize the base entity."""
        super().__init__(coordinator=coordinator)

        self.coordinator = coordinator
        self.device = device
        self.device_id = device.model.id

        self._update_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, str(self.device.model.id))},
            name=self.device.model.name,
            manufacturer="Atmeex",
            model=self.device.model.model,
            sw_version=self.device.model.fw_ver,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.device is None:
            return False

        if self.device.model.condition is not None:
            return True

        return self.device.model.online

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        updated_device = self.coordinator.devices.get(self.device_id, None)

        if updated_device is None:
            self._attr_available = False
            return

        self.device = updated_device
        self._update_state()
        self.async_write_ha_state()

    @abstractmethod
    def _update_state(self):
        """Update entity state from device data. Must be implemented by subclasses."""
        pass

    def _sync_update(self):
        """Sync entity state to coordinator after local changes."""
        self.coordinator.async_update_listeners()
