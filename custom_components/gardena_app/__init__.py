"""GARDENA smart system via the app API: schedules, valves, gateway, sensors."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GardenaAppClient, GardenaAuthError, GardenaError
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, PLATFORMS
from .coordinator import GardenaCoordinator

type GardenaConfigEntry = ConfigEntry[GardenaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GardenaConfigEntry) -> bool:
    client = GardenaAppClient(
        async_get_clientsession(hass), entry.data[CONF_CLIENT_ID], entry.data[CONF_CLIENT_SECRET]
    )
    try:
        location = await client.async_locate()
    except GardenaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except GardenaError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = GardenaCoordinator(hass, entry, client, location)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_options_changed))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GardenaConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_changed(hass: HomeAssistant, entry: GardenaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
