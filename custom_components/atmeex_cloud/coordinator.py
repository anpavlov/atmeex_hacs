"""Coordinator for Atmeex integration."""

import copy
import httpx
from datetime import timedelta
import logging

from dacite import DaciteError

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from atmeexpy.client import AtmeexClient
from atmeexpy.device import Device
from atmeexpy.exceptions import AtmeexAuthError

from .const import CONF_ACCESS_TOKEN, CONF_CLOUD_RELAY, CONF_REFRESH_TOKEN, DOMAIN, ZERO_MEANS_MISSING
from .local import LOCAL_PORT, AtmeexLocalServer, AtmeexLocalSession

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


def _identity(devices: list[dict]) -> list[tuple]:
    """What makes a stored device list outdated; settings change all the time and come from the breezer."""
    return [(data["id"], data["mac"], data["name"]) for data in devices]


def _fill_dropped_fields(data: dict, condition: dict) -> None:
    """Fill fields atmeexpy requires that the cloud stopped sending after its October 2026 restart."""
    if data.get("socket_id") is None:
        data["socket_id"] = ""
    if data.get("fw_ver") is None:
        data["fw_ver"] = condition.get("firmware_version") or ""

    settings = data["settings"]
    for key, default in (("id", 0), ("device_id", data["id"]), ("u_cool_mode", False)):
        if settings.get(key) is None:
            settings[key] = default


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
        self.local: AtmeexLocalServer | None = None

        # Device list from the cloud without readings; also stored to start the local server without the cloud
        self._cloud_devices: list[dict] = []
        self._cloud_conditions: dict[int, dict] = {}
        self._cloud_available = True
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._stored_identity: list[tuple] | None = None

    async def async_start_local_server(self):
        """Serve breezers redirected to Home Assistant, starting from the stored device list."""
        stored = await self._store.async_load() or []
        try:
            for data in stored:
                Device(self.api.http_client, copy.deepcopy(data))
        except (TypeError, KeyError, AttributeError, DaciteError) as err:
            _LOGGER.warning("Ignoring stored devices: %s", err)
        else:
            self._cloud_devices = stored
            self._stored_identity = _identity(stored)

        self.local = AtmeexLocalServer(
            LOCAL_PORT, self._is_known_device, self._async_local_update,
            relay_to_cloud=self.entry.options.get(CONF_CLOUD_RELAY, True),
        )
        await self.local.async_start()

    async def async_stop_local_server(self):
        if self.local is not None:
            await self.local.async_stop()

    async def _async_update_data(self):
        """Fetch data from API."""
        # Keep the previous devices on failure: entities go unavailable through last_update_success
        try:
            self._cloud_devices, self._cloud_conditions = await self._async_fetch_cloud()
        except (UpdateFailed, ConfigEntryAuthFailed) as err:
            # Breezers connected to Home Assistant don't need the cloud
            if self.local is None or not self._cloud_devices:
                raise

            if isinstance(err, ConfigEntryAuthFailed):
                if not self._reauth_flows():
                    _LOGGER.warning("Atmeex cloud rejected the saved sign-in, asking to sign in again")
                self.entry.async_start_reauth(self.hass)
            else:
                self._async_abort_reauth()
            if self._cloud_available:
                _LOGGER.warning("Atmeex cloud unavailable, only breezers connected to Home Assistant work: %s", err)
            self._cloud_available = False
            self._cloud_conditions = {}
        else:
            if not self._cloud_available:
                _LOGGER.info("Atmeex cloud is back")
            self._cloud_available = True
            await self._async_store_devices()

        self._build_devices()

    def _reauth_flows(self) -> list:
        return list(self.entry.async_get_active_flows(self.hass, {SOURCE_REAUTH}))

    @callback
    def _async_abort_reauth(self):
        """Signing in is impossible while the cloud doesn't answer, its next refusal asks again."""
        for flow in self._reauth_flows():
            _LOGGER.warning("Atmeex cloud unavailable, withdrawing the sign-in request until it answers")
            self.hass.config_entries.flow.async_abort(flow["flow_id"])

    async def _async_fetch_cloud(self) -> tuple[list[dict], dict[int, dict]]:
        try:
            device_list = await self._async_fetch_devices()

            conditions = {}
            for data in device_list:
                # Readings are kept raw and read one by one instead of parsing them with the strict
                # DeviceConditionModel: a null or missing field only empties that reading
                condition = data.pop("condition", None)
                condition = condition if isinstance(condition, dict) else {}
                conditions[data["id"]] = condition
                _fill_dropped_fields(data, condition)
                Device(self.api.http_client, data)
        except AtmeexAuthError as err:
            raise ConfigEntryAuthFailed from err
        except httpx.HTTPError as err:
            raise UpdateFailed(f"Error communicating with API: {type(err).__name__} {err}") from err
        except (ValueError, TypeError, KeyError, AttributeError, DaciteError) as err:
            raise UpdateFailed(f"Unexpected API response: {err}") from err
        finally:
            # Tokens may be refreshed during the request even if the response turns out unusable
            self._save_tokens()

        return device_list, conditions

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

    async def _async_store_devices(self):
        if (identity := _identity(self._cloud_devices)) == self._stored_identity:
            return

        self._stored_identity = identity
        await self._store.async_save(self._cloud_devices)

    @callback
    def _build_devices(self):
        """Combine the cloud device list with what breezers connected to Home Assistant report."""
        devices = {}
        conditions = {}
        for cloud_data in self._cloud_devices:
            data = copy.deepcopy(cloud_data)
            device_id = data["id"]
            condition = self._cloud_conditions.get(device_id, {})

            session = self._local_session(data["mac"])
            if session is not None and session.ready:
                data["settings"].update(session.settings)
                data["online"] = True
                data["fw_ver"] = session.fw_ver or data["fw_ver"]
                condition = session.state
            elif not self._cloud_available:
                data["online"] = False

            devices[device_id] = Device(self.api.http_client, data)
            conditions[device_id] = condition

        self.devices = devices
        self.conditions = conditions

    def _local_session(self, mac: str) -> AtmeexLocalSession | None:
        return self.local.sessions.get(mac.upper()) if self.local is not None else None

    def _is_known_device(self, mac: str) -> bool:
        return any(data["mac"].upper() == mac for data in self._cloud_devices)

    @callback
    def _async_local_update(self):
        self._build_devices()
        self.async_update_listeners()

    async def async_set_params(self, device: Device, params: dict) -> None:
        """Change device settings, through the breezer's own connection if it has one."""
        if (session := self._local_session(device.model.mac)) is not None:
            await session.async_set_params(params)
            return

        resp = await self.api.http_client.put(f"/devices/{device.model.id}/params", json=params)
        resp.raise_for_status()

        # Devices are rebuilt on every local update, keep the new settings until the next poll brings them
        for data in self._cloud_devices:
            if data["id"] == device.model.id:
                data["settings"].update(params)

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
