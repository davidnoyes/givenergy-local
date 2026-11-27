"""Out-of-range time slot registers decode as 'undefined' instead of raising.

The GivEnergy app's force-charge left discharge slot 2 holding [62, 54]
("00:62"). Converter.timeslot raised ValueError, the refresh was rejected,
and the integration went unavailable while it kept reconnecting.
"""

from datetime import time

import pytest

from custom_components.givenergy_local.givenergy_modbus.model import TimeSlot
from custom_components.givenergy_local.givenergy_modbus.model.register import (
    Converter,
)


@pytest.mark.parametrize(
    "registers",
    [
        (62, 54),  # seen on a live inverter, 2026-11-27
        (0, 60),  # the long-known '--:--' sentinel
        (60, 2359),
        (2460, 100),  # hour out of range
        (1300, 1675),  # minute out of range in the end time
    ],
)
def test_invalid_timeslot_registers_decode_as_none(registers):
    assert Converter.timeslot(*registers) is None


def test_valid_timeslot_still_decodes():
    assert Converter.timeslot(1300, 1600) == TimeSlot(time(13, 0), time(16, 0))


def test_missing_registers_decode_as_none():
    assert Converter.timeslot(None, 1600) is None
