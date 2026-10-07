"""Base entity class for Atmeex entities."""

import httpx
import logging
from abc import abstractmethod
from typing import Any, Awaitable, Callable, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from atmeexpy.device import Device
from atmeexpy.exceptions import AtmeexAuthError

from .coordinator import AtmeexDataCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


@callback
def async_add_entities_when_reported(
    coordinator: AtmeexDataCoordinator,
    config_entry: ConfigEntry,
    async_add_entities,
    factories: dict[str, Callable[[Device], Entity]],
):
    """Add entities once their device reports the reading they need.

    factories maps a reading key to a function that creates the entity for a device.
    Readings may be missing on the first fetch (device offline), so check on every update.
    """
    added: set[tuple[int, str]] = set()

    @callback
    def add_new_entities():
        new_entities = []
        for device_id, device in coordinator.devices.items():
            for key, factory in factories.items():
                if (device_id, key) in added or coordinator.get_reading(device_id, key) is None:
                    continue

                added.add((device_id, key))
                new_entities.append(factory(device))

        if new_entities:
            async_add_entities(new_entities)

    add_new_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


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
        # A failed poll or a device removed from the account
        if not super().available or self.device_id not in self.coordinator.devices:
            return False

        if self.device.model.condition is not None:
            return True

        return self.device.model.online

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        updated_device = self.coordinator.devices.get(self.device_id, None)

        if updated_device is not None:
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

    async def _async_set_params(self, **params: Any) -> None:
        """Set device params that atmeexpy has no setters for."""
        resp = await self.coordinator.api.http_client.put(f"/devices/{self.device_id}/params", json=params)
        resp.raise_for_status()

        # Show the new values right away, the next poll brings the values stored in the cloud
        for key, value in params.items():
            setattr(self.device.model.settings, key, value)

    async def _async_set_fan_speed(self, speed_index: int, power_on: bool = False) -> None:
        """Set fan speed (0-6) in one request; auto mode would override it, so turn auto mode off too."""
        params = {"u_fan_speed": speed_index, "u_auto": False}
        if power_on:
            params["u_pwr_on"] = True

        await self._async_call_with_auth_check(self._async_set_params(**params))

    async def _async_call_with_auth_check(self, coro: Awaitable[T]) -> T:
        """Execute API call with auth error handling."""
        try:
            return await coro
        except AtmeexAuthError as err:
            # Start reauth flow
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "Authentication expired. Please reconfigure the integration."
            ) from err
        except (httpx.HTTPError, ValueError) as err:
            # ValueError: atmeexpy setters parse the response, which may be a non-JSON error page
            raise HomeAssistantError(f"Communication error: {type(err).__name__} {err}") from err
