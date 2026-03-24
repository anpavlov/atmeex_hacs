"""Coordinator for Atmeex integration."""

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from atmeexpy.client import AtmeexClient

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
        device_list = await self.api.get_devices()

        self.devices = {device.model.id: device for device in device_list}

        if self.entry.data[CONF_ACCESS_TOKEN] != self.api.auth._access_token or \
            self.entry.data[CONF_REFRESH_TOKEN] != self.api.auth._refresh_token:

            data = dict(self.entry.data)
            data[CONF_ACCESS_TOKEN] = self.api.auth._access_token
            data[CONF_REFRESH_TOKEN] = self.api.auth._refresh_token

            self.hass.config_entries.async_update_entry(self.entry, data=data)
