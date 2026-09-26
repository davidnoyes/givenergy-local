"""Sensors combining several registers must not raise or emit a wrong value when one is missing.

Ported from upstream cdpuk/givenergy-local #148, adapted to this fork's formulas.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.givenergy_local.givenergy_modbus.model.inverter import Model
from custom_components.givenergy_local.sensor import (
    ConsumptionTodaySensor,
    ConsumptionTotalSensor,
    PVEnergyTodaySensor,
    PVPowerSensor,
)


def _sensor(cls, **inverter):
    sensor = cls.__new__(cls)
    sensor.coordinator = SimpleNamespace(data=SimpleNamespace(inverter=SimpleNamespace(**inverter)))
    return sensor


_TODAY = {
    "model": Model.HYBRID,
    "e_inverter_out_day": 10.0,
    "e_inverter_in_day": 2.0,
    "e_grid_in_day": 5.0,
    "e_grid_out_day": 1.0,
    "e_pv1_day": 3.0,
    "e_pv2_day": 4.0,
}
_TOTAL = {
    "model": Model.HYBRID,
    "e_inverter_out_total": 100.0,
    "e_inverter_in_total": 20.0,
    "e_grid_in_total": 50.0,
    "e_grid_out_total": 10.0,
    "e_pv_total": 70.0,
}


def test_pv_sensors_sum_both_strings():
    assert _sensor(PVEnergyTodaySensor, e_pv1_day=3.0, e_pv2_day=4.0).native_value == 7.0
    assert _sensor(PVPowerSensor, p_pv1=300, p_pv2=400).native_value == 700


@pytest.mark.parametrize("missing", ["e_pv1_day", "e_pv2_day"])
def test_pv_energy_is_none_when_a_string_is_missing(missing):
    values = {"e_pv1_day": 3.0, "e_pv2_day": 4.0, missing: None}
    assert _sensor(PVEnergyTodaySensor, **values).native_value is None


@pytest.mark.parametrize("missing", ["p_pv1", "p_pv2"])
def test_pv_power_is_none_when_a_string_is_missing(missing):
    values = {"p_pv1": 300, "p_pv2": 400, missing: None}
    assert _sensor(PVPowerSensor, **values).native_value is None


def test_consumption_today_hybrid_and_ac():
    assert _sensor(ConsumptionTodaySensor, **_TODAY).native_value == 12.0
    assert _sensor(ConsumptionTodaySensor, **{**_TODAY, "model": Model.AC}).native_value == 19.0


@pytest.mark.parametrize(
    "missing",
    ["e_inverter_out_day", "e_inverter_in_day", "e_grid_in_day", "e_grid_out_day"],
)
def test_consumption_today_is_none_when_a_component_is_missing(missing):
    assert _sensor(ConsumptionTodaySensor, **{**_TODAY, missing: None}).native_value is None


def test_consumption_today_ac_needs_pv_strings():
    values = {**_TODAY, "model": Model.AC, "e_pv2_day": None}
    assert _sensor(ConsumptionTodaySensor, **values).native_value is None


def test_consumption_today_hybrid_ignores_missing_pv_strings():
    values = {**_TODAY, "e_pv1_day": None}
    assert _sensor(ConsumptionTodaySensor, **values).native_value == 12.0


def test_consumption_total_hybrid_and_ac():
    assert _sensor(ConsumptionTotalSensor, **_TOTAL).native_value == 120.0
    assert _sensor(ConsumptionTotalSensor, **{**_TOTAL, "model": Model.AC}).native_value == 190.0


@pytest.mark.parametrize(
    "missing",
    ["e_inverter_out_total", "e_inverter_in_total", "e_grid_in_total", "e_grid_out_total"],
)
def test_consumption_total_is_none_when_a_component_is_missing(missing):
    assert _sensor(ConsumptionTotalSensor, **{**_TOTAL, missing: None}).native_value is None


def test_consumption_total_ac_needs_pv_total():
    values = {**_TOTAL, "model": Model.AC, "e_pv_total": None}
    assert _sensor(ConsumptionTotalSensor, **values).native_value is None
