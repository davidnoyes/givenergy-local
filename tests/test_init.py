"""Test givenergy_local setup process."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_local import async_setup_entry, async_unload_entry
from custom_components.givenergy_local.compat import (
    clear_entry_runtime_data,
    get_entry_runtime_data,
    has_entry_runtime_data,
    set_entry_runtime_data,
)
from custom_components.givenergy_local.const import DOMAIN

from .const import MOCK_CONFIG


async def test_setup_entry_exception(hass: HomeAssistant, error_on_get_data):
    """Test ConfigEntryNotReady when API raises an exception during entry setup."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        entry_id="test",
        version=2,
    )
    config_entry.add_to_hass(hass)

    # In this case we are testing the condition where async_setup_entry raises
    # ConfigEntryNotReady using the `error_on_get_data` fixture which simulates
    # an error.
    await hass.config_entries.async_setup(config_entry.entry_id)

    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_services_registered_once_and_unloaded_after_last_entry(
    hass: HomeAssistant,
):
    """Ensure shared services are loaded once and removed on last unload."""
    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        entry_id="entry_a",
        version=2,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={**MOCK_CONFIG, "host": "test_inverter_host_2"},
        entry_id="entry_b",
        version=2,
    )

    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    coordinator_a = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(),
        async_shutdown=AsyncMock(),
    )
    coordinator_b = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(),
        async_shutdown=AsyncMock(),
    )

    with (
        patch(
            "custom_components.givenergy_local.GivEnergyUpdateCoordinator",
            side_effect=[coordinator_a, coordinator_b],
        ),
        patch(
            "custom_components.givenergy_local.async_setup_services",
        ) as mock_setup_services,
        patch(
            "custom_components.givenergy_local.async_unload_services",
        ) as mock_unload_services,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
        patch.object(
            hass.config_entries,
            "async_unload_platforms",
            AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_entry(hass, entry_a) is True
        assert await async_setup_entry(hass, entry_b) is True
        assert entry_a.runtime_data.coordinator is coordinator_a
        assert entry_b.runtime_data.coordinator is coordinator_b
        assert mock_setup_services.call_count == 1

        assert await async_unload_entry(hass, entry_a) is True
        assert mock_unload_services.call_count == 0
        coordinator_a.async_shutdown.assert_awaited_once()
        assert entry_a.runtime_data is None

        assert await async_unload_entry(hass, entry_b) is True
        assert mock_unload_services.call_count == 1
        coordinator_b.async_shutdown.assert_awaited_once()
        assert entry_b.runtime_data is None


def test_compat_runtime_data_helpers_round_trip():
    """Ensure config-entry runtime compatibility helpers behave consistently."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        entry_id="compat",
        version=2,
    )
    runtime_data = SimpleNamespace(coordinator=object())

    assert has_entry_runtime_data(entry) is False
    assert get_entry_runtime_data(entry) is None

    set_entry_runtime_data(entry, runtime_data)

    assert has_entry_runtime_data(entry) is True
    assert get_entry_runtime_data(entry) is runtime_data

    clear_entry_runtime_data(entry)

    assert has_entry_runtime_data(entry) is False
    assert get_entry_runtime_data(entry) is None
