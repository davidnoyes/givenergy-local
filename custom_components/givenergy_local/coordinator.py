"""The GivEnergy update coordinator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from logging import getLogger

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_HOST
from .givenergy_modbus.client.client import Client
from .givenergy_modbus.exceptions import CommunicationError, ConversionError
from .givenergy_modbus.model.plant import Plant
from .givenergy_modbus.model.register_cache import RegisterCache
from .givenergy_modbus.pdu.transparent import TransparentRequest

_LOGGER = getLogger(__name__)
_FULL_REFRESH_INTERVAL = timedelta(minutes=5)
_REFRESH_ATTEMPTS = 3
_REFRESH_DELAY_BETWEEN_ATTEMPTS = 2.0
_COMMAND_TIMEOUT = 3.0
_COMMAND_RETRIES = 3
_TRUSTED_SNAPSHOT_MAX_AGE = timedelta(seconds=30)
_MAX_UNHEALTHY_DURATION = timedelta(seconds=30)
_RECOVERY_NOTIFICATION_ID_PREFIX = "givenergy_local_recovery_state"
_RECOVERY_NOTIFICATION_TITLE = "GivEnergy inverter needs attention"


class RecoveryState(StrEnum):
    """Coordinator-owned recovery state."""

    HEALTHY = "healthy"
    RECOVERING = "recovering"
    UNAVAILABLE = "unavailable"


class FailureCategory(StrEnum):
    """Failure categories that feed the recovery policy."""

    TIMEOUT = "timeout"
    COMMUNICATION = "communication"
    VALIDATION = "validation"
    UNEXPECTED = "unexpected"


@dataclass
class RecoveryStateInfo:
    """Track the current recovery state and trusted snapshot metadata."""

    state: RecoveryState = RecoveryState.UNAVAILABLE
    consecutive_failures: int = 0
    last_failure_category: FailureCategory | None = None
    last_trusted_update: datetime | None = None
    failure_category_counts: dict[FailureCategory, int] = field(default_factory=dict)


@dataclass
class QualityCheck:
    """Defines likely values for a given property."""

    attr_name: str
    min: float | None
    max: float | None
    min_inclusive: bool = True
    max_inclusive: bool = True

    @property
    def range_description(self) -> str:
        """Provide a string representation of the accepted range."""
        return "%s%s, %s%s" % (  # pylint: disable=consider-using-f-string
            "[" if self.min_inclusive else "(",
            self.min,
            self.max,
            "]" if self.max_inclusive else ")",
        )


QC = QualityCheck
_INVERTER_QUALITY_CHECKS = [
    QC("temp_inverter_heatsink", -10, 100),
    QC("temp_charger", -10, 100),
    QC("temp_battery", -10, 100),
    QC("e_inverter_out_total", 0, 1e6, min_inclusive=False),  # 1GWh
    QC("e_grid_in_total", 0, 1e6, min_inclusive=False),  # 1GWh
    QC("e_grid_out_total", 0, 1e6, min_inclusive=False),  # 1GWh
    QC("battery_percent", 0, 100),
    QC("p_eps_backup", -15e3, 15e3),  # +/- 15kW
    QC("p_grid_out", -1e6, 15e3),  # 15kW export, 1MW import
    QC("p_battery", -15e3, 15e3),  # +/- 15kW
]


class GivEnergyUpdateCoordinator(DataUpdateCoordinator[Plant]):
    """Update coordinator that fetches data from a GivEnergy inverter."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Inverter",
            update_interval=timedelta(seconds=10),
        )

        self.entry_id = config_entry.entry_id
        self.host = str(config_entry.data.get(CONF_HOST))
        self.client = Client(self.host, 8899)
        self.require_full_refresh = True
        self.last_full_refresh = datetime.min
        self.last_trusted_plant: Plant | None = None
        self.recovery = RecoveryStateInfo()

    async def async_shutdown(self) -> None:
        """Terminate the modbus connection and shut down the coordinator."""
        _LOGGER.debug("Shutting down")
        await self.client.close()
        await super().async_shutdown()

    async def _async_update_data(self) -> Plant:
        """Fetch data from the inverter."""
        if not self.client.connected:
            try:
                await self.client.connect()
                await self.client.detect_plant()
            except Exception as err:
                await self.client.close()
                self._record_failure(FailureCategory.COMMUNICATION)
                self._transition_recovery_state(RecoveryState.UNAVAILABLE)
                raise UpdateFailed(
                    "Failed to establish initial inverter connection"
                ) from err
            return self._accept_trusted_plant(self.client.plant)

        return await self._async_refresh_with_recovery()

    async def _async_refresh_with_recovery(self) -> Plant:
        """Refresh inverter data using coordinator-owned recovery policy."""
        if self.last_full_refresh < (datetime.now(UTC) - _FULL_REFRESH_INTERVAL):
            self.require_full_refresh = True

        # Within the inverter comms, there are further retries to ensure >some< data is
        # returned. This layer decides whether the mutated client state is trustworthy
        # enough to publish into Home Assistant.
        attempt = 0
        while attempt < _REFRESH_ATTEMPTS:
            attempt += 1
            try:
                async with asyncio.timeout(10):
                    _LOGGER.info(
                        "Fetching data from %s (attempt=%d/%d, full_refresh=%s, recovery=%s)",
                        self.host,
                        attempt,
                        _REFRESH_ATTEMPTS,
                        self.require_full_refresh,
                        self.recovery.state,
                    )
                    plant = await self.client.refresh_plant(
                        full_refresh=self.require_full_refresh, retries=2
                    )
            except ValueError as err:
                _LOGGER.warning("Plant refresh failed due to bad data: %s", err)
                self._record_failure(FailureCategory.VALIDATION)
                self._restore_client_to_trusted_snapshot()
                if self._unhealthy_duration_exceeded():
                    break
                await asyncio.sleep(_REFRESH_DELAY_BETWEEN_ATTEMPTS)
                continue
            except CommunicationError as err:
                _LOGGER.debug("Closing connection due to communication error: %s", err)
                self._record_failure(FailureCategory.COMMUNICATION)
                await self.client.close()
                if self._unhealthy_duration_exceeded():
                    break
                await asyncio.sleep(_REFRESH_DELAY_BETWEEN_ATTEMPTS)
                await self.client.connect()
                continue
            except TimeoutError:
                _LOGGER.warning("Timeout error, restarting connection")
                self._record_failure(FailureCategory.TIMEOUT)
                await self.client.close()
                if self._unhealthy_duration_exceeded():
                    break
                await asyncio.sleep(_REFRESH_DELAY_BETWEEN_ATTEMPTS)
                await self.client.connect()
                continue
            except Exception as err:
                _LOGGER.error("Closing connection due to expected error: %s", err)
                self._record_failure(FailureCategory.UNEXPECTED)
                self._transition_recovery_state(RecoveryState.UNAVAILABLE)
                await self.client.close()
                raise UpdateFailed("Connection closed due to expected error") from err

            if not self._is_data_valid(plant):
                self._record_failure(FailureCategory.VALIDATION)
                self._restore_client_to_trusted_snapshot()
                if self._unhealthy_duration_exceeded():
                    break
                await asyncio.sleep(_REFRESH_DELAY_BETWEEN_ATTEMPTS)
                continue

            return self._accept_trusted_plant(plant)

        self._transition_recovery_state(RecoveryState.UNAVAILABLE)
        raise UpdateFailed(
            f"Failed to obtain valid data after {_REFRESH_ATTEMPTS} attempts"
        )

    def _accept_trusted_plant(self, plant: Plant) -> Plant:
        """Accept a fully validated plant as the trusted coordinator snapshot."""
        now = datetime.now(UTC)
        trusted_plant = self._clone_plant(plant)
        self.last_trusted_plant = trusted_plant
        self.client.plant = self._clone_plant(trusted_plant)
        self.recovery.consecutive_failures = 0
        self.recovery.last_failure_category = None
        self.recovery.failure_category_counts = {}
        self.recovery.last_trusted_update = now
        self._transition_recovery_state(RecoveryState.HEALTHY)
        if self.require_full_refresh:
            self.require_full_refresh = False
            self.last_full_refresh = now
        return trusted_plant

    def _record_failure(self, category: FailureCategory) -> None:
        """Record a failed refresh attempt and update recovery state."""
        self.recovery.consecutive_failures += 1
        self.recovery.last_failure_category = category
        self.recovery.failure_category_counts[category] = (
            self.recovery.failure_category_counts.get(category, 0) + 1
        )
        if self.recovery.state == RecoveryState.HEALTHY:
            self._transition_recovery_state(RecoveryState.RECOVERING)

    def _unhealthy_duration_exceeded(self) -> bool:
        """Return True if the coordinator has gone too long without trusted data."""
        if self.recovery.last_trusted_update is None:
            return False
        return (
            datetime.now(UTC) - self.recovery.last_trusted_update
        ) > _MAX_UNHEALTHY_DURATION

    def _transition_recovery_state(self, new_state: RecoveryState) -> None:
        """Update recovery state and emit transition logs once."""
        old_state = self.recovery.state
        if new_state == old_state:
            if new_state == RecoveryState.UNAVAILABLE:
                self._show_recovery_notification()
            return

        self.recovery.state = new_state
        if new_state == RecoveryState.HEALTHY:
            _LOGGER.info("Coordinator recovered and returned to healthy state")
            self._dismiss_recovery_notification()
        elif new_state == RecoveryState.RECOVERING:
            _LOGGER.info("Coordinator entered recovery mode")
        else:
            _LOGGER.warning(
                "Coordinator marked unavailable after %d failed refresh attempts",
                self.recovery.consecutive_failures,
            )
            self._show_recovery_notification()

    def _show_recovery_notification(self) -> None:
        """Create or update a single troubleshooting notification for the user."""
        if not hasattr(self, "hass"):
            return
        persistent_notification.async_create(
            self.hass,
            self.recovery_status_detail,
            title=_RECOVERY_NOTIFICATION_TITLE,
            notification_id=self._recovery_notification_id,
        )

    def _dismiss_recovery_notification(self) -> None:
        """Dismiss the troubleshooting notification after recovery."""
        if not hasattr(self, "hass"):
            return
        persistent_notification.async_dismiss(self.hass, self._recovery_notification_id)

    def _restore_client_to_trusted_snapshot(self) -> None:
        """Reset mutable client state from the last trusted snapshot when safe."""
        if not self._trusted_snapshot_is_usable():
            return
        assert self.last_trusted_plant is not None
        self.client.plant = self._clone_plant(self.last_trusted_plant)

    def _trusted_snapshot_is_usable(self) -> bool:
        """Return True if the trusted snapshot is still fresh enough to reuse."""
        if self.last_trusted_plant is None or self.recovery.last_trusted_update is None:
            return False
        return (
            datetime.now(UTC) - self.recovery.last_trusted_update
        ) <= _TRUSTED_SNAPSHOT_MAX_AGE

    @staticmethod
    def _clone_plant(plant: Plant) -> Plant:
        """Clone Plant explicitly to avoid deepcopy issues in RegisterCache."""
        return Plant(
            register_caches={
                slave: RegisterCache(dict(cache.items()))
                for slave, cache in plant.register_caches.items()
            },
            additional_holding_registers=list(plant.additional_holding_registers),
            inverter_serial_number=plant.inverter_serial_number,
            data_adapter_serial_number=plant.data_adapter_serial_number,
            number_batteries=plant.number_batteries,
        )

    @property
    def recovery_state(self) -> RecoveryState:
        """Expose machine-readable recovery state."""
        return self.recovery.state

    @property
    def last_failure_category(self) -> FailureCategory | None:
        """Expose the most recent failure category."""
        return self.recovery.last_failure_category

    @property
    def consecutive_failures(self) -> int:
        """Expose the current consecutive failure count."""
        return self.recovery.consecutive_failures

    @property
    def trusted_snapshot_age_seconds(self) -> int | None:
        """Expose the age of the last trusted snapshot."""
        if self.recovery.last_trusted_update is None:
            return None
        return int(
            (datetime.now(UTC) - self.recovery.last_trusted_update).total_seconds()
        )

    @property
    def trusted_snapshot_available(self) -> bool:
        """Return True if a trusted snapshot is still usable."""
        return self._trusted_snapshot_is_usable()

    @property
    def failure_category_counts(self) -> dict[str, int]:
        """Expose failure category counts for diagnostics."""
        return {
            category.value: count
            for category, count in self.recovery.failure_category_counts.items()
        }

    @property
    def _recovery_notification_id(self) -> str:
        """Return the per-entry persistent notification ID."""
        entry_id = getattr(self, "entry_id", None)
        if entry_id is None:
            config_entry = getattr(self, "config_entry", None)
            entry_id = config_entry.entry_id if config_entry is not None else "unknown"
        return f"{_RECOVERY_NOTIFICATION_ID_PREFIX}_{entry_id}"

    @property
    def recovery_status_summary(self) -> str:
        """Provide a short, user-readable summary of the current recovery state."""
        if self.recovery.state == RecoveryState.HEALTHY:
            return "Connected normally."

        if self.recovery.state == RecoveryState.RECOVERING:
            return "Recovering from a temporary inverter or network problem."

        return "Unable to refresh data from the inverter."

    @property
    def recovery_recommended_action(self) -> str:
        """Provide the next user action that best matches the recovery state."""
        if self.recovery.state == RecoveryState.HEALTHY:
            return "No action required."

        if self.recovery.state == RecoveryState.RECOVERING:
            return "Wait for the integration to recover. If it stays in recovery, check the inverter host and network path."

        if self.last_failure_category == FailureCategory.VALIDATION:
            return "Check for conflicting Modbus access or bad inverter data, then reload the integration."

        if self.last_failure_category in {
            FailureCategory.TIMEOUT,
            FailureCategory.COMMUNICATION,
        }:
            return "Check that Home Assistant can reach the configured inverter host, then use Reconfigure to update the host if needed."

        return "Check the inverter connection, then reload the integration."

    @property
    def recovery_status_detail(self) -> str:
        """Provide a fuller troubleshooting message for notifications and diagnostics."""
        last_failure = (
            self.last_failure_category.value if self.last_failure_category else "none"
        )
        return (
            f"{self.recovery_status_summary}\n\n"
            f"Last failure category: {last_failure}\n"
            f"Consecutive failures: {self.consecutive_failures}\n"
            f"Configured host: {self.host}\n\n"
            f"Recommended action: {self.recovery_recommended_action}"
        )

    @staticmethod
    def _is_data_valid(plant: Plant) -> bool:
        """Perform checks to ensure returned data actually makes sense.

        The connection sometimes returns what it claims is valid data, but many of the values
        are zero (or other highly improbable values). This is particularly painful when values
        are used in the energy dashboard, as the dashboard double counts everything up to the
        point in the day when the figures go back to normal.
        """
        try:
            inverter_data = plant.inverter
            _ = plant.batteries
        except ConversionError as err:
            _LOGGER.warning(
                "Failed to convert %s from %s: %s",
                err.key,
                err.source_registers,
                err.message,
            )
            return False
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Unexpected register validation error: %s", err)
            return False

        for check in _INVERTER_QUALITY_CHECKS:
            value = inverter_data.model_dump().get(check.attr_name)
            if value is None:
                _LOGGER.warning("Data discarded: %s is missing", check.attr_name)
                return False
            too_low = False
            too_high = False

            if (min_val := check.min) is not None:
                too_low = not (
                    value > min_val or (check.min_inclusive and value >= min_val)
                )
            if (max_val := check.max) is not None:
                too_high = not (
                    value < max_val or (check.max_inclusive and value <= max_val)
                )

            if too_low or too_high:
                _LOGGER.warning(
                    "Data discarded: %s value of %s is out of range %s",
                    check.attr_name,
                    value,
                    check.range_description,
                )
                return False

        return True

    async def execute(self, requests: list[TransparentRequest]) -> None:
        """Execute a set of requests and force an update to read any new values."""
        if self.recovery.state is not RecoveryState.HEALTHY:
            raise HomeAssistantError(
                f"Cannot execute inverter commands while coordinator is {self.recovery.state}"
            )
        await self.client.execute(requests, _COMMAND_TIMEOUT, _COMMAND_RETRIES)
        self.require_full_refresh = True
        await self.async_request_refresh()
