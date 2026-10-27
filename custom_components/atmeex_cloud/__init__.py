"""Atmeex Cloud integration."""

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.httpx_client import create_async_httpx_client

from atmeexpy.client import AtmeexClient

from .const import CONF_ACCESS_TOKEN, CONF_LOCAL_SERVER, CONF_REFRESH_TOKEN, DOMAIN, PLATFORMS
from .coordinator import AtmeexDataCoordinator
from .local import LOCAL_PORT


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the integration."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up from a config entry."""
    http_client = create_async_httpx_client(hass)
    api = AtmeexClient(http_client)
    api.restore_tokens(entry.data[CONF_ACCESS_TOKEN], entry.data[CONF_REFRESH_TOKEN])

    coordinator = AtmeexDataCoordinator(hass, api, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    if entry.options.get(CONF_LOCAL_SERVER):
        try:
            await coordinator.async_start_local_server()
        except OSError as err:
            raise ConfigEntryNotReady(f"Can't listen on port {LOCAL_PORT}: {err}") from err

        async def async_stop_local_server(_event=None):
            await coordinator.async_stop_local_server()

        # Also runs if the setup below fails
        entry.async_on_unload(async_stop_local_server)
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop_local_server))

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    hass.data[DOMAIN].pop(entry.entry_id)
    return True
