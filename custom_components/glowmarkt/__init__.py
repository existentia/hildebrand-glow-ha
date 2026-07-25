"""The Glowmarkt (Bright) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GlowmarktClient
from .coordinator import GlowmarktCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type GlowmarktConfigEntry = ConfigEntry[GlowmarktCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: GlowmarktConfigEntry
) -> bool:
    """Set up Glowmarkt from a config entry."""
    client = GlowmarktClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    coordinator = GlowmarktCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: GlowmarktConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: GlowmarktConfigEntry
) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)
