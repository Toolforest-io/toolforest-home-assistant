"""Home Assistant toolkit: outbound-only bridge installed inside HA."""

from __future__ import annotations

import asyncio
import contextlib

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN, STATUS_SIGNAL
from .executor import Executor, validate_exposure
from .transport import BridgeTransport


async def async_setup_entry(hass, entry):
    validate_exposure(entry.options)
    executor = Executor(hass, entry)
    runtime = {"status": "connecting", "executor": executor}

    def status(value):
        executor.active = value == "connected"
        runtime["status"] = value
        async_dispatcher_send(hass, f"{STATUS_SIGNAL}_{entry.entry_id}")

    transport = BridgeTransport(
        async_get_clientsession(hass),
        entry.data["access_token"],
        entry.data["environment"],
        executor.execute,
        status,
        lambda: entry.async_start_reauth(hass),
    )
    task = hass.async_create_background_task(
        transport.run(), f"toolforest-{entry.entry_id}"
    )
    runtime.update(transport=transport, task=task)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    async def stop(_event=None):
        executor.active = False
        await transport.close()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    runtime["stop"] = stop
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    entry.async_on_unload(entry.add_update_listener(_reload))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    except Exception:  # setup failure must stop the owned connection/task
        await stop()
        del hass.data[DOMAIN][entry.entry_id]
        raise
    return True


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    runtime = hass.data[DOMAIN][entry.entry_id]
    # Stop execution before taking down the UI platform.
    await runtime["stop"]()
    if not await hass.config_entries.async_unload_platforms(entry, ["sensor"]):
        return False
    del hass.data[DOMAIN][entry.entry_id]
    return True


async def async_remove_entry(hass, entry):
    import aiohttp

    from .const import ENVIRONMENTS

    # Removal revokes the remote device; unload/reload preserves pairing.
    with contextlib.suppress(aiohttp.ClientError, TimeoutError):
        async with async_get_clientsession(hass).post(
            f"{ENVIRONMENTS[entry.data['environment']][0]}/device/revoke-self",
            headers={"Authorization": f"Bearer {entry.data['access_token']}"},
            json={},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            await response.read()
