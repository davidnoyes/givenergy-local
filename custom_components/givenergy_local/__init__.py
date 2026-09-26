"""The GivEnergy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .compat import has_entry_runtime_data
from .const import DOMAIN
from .coordinator import GivEnergyUpdateCoordinator
from .runtime import (
    GivEnergyRuntimeData,
    clear_runtime_data,
    get_coordinator,
    set_runtime_data,
)
from .services import async_setup_services, async_unload_services

_RUNTIME_KEY = f"{DOMAIN}_runtime"
_SERVICES_REGISTERED_KEY = "services_registered"

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TIME,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GivEnergy from a config entry."""

    coordinator = GivEnergyUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    set_runtime_data(entry, GivEnergyRuntimeData(coordinator=coordinator))
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    runtime_data = hass.data.setdefault(_RUNTIME_KEY, {})
    if not runtime_data.get(_SERVICES_REGISTERED_KEY):
        async_setup_services(hass)
        runtime_data[_SERVICES_REGISTERED_KEY] = True

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok: bool = await hass.config_entries.async_unload_platforms(
        entry, _PLATFORMS
    )
    if unload_ok:
        coordinator = get_coordinator(entry)
        await coordinator.async_shutdown()
        clear_runtime_data(entry)

        remaining_entries = [
            config_entry
            for config_entry in hass.config_entries.async_entries(DOMAIN)
            if config_entry.entry_id != entry.entry_id
            and has_entry_runtime_data(config_entry)
        ]
        if not remaining_entries:
            runtime_data = hass.data.get(_RUNTIME_KEY, {})
            if runtime_data.get(_SERVICES_REGISTERED_KEY):
                async_unload_services(hass)
                runtime_data[_SERVICES_REGISTERED_KEY] = False

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry.

    Goes through hass.config_entries.async_reload rather than calling
    async_unload_entry/async_setup_entry directly: HA only runs the config entry's
    on-unload callbacks (including the update listener registered in setup) from
    ConfigEntry.async_unload, so calling them directly leaks the old listener and
    coordinator on every reload. Ported from upstream cdpuk/givenergy-local #151.
    """
    await hass.config_entries.async_reload(entry.entry_id)
