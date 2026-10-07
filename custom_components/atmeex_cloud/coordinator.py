"""Coordinator for Atmeex integration."""

import httpx
from datetime import timedelta
import logging

from dacite import DaciteError

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from atmeexpy.client import AtmeexClient
from atmeexpy.device import Device
from atmeexpy.exceptions import AtmeexAuthError

from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, ZERO_MEANS_MISSING

_LOGGER = logging.getLogger(__name__)


class AtmeexDataCoordinator(DataUpdateCoordinator):
    """Coordinator for Atmeex devices."""

    def __init__(self, hass: HomeAssistant, api: AtmeexClient, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name="Atmeex Coordinator",
            update_interval=timedelta(seconds=30),
        )

        self.hass = hass
        self.api = api
        self.devices = {}
        self.conditions: dict[int, dict] = {}
        self.entry: ConfigEntry = entry

    async def _async_update_data(self):
        """Fetch data from API."""
        # Keep the previous devices on failure: entities go unavailable through last_update_success
        try:
            device_list = await self._async_fetch_devices()

            conditions = {}
            devices = {}
            for data in device_list:
                # Readings are kept raw and read one by one instead of parsing them with the strict
                # DeviceConditionModel: a null or missing field only empties that reading
                condition = data.pop("condition", None)
                conditions[data["id"]] = condition if isinstance(condition, dict) else {}
                devices[data["id"]] = Device(self.api.http_client, data)
        except AtmeexAuthError as err:
            raise ConfigEntryAuthFailed from err
        except httpx.HTTPError as err:
            raise UpdateFailed(f"Error communicating with API: {type(err).__name__} {err}") from err
        except (ValueError, TypeError, KeyError, AttributeError, DaciteError) as err:
            raise UpdateFailed(f"Unexpected API response: {err}") from err
        finally:
            # Tokens may be refreshed during the request even if the response turns out unusable
            self._save_tokens()

        self.conditions = conditions
        self.devices = devices

    async def _async_fetch_devices(self) -> list:
        # The plain device list has no readings, with_condition appends them
        try:
            resp = await self.api.http_client.get("/devices", params={"with_condition": 1})
        except httpx.TransportError as err:
            # The cloud drops a request now and then, a retry keeps entities from going unavailable for a minute
            _LOGGER.debug("Retrying device list request after %s", type(err).__name__)
            resp = await self.api.http_client.get("/devices", params={"with_condition": 1})

        resp.raise_for_status()
        return resp.json()

    def _save_tokens(self):
        if self.entry.data[CONF_ACCESS_TOKEN] == self.api.access_token and \
            self.entry.data[CONF_REFRESH_TOKEN] == self.api.refresh_token:
            return

        data = dict(self.entry.data)
        data[CONF_ACCESS_TOKEN] = self.api.access_token
        data[CONF_REFRESH_TOKEN] = self.api.refresh_token

        self.hass.config_entries.async_update_entry(self.entry, data=data)

    def get_reading(self, device_id: int, key: str, divider: int = 1) -> float | int | None:
        """Return sensor reading, or None if the device does not report it."""
        value = self.conditions.get(device_id, {}).get(key)
        if not isinstance(value, (int, float)):
            return None

        if value == 0 and key in ZERO_MEANS_MISSING:
            return None

        return value / divider if divider > 1 else value
