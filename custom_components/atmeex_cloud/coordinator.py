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
        self.entry: ConfigEntry = entry

    async def _async_update_data(self):
        """Fetch data from API."""
        # Empty device map before data fetch, so if fetch fail, entities will be marked as unavailable
        self.devices = {}

        try:
            device_list = await self.api.get_devices()
        except AtmeexAuthError as err:
            raise ConfigEntryAuthFailed from err
        except httpx.HTTPStatusError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        self.devices = {device.model.id: device for device in device_list}

        if self.entry.data[CONF_ACCESS_TOKEN] != self.api.access_token or \
            self.entry.data[CONF_REFRESH_TOKEN] != self.api.refresh_token:

            data = dict(self.entry.data)
            data[CONF_ACCESS_TOKEN] = self.api.access_token
            data[CONF_REFRESH_TOKEN] = self.api.refresh_token

            self.hass.config_entries.async_update_entry(self.entry, data=data)
