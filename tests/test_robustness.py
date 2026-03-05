"""Robustness tests for edge cases and async behavior."""

from __future__ import annotations

from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.givenergy_local import config_flow
from custom_components.givenergy_local.const import DOMAIN
from custom_components.givenergy_local.coordinator import (
    _COMMAND_RETRIES,
    _COMMAND_TIMEOUT,
    GivEnergyUpdateCoordinator,
)
from custom_components.givenergy_local.givenergy_modbus.client.client import Client
from custom_components.givenergy_local.givenergy_modbus.model.plant import Plant
from custom_components.givenergy_local.givenergy_modbus.model.register_cache import RegisterCache
from custom_components.givenergy_local.services import (
    _async_service_call,
    _resolve_coordinator,
)
from custom_components.givenergy_local.sensor import BatteryCapacitySensor
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

    await GivEnergyUpdateCoordinator.execute(coordinator, [])

    coordinator.client.execute.assert_awaited_once_with(
        [], _COMMAND_TIMEOUT, _COMMAND_RETRIES
    )
    coordinator.async_request_refresh.assert_awaited_once()
    assert coordinator.require_full_refresh is True


async def test_read_inverter_serial_closes_client_on_error(monkeypatch: pytest.MonkeyPatch):
    """Ensure validation path always closes the client even when detect fails."""
    created = []

    class DummyClient:
        """Dummy client for config-flow validation tests."""

        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.closed = False
            self.plant = SimpleNamespace(inverter=SimpleNamespace(serial_number="SN123"))
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
    hass = SimpleNamespace(data={DOMAIN: {"entry_a": coordinator_a, "entry_b": coordinator_b}})
    device_entry = SimpleNamespace(config_entries={"entry_a", "entry_b"})
    registry = SimpleNamespace(async_get=lambda _: device_entry)

    with patch(
        "custom_components.givenergy_local.services.dr.async_get",
        return_value=registry,
    ), pytest.raises(HomeAssistantError, match="multiple"):
        _resolve_coordinator(hass, "device_1")


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


def test_battery_sensor_uses_cached_data_when_battery_disappears():
    """Ensure entities don't crash if a battery temporarily disappears."""
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
    assert sensor.native_value == 0.512
