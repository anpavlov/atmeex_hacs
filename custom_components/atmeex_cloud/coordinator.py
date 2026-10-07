"""Coordinator for Atmeex integration."""

import httpx
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from atmeexpy.client import AtmeexClient
from atmeexpy.exceptions import AtmeexAuthError

from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN

_LOGGER = logging.getLogger(__name__)


class AtmeexDataCoordinator(DataUpdateCoordinator):
    """Coordinator for Atmeex devices."""

    def __init__(self, hass: HomeAssistant, api: AtmeexClient, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name="Atmeex Coordinator",
            update_interval=timedelta(seconds=60),
        )

        self.hass = hass
        self.api = api
        self.devices = {}
        self.conditions: dict[int, dict] = {}
        self.entry: ConfigEntry = entry

    async def _async_update_data(self):
        """Fetch data from API."""
        # Empty device map before data fetch, so if fetch fail, entities will be marked as unavailable
        self.devices = {}

        try:
            device_list = await self.api.get_devices()
            conditions = {device.model.id: await self._async_fetch_condition(device.model.id) for device in device_list}
        except AtmeexAuthError as err:
            raise ConfigEntryAuthFailed from err
        except httpx.HTTPStatusError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        self.devices = {device.model.id: device for device in device_list}
        self.conditions = conditions

        if self.entry.data[CONF_ACCESS_TOKEN] != self.api.access_token or \
            self.entry.data[CONF_REFRESH_TOKEN] != self.api.refresh_token:

            data = dict(self.entry.data)
            data[CONF_ACCESS_TOKEN] = self.api.access_token
            data[CONF_REFRESH_TOKEN] = self.api.refresh_token

            self.hass.config_entries.async_update_entry(self.entry, data=data)

    async def _async_fetch_condition(self, device_id: int) -> dict:
        """Fetch current sensor readings, the device list endpoint does not include them."""
        # Readings are optional, their failure must not make device controls unavailable
        try:
            resp = await self.api.http_client.get(f"/devices/{device_id}")
            resp.raise_for_status()
        except httpx.HTTPError as err:
            _LOGGER.warning("Failed to fetch readings for device %s: %s", device_id, err)
            return {}

        return resp.json().get("condition") or {}

    def get_reading(self, device_id: int, key: str, divider: int = 1) -> float | int | None:
        """Return sensor reading, or None if the device does not report it."""
        value = self.conditions.get(device_id, {}).get(key)
        if not isinstance(value, (int, float)):
            return None

        return value / divider if divider > 1 else value
