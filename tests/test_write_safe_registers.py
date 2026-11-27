"""Every register the CommandBuilder writes must be on the write-safe list.

The battery pause select and pause-slot time entities were exposed with
commands for HR318-320, but those registers were missing from
WRITE_SAFE_REGISTERS, so every write raised "HR(318) is not safe to write to".
"""

from datetime import time

import pytest

from custom_components.givenergy_local.givenergy_modbus.client.commands import (
    CommandBuilder,
)
from custom_components.givenergy_local.givenergy_modbus.model.inverter import (
    BatteryPauseMode,
)
from custom_components.givenergy_local.givenergy_modbus.pdu.write_registers import (
    WRITE_SAFE_REGISTERS,
    WriteHoldingRegisterRequest,
)


@pytest.mark.parametrize(
    "requests",
    [
        CommandBuilder.set_battery_pause_mode(BatteryPauseMode.PAUSE_DISCHARGE),
        CommandBuilder.set_pause_slot_start(time(0, 0)),
        CommandBuilder.set_pause_slot_end(time(23, 59)),
    ],
    ids=["pause_mode", "pause_slot_start", "pause_slot_end"],
)
def test_pause_commands_target_write_safe_registers(requests):
    for request in requests:
        assert isinstance(request, WriteHoldingRegisterRequest)
        assert request.register in WRITE_SAFE_REGISTERS
        request.ensure_valid_state()
