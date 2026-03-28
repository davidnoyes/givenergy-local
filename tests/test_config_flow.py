"""Test givenergy_local config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_local.const import DOMAIN

from .const import MOCK_CONFIG

_MOCK_SERIAL_NO = "AB123456"


# This fixture bypasses the actual setup of the integration
# since we only want to test the config flow. We test the
# actual functionality of the integration in other test modules.
@pytest.fixture(autouse=True)
def bypass_setup_fixture():
    """Prevent setup."""
    with patch(
        "custom_components.givenergy_local.async_setup_entry",
        return_value=True,
    ):
        yield


@pytest.fixture(name="bypass_validation")
def skip_validation():
    """Bypasses the validation step that attempts to read the serial number from the inverter."""
    with patch(
        "custom_components.givenergy_local.config_flow.read_inverter_serial",
        return_value=_MOCK_SERIAL_NO,
    ):
        yield


@pytest.fixture(name="error_on_validation")
def error_get_data_fixture():
    """Simulate an error trying to read the serial number."""
    with patch(
        "custom_components.givenergy_local.config_flow.read_inverter_serial",
        side_effect=Exception,
    ):
        yield


async def test_successful_config_flow(hass, bypass_validation):
    """Test a successful config flow."""
    # Initialize a config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Check that the config flow shows the user form as the first step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # If a user were to enter `test_inverter_host` for host,
    # it would result in this function call
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )

    # Check that the config flow is complete and a new entry is created with
    # the input data
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Solar Inverter (S/N {_MOCK_SERIAL_NO})"
    assert result["data"] == MOCK_CONFIG
    assert result["result"]
    assert result["result"].unique_id == _MOCK_SERIAL_NO


async def test_failed_config_flow(hass, error_on_validation):
    """Test a failed config flow due to credential validation failure."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_invalid_host_config_flow_error(hass):
    """Test a host-format validation failure."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"host": "http://bad-host"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_host"}


async def test_successful_reconfigure_flow(hass, bypass_validation):
    """Test updating the configured inverter host through reconfigure."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Solar Inverter (S/N {_MOCK_SERIAL_NO})",
        data=MOCK_CONFIG,
        entry_id="reconfigure-entry",
        unique_id=_MOCK_SERIAL_NO,
        version=2,
    )
    entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_schedule_reload") as mock_reload:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        updated_config = {"host": "updated_inverter_host"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=updated_config
        )

        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == updated_config
    assert entry.title == f"Solar Inverter (S/N {_MOCK_SERIAL_NO})"
    assert entry.unique_id == _MOCK_SERIAL_NO
    mock_reload.assert_called_once_with(entry.entry_id)


async def test_failed_reconfigure_flow(hass, error_on_validation):
    """Test a failed reconfigure validation attempt."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Solar Inverter",
        data=MOCK_CONFIG,
        entry_id="reconfigure-entry-error",
        unique_id=_MOCK_SERIAL_NO,
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"host": "broken-host"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_inverter_aborts_user_flow(hass, bypass_validation):
    """Test duplicate setup is rejected by inverter serial."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Solar Inverter (S/N {_MOCK_SERIAL_NO})",
        data=MOCK_CONFIG,
        entry_id="existing-entry",
        unique_id=_MOCK_SERIAL_NO,
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"host": "another-host"}
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_rejects_different_inverter(hass):
    """Test reconfigure refuses to point an entry at a different inverter serial."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Solar Inverter (S/N {_MOCK_SERIAL_NO})",
        data=MOCK_CONFIG,
        entry_id="reconfigure-entry-mismatch",
        unique_id=_MOCK_SERIAL_NO,
        version=2,
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.givenergy_local.config_flow.read_inverter_serial",
        return_value="CD987654",
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"host": "different-inverter-host"}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "different_inverter"


async def test_reconfigure_sets_unique_id_for_legacy_entry(hass, bypass_validation):
    """Test reconfigure populates unique_id for existing entries created before unique IDs."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Solar Inverter (S/N {_MOCK_SERIAL_NO})",
        data=MOCK_CONFIG,
        entry_id="legacy-entry",
        unique_id=None,
        version=2,
    )
    entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_schedule_reload"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"host": "legacy-updated-host"}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == _MOCK_SERIAL_NO
