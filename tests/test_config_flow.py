"""Exercise pairing/options/reauth through the real HA flow manager."""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.toolforest.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def start_pairing(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "My HA", "environment": "dev"}
    )


async def test_pairing_exposure_creates_entry(hass, device_api, mock_setup_entry):
    result = await start_pairing(hass)
    assert result["step_id"] == "pairing"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "exposure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "read_entities": ["light.allowed"],
            "turn_on_entities": ["light.allowed"],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == "dev:new-instance"
    assert entry.data == {"name": "My HA", "environment": "dev", **device_api.token}
    assert entry.options["read_entities"] == ["light.allowed"]
    assert [call[0] for call in device_api.calls] == [
        "/dev/device/code",
        "/dev/device/token",
    ]
    mock_setup_entry.assert_awaited_once()


async def test_pending_poll_is_throttled(hass, device_api, freezer):
    device_api.responses["/dev/device/token"] = (
        400,
        {"error": "authorization_pending"},
    )
    result = await start_pairing(hass)
    for _ in range(2):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["errors"] == {"base": "authorization_pending"}
    assert len(device_api.calls) == 2
    freezer.tick(6)
    device_api.responses.pop("/dev/device/token")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "exposure"
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()


@pytest.mark.parametrize("error", ["access_denied", "expired_token"])
async def test_pairing_denied_or_expired(hass, device_api, error):
    device_api.responses["/dev/device/token"] = (400, {"error": error})
    result = await start_pairing(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not any("revoke-self" in call[0] for call in device_api.calls)


async def test_pairing_local_expiry_does_not_poll(hass, device_api, freezer):
    result = await start_pairing(hass)
    freezer.tick(601)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "pairing_expired"
    assert len(device_api.calls) == 1


@pytest.mark.parametrize("error", [TimeoutError, aiohttp.ClientConnectionError])
async def test_pairing_network_failure_can_retry(hass, device_api, error):
    result = await start_pairing(hass)
    with patch(
        "custom_components.toolforest.config_flow.ConfigFlow._post", side_effect=error
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pairing"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_exposure_validation_and_abort_revocation(hass, device_api):
    result = await start_pairing(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "read_entities": [],
            "turn_on_entities": ["light.allowed"],
        },
    )
    assert result["errors"] == {"base": "invalid_exposure"}
    assert not any("revoke-self" in call[0] for call in device_api.calls)
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert device_api.calls[-1] == ("/dev/device/revoke-self", {}, "Bearer new-token")
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_abort_before_token_does_not_revoke(hass, device_api):
    result = await start_pairing(hass)
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert len(device_api.calls) == 1


async def test_abort_while_token_request_is_in_flight_revokes_returned_token(
    hass, device_api
):
    result = await start_pairing(hass)
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow_token(*args):
        started.set()
        await finish.wait()
        return device_api.token

    with patch(
        "custom_components.toolforest.config_flow.ConfigFlow._post",
        side_effect=slow_token,
    ):
        task = hass.async_create_task(
            hass.config_entries.flow.async_configure(result["flow_id"], {})
        )
        await started.wait()
        hass.config_entries.flow.async_abort(result["flow_id"])
        finish.set()
        result = await task
        assert result["type"] is FlowResultType.ABORT
    assert device_api.calls[-1] == ("/dev/device/revoke-self", {}, "Bearer new-token")
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_initial_connection_error_keeps_entered_settings(hass, device_api):
    device_api.responses["/dev/device/code"] = (503, {})
    result = await start_pairing(hass)
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}
    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults == {"name": "My HA", "environment": "dev"}


async def test_abandoned_pairing_failed_revoke_warns_without_secret(
    hass, device_api, caplog
):
    device_api.responses["/dev/device/revoke-self"] = (503, {})
    result = await start_pairing(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert "could not confirm device revocation" in caplog.text
    assert "new-token" not in caplog.text


async def test_duplicate_entry_abort_revokes_unused_token(
    hass, device_api, config_entry
):
    hass.config_entries.async_update_entry(config_entry, unique_id="dev:new-instance")
    result = await start_pairing(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["reason"] == "already_configured"
    assert device_api.calls[-1] == ("/dev/device/revoke-self", {}, "Bearer new-token")
    assert config_entry.data["access_token"] == "old-token"


async def test_reauth_error_preserves_environment_name_and_updates_identity(
    hass,
    device_api,
    config_entry,
    mock_setup_entry,
):
    device_api.responses["/dev/device/code"] = [(503, {}), (200, device_api.code)]
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}
    assert not result["data_schema"].schema
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pairing"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert config_entry.unique_id == "dev:new-instance"
    assert config_entry.data == {
        "name": "My HA",
        "environment": "dev",
        **device_api.token,
    }
    assert config_entry.title == "My HA"
    assert config_entry.options["read_entities"] == ["light.allowed"]
    assert all(call[0].startswith("/dev/") for call in device_api.calls)
    assert not any("revoke-self" in call[0] for call in device_api.calls)
