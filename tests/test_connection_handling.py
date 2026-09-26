"""Bounded close/connect, reconnect backoff and execute timeout (ported from upstream #151)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.givenergy_local import coordinator as coordinator_module
from custom_components.givenergy_local.coordinator import (
    _RECONNECT_BACKOFF_INITIAL,
    GivEnergyUpdateCoordinator,
    RecoveryState,
    RecoveryStateInfo,
)
from custom_components.givenergy_local.givenergy_modbus.exceptions import (
    CommunicationError,
)


def _coordinator(client) -> GivEnergyUpdateCoordinator:
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.host = "192.0.2.10"
    coordinator.entry_id = "entry"
    coordinator.client = client
    coordinator.require_full_refresh = False
    coordinator.last_full_refresh = datetime.min
    coordinator.last_trusted_plant = None
    coordinator.recovery = RecoveryStateInfo(state=RecoveryState.HEALTHY)
    coordinator._reconnect_backoff = _RECONNECT_BACKOFF_INITIAL
    coordinator._next_reconnect_attempt = datetime.min.replace(tzinfo=UTC)
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    return coordinator


def _client(**overrides) -> SimpleNamespace:
    values = {
        "connected": False,
        "close": AsyncMock(),
        "connect": AsyncMock(),
        "detect_plant": AsyncMock(),
        "execute": AsyncMock(),
        "plant": SimpleNamespace(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_clean_close_keeps_the_client():
    client = _client()
    coordinator = _coordinator(client)

    assert await coordinator._close_client() is True
    assert coordinator.client is client


async def test_failed_close_abandons_and_replaces_the_client():
    task = MagicMock(done=MagicMock(return_value=False))
    client = _client(
        close=AsyncMock(side_effect=OSError("wait_closed failed")),
        network_consumer_task=task,
    )
    coordinator = _coordinator(client)

    with patch.object(coordinator_module, "Client") as client_cls:
        assert await coordinator._close_client() is False

    task.cancel.assert_called_once()
    client_cls.assert_called_once_with("192.0.2.10", 8899)
    assert coordinator.client is client_cls.return_value


async def test_shutdown_unschedules_even_when_close_fails():
    coordinator = _coordinator(_client(close=AsyncMock(side_effect=OSError("boom"))))

    with (
        patch.object(
            coordinator_module.DataUpdateCoordinator, "async_shutdown", AsyncMock()
        ) as parent_shutdown,
        patch.object(coordinator_module, "Client"),
    ):
        await coordinator.async_shutdown()  # must not raise

    parent_shutdown.assert_awaited_once()


async def test_failed_first_connection_backs_off_before_retrying():
    client = _client(connect=AsyncMock(side_effect=CommunicationError("refused")))
    coordinator = _coordinator(client)

    with pytest.raises(UpdateFailed, match="initial inverter connection"):
        await coordinator._async_update_data()
    assert coordinator._next_reconnect_attempt > datetime.now(UTC)
    assert coordinator._reconnect_backoff == _RECONNECT_BACKOFF_INITIAL * 2

    client.connect.reset_mock()
    with pytest.raises(UpdateFailed, match="Waiting before next"):
        await coordinator._async_update_data()
    client.connect.assert_not_called()


async def test_successful_connection_counts_as_a_full_refresh():
    """Detection re-reads the clock, so last_full_refresh must move with it."""
    plant = SimpleNamespace()
    coordinator = _coordinator(_client(plant=plant))
    coordinator._next_reconnect_attempt = datetime.now(UTC) - timedelta(seconds=1)

    with patch.object(
        GivEnergyUpdateCoordinator, "_clone_plant", staticmethod(lambda p: p)
    ):
        await coordinator._async_update_data()

    assert coordinator.last_full_refresh.tzinfo is UTC
    assert datetime.now(UTC) - coordinator.last_full_refresh < timedelta(seconds=5)
    assert coordinator._reconnect_backoff == _RECONNECT_BACKOFF_INITIAL


async def test_failed_reconnect_inside_a_refresh_ends_it_with_backoff():
    client = _client(
        connected=True,
        refresh_plant=AsyncMock(side_effect=TimeoutError()),
        connect=AsyncMock(side_effect=CommunicationError("gone")),
    )
    coordinator = _coordinator(client)
    coordinator.last_full_refresh = datetime.now(UTC)
    coordinator.recovery.last_trusted_update = datetime.now(UTC)

    with (
        patch.object(coordinator_module.asyncio, "sleep", AsyncMock()),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()

    assert client.refresh_plant.await_count == 1
    assert coordinator._next_reconnect_attempt > datetime.now(UTC)
    assert coordinator.recovery.state is RecoveryState.UNAVAILABLE


async def test_execute_timeout_is_reported_as_a_home_assistant_error():
    async def never_finishes(*_args):
        await asyncio.sleep(3600)

    coordinator = _coordinator(_client(execute=never_finishes))

    with (
        patch.object(coordinator_module, "_EXECUTE_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError, match="Failed to send command"),
    ):
        await GivEnergyUpdateCoordinator.execute(coordinator, [])
    coordinator.async_request_refresh.assert_not_called()
