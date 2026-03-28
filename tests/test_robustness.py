"""Robustness tests for edge cases and async behavior."""

from __future__ import annotations

from datetime import UTC, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.givenergy_local import config_flow
from custom_components.givenergy_local.coordinator import (
    _COMMAND_RETRIES,
    _COMMAND_TIMEOUT,
    FailureCategory,
    GivEnergyUpdateCoordinator,
    RecoveryState,
    RecoveryStateInfo,
)
from custom_components.givenergy_local.givenergy_modbus.client.client import Client
from custom_components.givenergy_local.givenergy_modbus.exceptions import (
    CommunicationError,
)
from custom_components.givenergy_local.givenergy_modbus.model.plant import Plant
from custom_components.givenergy_local.givenergy_modbus.model.register_cache import (
    RegisterCache,
)
from custom_components.givenergy_local.services import (
    _async_service_call,
    _resolve_coordinator,
)
from custom_components.givenergy_local.sensor import BatteryCapacitySensor
from custom_components.givenergy_local.sensor import RecoveryStateSensor
from custom_components.givenergy_local.time import InverterTimeslotSensor


async def test_time_entity_setter_awaits_service_call():
    """Ensure async time writes await the configured setter coroutine."""
    set_fn = AsyncMock()
    sensor = InverterTimeslotSensor.__new__(InverterTimeslotSensor)
    sensor.coordinator = object()
    sensor.entity_description = SimpleNamespace(set_fn=set_fn)

    await InverterTimeslotSensor.async_set_value(sensor, time(1, 30))

    set_fn.assert_awaited_once_with(sensor.coordinator, time(1, 30))


async def test_coordinator_execute_awaits_client_execute():
    """Ensure execute waits for command completion before refreshing."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.client = SimpleNamespace(execute=AsyncMock())
    coordinator.require_full_refresh = False
    coordinator.async_request_refresh = AsyncMock()
    coordinator.recovery = RecoveryStateInfo(state=RecoveryState.HEALTHY)

    await GivEnergyUpdateCoordinator.execute(coordinator, [])

    coordinator.client.execute.assert_awaited_once_with(
        [], _COMMAND_TIMEOUT, _COMMAND_RETRIES
    )
    coordinator.async_request_refresh.assert_awaited_once()
    assert coordinator.require_full_refresh is True


async def test_coordinator_execute_blocks_commands_when_not_healthy():
    """Ensure write commands are blocked outside the healthy state."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.client = SimpleNamespace(execute=AsyncMock())
    coordinator.require_full_refresh = False
    coordinator.async_request_refresh = AsyncMock()
    coordinator.recovery = RecoveryStateInfo(state=RecoveryState.RECOVERING)

    with pytest.raises(HomeAssistantError, match="recovering"):
        await GivEnergyUpdateCoordinator.execute(coordinator, [])

    coordinator.client.execute.assert_not_called()
    coordinator.async_request_refresh.assert_not_called()


async def test_read_inverter_serial_closes_client_on_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """Ensure validation path always closes the client even when detect fails."""
    created = []

    class DummyClient:
        """Dummy client for config-flow validation tests."""

        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.closed = False
            self.plant = SimpleNamespace(
                inverter=SimpleNamespace(serial_number="SN123")
            )
            created.append(self)

        async def connect(self):
            return None

        async def detect_plant(self):
            raise RuntimeError("probe failed")

        async def close(self):
            self.closed = True

    monkeypatch.setattr(config_flow, "Client", DummyClient)

    with pytest.raises(RuntimeError, match="probe failed"):
        await config_flow.read_inverter_serial({"host": "127.0.0.1"})

    assert created and created[0].closed is True


def test_plant_instances_do_not_share_mutable_state():
    """Ensure each Plant gets independent cache/list instances."""
    plant_a = Plant()
    plant_b = Plant()

    plant_a.additional_holding_registers.append(300)
    plant_a.register_caches[0x99] = RegisterCache()

    assert plant_b.additional_holding_registers == []
    assert 0x99 not in plant_b.register_caches


def test_client_instances_do_not_share_expected_responses():
    """Ensure response futures are instance-scoped, not class-scoped."""
    client_a = Client("127.0.0.1", 8899)
    client_b = Client("127.0.0.2", 8899)
    future = AsyncMock()
    client_a.expected_responses[123] = future

    assert client_b.expected_responses == {}


def test_battery_capacity_sensor_returns_none_when_register_missing():
    """Ensure missing battery register values don't raise in entity calculations."""
    battery_data = SimpleNamespace(
        model_dump=lambda: {"cap_remaining": None},
        v_cells_sum=51.2,
    )
    sensor = BatteryCapacitySensor.__new__(BatteryCapacitySensor)
    sensor.battery_id = 0
    sensor.coordinator = SimpleNamespace(
        data=SimpleNamespace(
            batteries=[battery_data],
            inverter=SimpleNamespace(),
        )
    )
    sensor.entity_description = SimpleNamespace(ge_modbus_key="cap_remaining")

    assert sensor.native_value is None


def test_resolve_coordinator_rejects_ambiguous_device_mapping():
    """Ensure service calls fail fast when a device maps to multiple entries."""
    coordinator_a = object()
    coordinator_b = object()
    entry_a = SimpleNamespace(runtime_data=SimpleNamespace(coordinator=coordinator_a))
    entry_b = SimpleNamespace(runtime_data=SimpleNamespace(coordinator=coordinator_b))
    config_entries = SimpleNamespace(
        async_get_entry=lambda entry_id: {
            "entry_a": entry_a,
            "entry_b": entry_b,
        }.get(entry_id)
    )
    hass = SimpleNamespace(config_entries=config_entries)
    device_entry = SimpleNamespace(config_entries={"entry_a", "entry_b"})
    registry = SimpleNamespace(async_get=lambda _: device_entry)

    with (
        patch(
            "custom_components.givenergy_local.services.dr.async_get",
            return_value=registry,
        ),
        pytest.raises(HomeAssistantError, match="multiple"),
    ):
        _resolve_coordinator(hass, "device_1")


def test_resolve_coordinator_uses_entry_runtime_data():
    """Ensure service resolution reads the coordinator from config-entry runtime data."""
    coordinator = object()
    entry = SimpleNamespace(runtime_data=SimpleNamespace(coordinator=coordinator))
    config_entries = SimpleNamespace(async_get_entry=lambda entry_id: entry)
    hass = SimpleNamespace(config_entries=config_entries)
    device_entry = SimpleNamespace(config_entries={"entry_a"})
    registry = SimpleNamespace(async_get=lambda _: device_entry)

    with patch(
        "custom_components.givenergy_local.services.dr.async_get",
        return_value=registry,
    ):
        assert _resolve_coordinator(hass, "device_1") is coordinator


async def test_service_call_executes_with_resolved_coordinator():
    """Ensure service command dispatch uses the resolved coordinator."""
    coordinator = SimpleNamespace(execute=AsyncMock())
    commands = [object()]

    with patch(
        "custom_components.givenergy_local.services._resolve_coordinator",
        return_value=coordinator,
    ):
        await _async_service_call(SimpleNamespace(), "device_1", commands)

    coordinator.execute.assert_awaited_once_with(commands)


def test_battery_sensor_returns_none_when_battery_disappears():
    """Ensure battery entities stop serving stale values when the battery disappears."""
    battery_data = SimpleNamespace(
        serial_number="BAT01",
        model_dump=lambda: {"cap_remaining": 10},
        v_cells_sum=51.2,
    )
    sensor = BatteryCapacitySensor.__new__(BatteryCapacitySensor)
    sensor.battery_id = 0
    sensor.coordinator = SimpleNamespace(
        last_update_success=True,
        data=SimpleNamespace(
            batteries=[battery_data],
            inverter=SimpleNamespace(serial_number="INV01"),
        ),
    )
    sensor.entity_description = SimpleNamespace(ge_modbus_key="cap_remaining")

    assert sensor.native_value == 0.512
    sensor.coordinator.data.batteries = []
    assert sensor.available is False
    assert sensor.native_value is None


def test_accept_trusted_plant_deep_copies_candidate_state():
    """Ensure trusted state is decoupled from the mutable client candidate plant."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.client = SimpleNamespace()
    coordinator.require_full_refresh = True
    coordinator.last_full_refresh = datetime.min
    coordinator.recovery = RecoveryStateInfo(state=RecoveryState.RECOVERING)
    coordinator.last_trusted_plant = None

    candidate = Plant()
    candidate.additional_holding_registers.append(300)

    trusted = GivEnergyUpdateCoordinator._accept_trusted_plant(coordinator, candidate)
    candidate.additional_holding_registers.append(301)

    assert trusted.additional_holding_registers == [300]
    assert coordinator.last_trusted_plant.additional_holding_registers == [300]
    assert coordinator.client.plant.additional_holding_registers == [300]
    assert coordinator.recovery.state == RecoveryState.HEALTHY
    assert coordinator.recovery.consecutive_failures == 0
    assert coordinator.recovery.last_failure_category is None
    assert coordinator.recovery.failure_category_counts == {}
    assert coordinator.recovery.last_trusted_update is not None


def test_restore_client_to_trusted_snapshot_when_recent():
    """Ensure invalid candidate state is reset to the last trusted snapshot."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    trusted = Plant()
    trusted.additional_holding_registers.append(300)
    coordinator.last_trusted_plant = trusted
    coordinator.client = SimpleNamespace(plant=Plant())
    coordinator.client.plant.additional_holding_registers.append(999)
    coordinator.recovery = RecoveryStateInfo(
        state=RecoveryState.RECOVERING,
        consecutive_failures=1,
        last_failure_category=FailureCategory.VALIDATION,
        last_trusted_update=datetime.now(UTC),
    )

    GivEnergyUpdateCoordinator._restore_client_to_trusted_snapshot(coordinator)

    assert coordinator.client.plant.additional_holding_registers == [300]
    assert coordinator.client.plant is not coordinator.last_trusted_plant


def test_restore_client_to_trusted_snapshot_skips_expired_snapshot():
    """Ensure expired trusted snapshots are not reused."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    trusted = Plant()
    trusted.additional_holding_registers.append(300)
    coordinator.last_trusted_plant = trusted
    coordinator.client = SimpleNamespace(plant=Plant())
    coordinator.client.plant.additional_holding_registers.append(999)
    coordinator.recovery = RecoveryStateInfo(
        state=RecoveryState.RECOVERING,
        consecutive_failures=3,
        last_failure_category=FailureCategory.TIMEOUT,
        last_trusted_update=datetime.now(UTC).replace(year=2025),
    )

    GivEnergyUpdateCoordinator._restore_client_to_trusted_snapshot(coordinator)

    assert coordinator.client.plant.additional_holding_registers == [999]


def test_recovery_state_sensor_exposes_coordinator_state():
    """Ensure the diagnostic sensor reflects coordinator recovery state."""
    sensor = RecoveryStateSensor.__new__(RecoveryStateSensor)
    sensor.coordinator = SimpleNamespace(recovery_state=RecoveryState.RECOVERING)

    assert sensor.native_value == RecoveryState.RECOVERING


def test_recovery_state_sensor_exposes_diagnostic_attributes():
    """Ensure the diagnostic sensor includes useful recovery metadata."""
    sensor = RecoveryStateSensor.__new__(RecoveryStateSensor)
    sensor.coordinator = SimpleNamespace(
        recovery_state=RecoveryState.RECOVERING,
        recovery_status_summary="Recovering from a temporary inverter or network problem.",
        recovery_recommended_action="Wait for the integration to recover. If it stays in recovery, check the inverter host and network path.",
        last_failure_category=FailureCategory.TIMEOUT,
        consecutive_failures=2,
        failure_category_counts={"timeout": 2, "validation": 1},
        trusted_snapshot_age_seconds=7,
        trusted_snapshot_available=True,
    )

    assert sensor.extra_state_attributes == {
        "status_summary": "Recovering from a temporary inverter or network problem.",
        "recommended_action": "Wait for the integration to recover. If it stays in recovery, check the inverter host and network path.",
        "last_failure_category": "timeout",
        "consecutive_failures": 2,
        "failure_category_counts": {"timeout": 2, "validation": 1},
        "trusted_snapshot_age_seconds": 7,
        "trusted_snapshot_available": True,
    }


def test_record_failure_tracks_category_counts():
    """Ensure repeated failures are tracked by category."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.recovery = RecoveryStateInfo(state=RecoveryState.HEALTHY)

    GivEnergyUpdateCoordinator._record_failure(coordinator, FailureCategory.TIMEOUT)
    GivEnergyUpdateCoordinator._record_failure(coordinator, FailureCategory.TIMEOUT)
    GivEnergyUpdateCoordinator._record_failure(coordinator, FailureCategory.VALIDATION)

    assert coordinator.recovery.consecutive_failures == 3
    assert coordinator.recovery.last_failure_category == FailureCategory.VALIDATION
    assert coordinator.failure_category_counts == {"timeout": 2, "validation": 1}


async def test_refresh_escalates_after_max_unhealthy_duration():
    """Ensure prolonged loss of trusted data escalates even before exhausting retries."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.host = "192.0.2.10"
    coordinator.hass = object()
    coordinator.config_entry = SimpleNamespace(entry_id="entry-duration")
    coordinator.require_full_refresh = False
    coordinator.last_full_refresh = datetime.now(UTC)
    coordinator.last_trusted_plant = Plant()
    coordinator.client = SimpleNamespace(
        refresh_plant=AsyncMock(side_effect=CommunicationError("link down")),
        close=AsyncMock(),
        connect=AsyncMock(),
    )
    coordinator.recovery = RecoveryStateInfo(
        state=RecoveryState.RECOVERING,
        consecutive_failures=0,
        last_failure_category=None,
        last_trusted_update=datetime.now(UTC).replace(year=2025),
    )

    with (
        patch(
            "custom_components.givenergy_local.coordinator.asyncio.sleep",
            AsyncMock(),
        ),
        patch(
            "custom_components.givenergy_local.coordinator.persistent_notification.async_create"
        ),
        pytest.raises(UpdateFailed),
    ):
        await GivEnergyUpdateCoordinator._async_refresh_with_recovery(coordinator)

    assert coordinator.recovery.state == RecoveryState.UNAVAILABLE
    assert coordinator.failure_category_counts == {"communication": 1}


def test_transition_to_unavailable_creates_single_notification():
    """Ensure hard failure creates a user-visible troubleshooting notification."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.hass = object()
    coordinator.config_entry = SimpleNamespace(entry_id="entry-a")
    coordinator.host = "192.0.2.10"
    coordinator.recovery = RecoveryStateInfo(
        state=RecoveryState.RECOVERING,
        consecutive_failures=3,
        last_failure_category=FailureCategory.TIMEOUT,
    )

    with patch(
        "custom_components.givenergy_local.coordinator.persistent_notification.async_create"
    ) as mock_create:
        GivEnergyUpdateCoordinator._transition_recovery_state(
            coordinator, RecoveryState.UNAVAILABLE
        )

    mock_create.assert_called_once()
    assert "Configured host: 192.0.2.10" in mock_create.call_args.args[1]
    assert "Recommended action:" in mock_create.call_args.args[1]
    assert (
        mock_create.call_args.kwargs["notification_id"]
        == "givenergy_local_recovery_state_entry-a"
    )


def test_transition_to_healthy_dismisses_notification():
    """Ensure recovery dismisses the troubleshooting notification."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.hass = object()
    coordinator.config_entry = SimpleNamespace(entry_id="entry-a")
    coordinator.host = "192.0.2.10"
    coordinator.recovery = RecoveryStateInfo(
        state=RecoveryState.UNAVAILABLE,
        consecutive_failures=0,
        last_failure_category=None,
    )

    with patch(
        "custom_components.givenergy_local.coordinator.persistent_notification.async_dismiss"
    ) as mock_dismiss:
        GivEnergyUpdateCoordinator._transition_recovery_state(
            coordinator, RecoveryState.HEALTHY
        )

    mock_dismiss.assert_called_once()
    assert mock_dismiss.call_args.args[1] == "givenergy_local_recovery_state_entry-a"


def test_transition_to_same_unavailable_state_still_updates_notification():
    """Ensure cold-start failures surface a notification even without a state transition."""
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.hass = object()
    coordinator.config_entry = SimpleNamespace(entry_id="entry-b")
    coordinator.host = "192.0.2.20"
    coordinator.recovery = RecoveryStateInfo(
        state=RecoveryState.UNAVAILABLE,
        consecutive_failures=1,
        last_failure_category=FailureCategory.COMMUNICATION,
    )

    with patch(
        "custom_components.givenergy_local.coordinator.persistent_notification.async_create"
    ) as mock_create:
        GivEnergyUpdateCoordinator._transition_recovery_state(
            coordinator, RecoveryState.UNAVAILABLE
        )

    mock_create.assert_called_once()
    assert (
        mock_create.call_args.kwargs["notification_id"]
        == "givenergy_local_recovery_state_entry-b"
    )
