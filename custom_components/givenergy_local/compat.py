"""Home Assistant compatibility helpers.

This is the one place where version-sensitive Home Assistant shims should live.
Right now it abstracts config-entry runtime data ownership so the rest of the
integration does not care whether Home Assistant exposes native runtime storage
or whether we need a local fallback attribute.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

_RUNTIME_DATA_ATTR = "runtime_data"
_RUNTIME_DATA_FALLBACK_ATTR = "_givenergy_local_runtime_data"


def set_entry_runtime_data(entry: ConfigEntry, value: Any) -> Any:
    """Store runtime data on a config entry in a compatibility-safe way."""
    setattr(entry, _RUNTIME_DATA_ATTR, value)
    setattr(entry, _RUNTIME_DATA_FALLBACK_ATTR, value)
    return value


def get_entry_runtime_data(entry: ConfigEntry) -> Any | None:
    """Return runtime data for a config entry if present."""
    runtime_data = getattr(entry, _RUNTIME_DATA_ATTR, None)
    if runtime_data is not None:
        return runtime_data
    return getattr(entry, _RUNTIME_DATA_FALLBACK_ATTR, None)


def clear_entry_runtime_data(entry: ConfigEntry) -> None:
    """Clear runtime data for a config entry."""
    setattr(entry, _RUNTIME_DATA_ATTR, None)
    setattr(entry, _RUNTIME_DATA_FALLBACK_ATTR, None)


def has_entry_runtime_data(entry: ConfigEntry) -> bool:
    """Return True if the config entry currently has runtime data."""
    return get_entry_runtime_data(entry) is not None
