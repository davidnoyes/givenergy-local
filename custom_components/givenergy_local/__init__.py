"""The GivEnergy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import GivEnergyUpdateCoordinator
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
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
        domain_data = hass.data.setdefault(DOMAIN, {})
        coordinator = domain_data.pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_shutdown()

        if not domain_data:
            hass.data.pop(DOMAIN, None)
            runtime_data = hass.data.get(_RUNTIME_KEY, {})
            if runtime_data.get(_SERVICES_REGISTERED_KEY):
                async_unload_services(hass)
                runtime_data[_SERVICES_REGISTERED_KEY] = False

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
