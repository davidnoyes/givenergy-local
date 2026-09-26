"""Duplicate register writes in one batch must not cancel each other (upstream #152)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.givenergy_local.coordinator import (
    _COMMAND_RETRIES,
    _COMMAND_TIMEOUT,
    GivEnergyUpdateCoordinator,
    RecoveryState,
    RecoveryStateInfo,
    _dedupe_requests,
)
from custom_components.givenergy_local.givenergy_modbus.client.commands import (
    RegisterMap,
)
from custom_components.givenergy_local.givenergy_modbus.pdu.write_registers import (
    WriteHoldingRegisterRequest,
)


def test_repeat_writes_to_one_register_keep_the_last_value():
    first = WriteHoldingRegisterRequest(RegisterMap.ENABLE_CHARGE, 1)
    last = WriteHoldingRegisterRequest(RegisterMap.ENABLE_CHARGE, 0)

    assert _dedupe_requests([first, last]) == [last]


def test_writes_to_different_registers_are_all_kept():
    enable = WriteHoldingRegisterRequest(RegisterMap.ENABLE_CHARGE, 1)
    target = WriteHoldingRegisterRequest(RegisterMap.CHARGE_TARGET_SOC, 80)

    assert _dedupe_requests([enable, target]) == [enable, target]


async def test_coordinator_execute_sends_the_deduplicated_batch():
    coordinator = GivEnergyUpdateCoordinator.__new__(GivEnergyUpdateCoordinator)
    coordinator.client = SimpleNamespace(execute=AsyncMock())
    coordinator.require_full_refresh = False
    coordinator.async_request_refresh = AsyncMock()
    coordinator.recovery = RecoveryStateInfo(state=RecoveryState.HEALTHY)
    first = WriteHoldingRegisterRequest(RegisterMap.ENABLE_CHARGE, 1)
    target = WriteHoldingRegisterRequest(RegisterMap.CHARGE_TARGET_SOC, 80)
    last = WriteHoldingRegisterRequest(RegisterMap.ENABLE_CHARGE, 0)

    await GivEnergyUpdateCoordinator.execute(coordinator, [first, target, last])

    coordinator.client.execute.assert_awaited_once_with(
        [last, target], _COMMAND_TIMEOUT, _COMMAND_RETRIES
    )
