"""Native HA entry/platform lifecycle with real loopback WSS/HTTP."""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components import toolforest
from custom_components.toolforest.const import DOMAIN
from custom_components.toolforest.executor import Denied

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def setup(hass, entry, device_api):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await asyncio.wait_for(device_api.connected.wait(), 2)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    await connected(runtime)
    return runtime


async def connected(runtime):
    # Server-side upgrade acceptance precedes the client's connected callback.
    async with asyncio.timeout(2):
        while not runtime["executor"].active:
            await asyncio.sleep(0.01)


def sensor(hass):
    return next(
        state
        for state in hass.states.async_all("sensor")
        if state.attributes.get("instance_id") == "old-instance"
    )


async def test_setup_sensor_options_reload_and_unload(hass, config_entry, device_api):
    runtime = await setup(hass, config_entry, device_api)
    assert config_entry.state is ConfigEntryState.LOADED
    assert runtime["executor"].active
    assert sensor(hass).state == "connected"
    assert sensor(hass).attributes["environment"] == "prod"
    assert "old-token" not in str(sensor(hass))
    runtime["transport"].status("reconnecting")
    await hass.async_block_till_done()
    assert sensor(hass).state == "reconnecting"
    assert not runtime["executor"].active
    runtime["transport"].status("connected")
    device_api.connected.clear()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "read_entities": [],
            "turn_on_entities": [],
            "turn_off_entities": ["light.allowed"],
        },
    )
    assert result["errors"] == {"base": "invalid_exposure"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "read_entities": ["switch.allowed"],
            "turn_on_entities": [],
            "turn_off_entities": [],
            "brightness_entities": [],
        },
    )
    await hass.async_block_till_done()
    await asyncio.wait_for(device_api.connected.wait(), 2)
    assert runtime["task"].done()
    assert not runtime["executor"].active
    replacement = hass.data[DOMAIN][config_entry.entry_id]
    assert replacement is not runtime
    assert replacement["executor"].entry.options["read_entities"] == ["switch.allowed"]
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert replacement["task"].done()
    assert not replacement["executor"].active
    assert config_entry.entry_id not in hass.data[DOMAIN]
    assert not any("revoke-self" in call[0] for call in device_api.calls)


async def test_shutdown_stops_owned_connection(hass, config_entry, device_api):
    runtime = await setup(hass, config_entry, device_api)
    await hass.async_stop(force=True)
    assert runtime["task"].done()
    assert not runtime["executor"].active
    assert runtime["transport"].stopped


async def test_disconnected_socket_reconnects_without_new_pairing(
    hass, config_entry, device_api, monkeypatch
):
    runtime = await setup(hass, config_entry, device_api)
    monkeypatch.setattr(
        "custom_components.toolforest.transport.random.uniform", lambda *_: 0
    )
    device_api.connected.clear()
    await device_api.sockets[-1].close()
    await asyncio.wait_for(device_api.connected.wait(), 3)
    await hass.async_block_till_done()
    await connected(runtime)
    assert len(device_api.sockets) == 2
    assert runtime["executor"].active and not runtime["task"].done()
    assert not device_api.calls


async def test_platform_setup_failure_cleans_runtime(hass, config_entry, device_api):
    with (
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=RuntimeError("platform failed"),
        ),
        pytest.raises(RuntimeError, match="platform failed"),
    ):
        await toolforest.async_setup_entry(hass, config_entry)
    assert config_entry.entry_id not in hass.data[DOMAIN]
    assert not any(
        task.get_name() == f"toolforest-{config_entry.entry_id}"
        for task in asyncio.all_tasks()
    )


async def test_invalid_options_never_start_transport(hass, config_entry, device_api):
    hass.config_entries.async_update_entry(
        config_entry, options={"read_entities": ["lock.front"]}
    )
    with pytest.raises(Denied):
        await toolforest.async_setup_entry(hass, config_entry)
    assert not device_api.sockets and DOMAIN not in hass.data


async def test_unload_stops_execution_before_platform_unload(
    hass, config_entry, device_api
):
    runtime = await setup(hass, config_entry, device_api)

    async def failed_unload(*args):
        assert not runtime["executor"].active
        assert runtime["task"].done()
        return False

    with patch.object(
        hass.config_entries, "async_unload_platforms", side_effect=failed_unload
    ):
        assert not await toolforest.async_unload_entry(hass, config_entry)
    assert config_entry.entry_id in hass.data[DOMAIN]
    assert await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.parametrize("kind", ["revoked_frame", "401_handshake"])
async def test_revocation_starts_native_reauth_flow(
    hass, config_entry, device_api, kind
):
    if kind == "401_handshake":
        device_api.handshake_status = 401
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        runtime = hass.data[DOMAIN][config_entry.entry_id]
    else:
        runtime = await setup(hass, config_entry, device_api)
        await device_api.sockets[-1].send_json({"v": 1, "type": "revoked"})
    await asyncio.wait_for(asyncio.shield(runtime["task"]), 2)
    await hass.async_block_till_done()
    assert not runtime["executor"].active
    assert runtime["status"] == "revoked"
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"
    assert flows[0]["context"]["entry_id"] == config_entry.entry_id


async def test_loaded_entry_reauth_reloads_once_with_new_identity(
    hass, config_entry, device_api
):
    runtime = await setup(hass, config_entry, device_api)
    await device_api.sockets[-1].send_json({"v": 1, "type": "revoked"})
    await asyncio.wait_for(asyncio.shield(runtime["task"]), 2)
    await hass.async_block_till_done()
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    assert result["step_id"] == "pairing"
    device_api.connected.clear()
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    await hass.async_block_till_done()
    await asyncio.wait_for(device_api.connected.wait(), 2)
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert config_entry.unique_id == "prod:new-instance"
    assert config_entry.data["environment"] == "prod"
    await connected(hass.data[DOMAIN][config_entry.entry_id])
    assert len(device_api.sockets) == 2
    assert hass.data[DOMAIN][config_entry.entry_id]["executor"].active
    assert config_entry.options["read_entities"] == ["light.allowed"]


@pytest.mark.parametrize("status", [200, 204, 401, 500])
async def test_entry_removal_attempts_revocation(
    hass, config_entry, device_api, caplog, status
):
    device_api.responses["/prod/device/revoke-self"] = (status, {})
    await hass.config_entries.async_remove(config_entry.entry_id)
    assert device_api.calls[-1] == ("/prod/device/revoke-self", {}, "Bearer old-token")
    assert not hass.config_entries.async_entries(DOMAIN)
    assert ("could not confirm device revocation" in caplog.text) == (status == 500)
    assert "old-token" not in caplog.text


@pytest.mark.parametrize("error", [TimeoutError, aiohttp.ClientConnectionError])
async def test_entry_removal_network_failure_is_safe(hass, config_entry, caplog, error):
    with patch(
        "custom_components.toolforest.device_auth.async_get_clientsession"
    ) as session:
        session.return_value.post.side_effect = error
        await hass.config_entries.async_remove(config_entry.entry_id)
    assert not hass.config_entries.async_entries(DOMAIN)
    assert "could not confirm device revocation" in caplog.text
    assert "old-token" not in caplog.text


@pytest.mark.parametrize("environment", ["dev", "test", "unknown", None, "missing"])
async def test_unsupported_pairing_never_connects_or_revokes_in_production(
    hass, config_entry, device_api, environment, caplog
):
    data = {**config_entry.data, "environment": environment}
    if environment == "missing":
        del data["environment"]
    hass.config_entries.async_update_entry(config_entry, data=data)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert DOMAIN not in hass.data
    assert not device_api.calls and not device_api.sockets
    assert config_entry.data["access_token"] == "old-token"
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not device_api.calls and not device_api.sockets
    assert "cannot revoke an unsupported pairing" in caplog.text
    assert "old-token" not in caplog.text
