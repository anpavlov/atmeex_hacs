from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN

async def async_setup_entry(hass, config_entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]