"""Runtime ownership helpers for GivEnergy config entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from .compat import clear_entry_runtime_data, get_entry_runtime_data, set_entry_runtime_data
from .coordinator import GivEnergyUpdateCoordinator


@dataclass
class GivEnergyRuntimeData:
    """Typed runtime state owned by a config entry."""

    coordinator: GivEnergyUpdateCoordinator


def set_runtime_data(
    entry: ConfigEntry, runtime_data: GivEnergyRuntimeData
) -> GivEnergyRuntimeData:
    """Attach typed runtime data to a config entry."""
    return cast(GivEnergyRuntimeData, set_entry_runtime_data(entry, runtime_data))


def get_runtime_data(entry: ConfigEntry) -> GivEnergyRuntimeData:
    """Return typed runtime data for a config entry."""
    runtime_data = get_entry_runtime_data(entry)
    if runtime_data is None:
        raise HomeAssistantError(
            f"Config entry '{entry.entry_id}' is missing runtime data"
        )
    return cast(GivEnergyRuntimeData, runtime_data)


def clear_runtime_data(entry: ConfigEntry) -> None:
    """Remove runtime data from a config entry."""
    clear_entry_runtime_data(entry)


def get_coordinator(entry: ConfigEntry) -> GivEnergyUpdateCoordinator:
    """Convenience accessor for the config entry coordinator."""
    return get_runtime_data(entry).coordinator
