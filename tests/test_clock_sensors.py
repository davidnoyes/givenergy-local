"""Tests for the inverter clock and clock drift sensors."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
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


def _sensor(cls, system_time, last_full_refresh=datetime.min):
    sensor = cls.__new__(cls)
    sensor.coordinator = SimpleNamespace(
        data=SimpleNamespace(inverter=SimpleNamespace(system_time=system_time)),
        last_full_refresh=last_full_refresh,
    )
    return sensor


def test_clock_is_interpreted_in_home_assistant_time_zone():
    """The inverter's zone-less wall clock is local time, not UTC."""
    sensor = _sensor(InverterClockSensor, _inverter_wall_clock(17, 15, 13))

    assert sensor.native_value == datetime(2026, 9, 26, 17, 15, 13, tzinfo=LONDON)
    assert sensor.native_value.astimezone(UTC).hour == 16  # BST is UTC+1


def test_clock_is_none_without_a_reading():
    assert _sensor(InverterClockSensor, None).native_value is None


def test_drift_compares_with_the_full_refresh_not_now():
    """Drift is measured against when the registers were read."""
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


def test_drift_is_none_before_first_full_refresh():
    """last_full_refresh starts as naive datetime.min until a full refresh completes."""
    sensor = _sensor(InverterClockDriftSensor, _inverter_wall_clock(17, 15, 13))

    assert sensor.native_value is None


def test_drift_is_none_without_a_clock_reading():
    assert _sensor(InverterClockDriftSensor, None, READ_AT).native_value is None
