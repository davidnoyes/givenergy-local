"""Tests for the inverter clock and clock drift sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from custom_components.givenergy_local.coordinator import GivEnergyUpdateCoordinator
from custom_components.givenergy_local.givenergy_modbus.client.client import (
    _carries_clock,
)
from custom_components.givenergy_local.givenergy_modbus.pdu import (
    ReadHoldingRegistersResponse,
    ReadInputRegistersResponse,
)
from custom_components.givenergy_local.sensor import (
    InverterClockDriftSensor,
    InverterClockSensor,
)
from homeassistant.util import dt as dt_util

LONDON = ZoneInfo("Europe/London")
READ_AT = datetime(2026, 9, 26, 16, 15, 13, tzinfo=UTC)


def _inverter_wall_clock(hour: int, minute: int, second: int) -> datetime:
    """Return a zone-less time, as the inverter's clock registers decode to."""
    return datetime(2026, 9, 26, hour, minute, second)  # noqa: DTZ001


@pytest.fixture(autouse=True)
def _london_time_zone():
    """Pin Home Assistant's default time zone for the duration of each test."""
    previous = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(LONDON)
    yield
    dt_util.set_default_time_zone(previous)


def _sensor(cls, system_time, clock_read_at=None):
    sensor = cls.__new__(cls)
    sensor.coordinator = SimpleNamespace(
        data=SimpleNamespace(inverter=SimpleNamespace(system_time=system_time)),
        clock_read_at=clock_read_at,
    )
    return sensor


def test_clock_is_interpreted_in_home_assistant_time_zone():
    """The inverter's zone-less wall clock is local time, not UTC."""
    sensor = _sensor(InverterClockSensor, _inverter_wall_clock(17, 15, 13))

    assert sensor.native_value == datetime(2026, 9, 26, 17, 15, 13, tzinfo=LONDON)
    assert sensor.native_value.astimezone(UTC).hour == 16  # BST is UTC+1


def test_clock_is_none_without_a_reading():
    assert _sensor(InverterClockSensor, None).native_value is None


def test_drift_compares_with_when_the_clock_was_read_not_now():
    """Drift is measured against when the clock registers were read."""
    in_step = _sensor(
        InverterClockDriftSensor, _inverter_wall_clock(17, 15, 13), READ_AT
    )
    ahead = _sensor(InverterClockDriftSensor, _inverter_wall_clock(17, 17, 43), READ_AT)
    behind = _sensor(
        InverterClockDriftSensor, _inverter_wall_clock(17, 10, 13), READ_AT
    )

    assert in_step.native_value == 0
    assert ahead.native_value == 150
    assert behind.native_value == -300


def test_drift_is_none_before_the_clock_is_first_read():
    sensor = _sensor(InverterClockDriftSensor, _inverter_wall_clock(17, 15, 13))

    assert sensor.native_value is None


def test_drift_is_none_without_a_clock_reading():
    assert _sensor(InverterClockDriftSensor, None, READ_AT).native_value is None


def _holding_read(base_register=0, register_count=60, slave_address=0x32, error=False):
    return ReadHoldingRegistersResponse(
        base_register=base_register,
        register_count=register_count,
        slave_address=slave_address,
        error=error,
    )


@pytest.mark.parametrize("slave_address", [0x32, 0x11, 0x00])
def test_reads_of_the_clock_registers_are_recognised(slave_address):
    """Our own reads (0x32) and relayed cloud/app reads (0x11, 0x00) all carry the clock."""
    assert _carries_clock(_holding_read(slave_address=slave_address))
    assert _carries_clock(_holding_read(base_register=35, register_count=6))


@pytest.mark.parametrize(
    "message",
    [
        _holding_read(base_register=60),
        _holding_read(base_register=0, register_count=40),
        _holding_read(base_register=36, register_count=5),
        _holding_read(error=True),
        _holding_read(slave_address=0x33),
        ReadInputRegistersResponse(base_register=0, register_count=60),
    ],
)
def test_other_messages_do_not_carry_the_clock(message):
    assert not _carries_clock(message)


def _coordinator(clock_received_at=None):
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.clock_read_at = None
    coordinator._published_clock = None
    coordinator.client = SimpleNamespace(clock_received_at=clock_received_at)
    return coordinator


def _plant(system_time):
    return SimpleNamespace(inverter=SimpleNamespace(system_time=system_time))


def test_relayed_cloud_read_between_full_refreshes_is_not_false_drift():
    """Regression: a cloud read 2 min after a full refresh used to show +120 s of drift."""
    coordinator = _coordinator(clock_received_at=READ_AT)
    coordinator._note_clock_reading(_plant(_inverter_wall_clock(17, 15, 13)), READ_AT)

    cloud_read = READ_AT + timedelta(minutes=2)
    coordinator.client.clock_received_at = cloud_read
    coordinator._note_clock_reading(
        _plant(_inverter_wall_clock(17, 17, 13)), cloud_read + timedelta(seconds=7)
    )

    sensor = _sensor(
        InverterClockDriftSensor,
        _inverter_wall_clock(17, 17, 13),
        coordinator.clock_read_at,
    )
    assert coordinator.clock_read_at == cloud_read
    assert sensor.native_value == 0


def test_unchanged_clock_keeps_its_original_read_time():
    """Partial refreshes publish the same clock value; its read time must not move."""
    coordinator = _coordinator(clock_received_at=READ_AT)
    clock = _inverter_wall_clock(17, 15, 13)
    coordinator._note_clock_reading(_plant(clock), READ_AT)
    coordinator._note_clock_reading(_plant(clock), READ_AT + timedelta(seconds=10))

    assert coordinator.clock_read_at == READ_AT


def test_read_time_falls_back_to_now_without_an_arrival_time():
    coordinator = _coordinator()
    coordinator._note_clock_reading(_plant(_inverter_wall_clock(17, 15, 13)), READ_AT)

    assert coordinator.clock_read_at == READ_AT


def test_missing_clock_is_not_noted():
    coordinator = _coordinator(clock_received_at=READ_AT)
    coordinator._note_clock_reading(_plant(None), READ_AT)

    assert coordinator.clock_read_at is None
