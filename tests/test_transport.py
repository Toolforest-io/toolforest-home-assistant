"""Real async socket contract tests; no Home Assistant or cloud needed here."""

import asyncio
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web

from custom_components.toolforest import transport


@pytest_asyncio.fixture
async def server(unused_tcp_port, socket_enabled):
    app = web.Application()
    sockets = []
    headers = []
    ready = asyncio.Event()

    async def handler(request):
        headers.append(dict(request.headers))
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        sockets.append(ws)
        ready.set()
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                app["responses"].append(msg.json())
        return ws

    app["responses"] = []
    app.router.add_get("/bridge", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    yield (
        f"ws://127.0.0.1:{unused_tcp_port}/bridge",
        sockets,
        headers,
        ready,
        app["responses"],
    )
    await runner.cleanup()


@pytest.mark.asyncio
async def test_protocol_headers_response_and_clean_stop(server, monkeypatch):
    endpoint, sockets, headers, ready, responses = server
    monkeypatch.setitem(transport.ENVIRONMENTS, "dev", ("unused", endpoint))
    status = Mock()
    execute = AsyncMock(return_value={"state": "on"})
    async with aiohttp.ClientSession() as session:
        bridge = transport.BridgeTransport(
            session, "secret", "dev", execute, status, Mock()
        )
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(ready.wait(), 2)
        await sockets[0].send_json(
            {"v": 1, "type": "request", "correlation_id": "test-1"}
        )
        async with asyncio.timeout(2):
            while not responses:
                await asyncio.sleep(0.01)
        assert responses[0]["correlation_id"] == "test-1" and responses[0]["body"] == {
            "state": "on"
        }
        assert headers[0]["Authorization"] == "Bearer secret"
        assert headers[0]["X-Bridge-Capability"] == "home_assistant"
        await bridge.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.done() and bridge.request_task is None


@pytest.mark.asyncio
async def test_revocation_cancels_inflight_and_never_reconnects(server, monkeypatch):
    endpoint, sockets, headers, ready, responses = server
    monkeypatch.setitem(transport.ENVIRONMENTS, "dev", ("unused", endpoint))
    running = asyncio.Event()
    cancelled = asyncio.Event()

    async def execute(message):
        running.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    reauth = Mock()
    status = Mock()
    async with aiohttp.ClientSession() as session:
        bridge = transport.BridgeTransport(
            session, "secret", "dev", execute, status, reauth
        )
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(ready.wait(), 2)
        await sockets[0].send_json(
            {"v": 1, "type": "request", "correlation_id": "test-1"}
        )
        await asyncio.wait_for(running.wait(), 2)
        await sockets[0].send_json({"v": 1, "type": "revoked"})
        await asyncio.wait_for(task, 2)
        assert cancelled.is_set() and len(headers) == 1
        reauth.assert_called_once()
        assert bridge.stopped
        status.assert_any_call("revoked")
        assert not responses


@pytest.mark.asyncio
async def test_busy_rejects_concurrent_requests(server, monkeypatch):
    endpoint, sockets, _headers, ready, responses = server
    monkeypatch.setitem(transport.ENVIRONMENTS, "dev", ("unused", endpoint))
    running = asyncio.Event()

    async def execute(message):
        running.set()
        await asyncio.sleep(60)

    async with aiohttp.ClientSession() as session:
        bridge = transport.BridgeTransport(
            session, "secret", "dev", execute, Mock(), Mock()
        )
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(ready.wait(), 2)
        await sockets[0].send_json(
            {"v": 1, "type": "request", "correlation_id": "first"}
        )
        await asyncio.wait_for(running.wait(), 2)
        await sockets[0].send_json(
            {"v": 1, "type": "request", "correlation_id": "second"}
        )
        async with asyncio.timeout(2):
            while not responses:
                await asyncio.sleep(0.01)
        assert responses[0]["correlation_id"] == "second"
        assert responses[0]["body"]["error"]["code"] == "BUSY"
        await bridge.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_application_heartbeat_is_sent_and_cleanly_cancelled(server, monkeypatch):
    endpoint, _sockets, _headers, ready, responses = server
    monkeypatch.setitem(transport.ENVIRONMENTS, "dev", ("unused", endpoint))
    monkeypatch.setattr(transport, "HEARTBEAT_SECONDS", 0.02)
    async with aiohttp.ClientSession() as session:
        bridge = transport.BridgeTransport(
            session, "secret", "dev", AsyncMock(), Mock(), Mock()
        )
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(ready.wait(), 2)
        async with asyncio.timeout(2):
            while not responses:
                await asyncio.sleep(0.01)
        assert responses == [{"v": 1, "type": "ping"}]
        await bridge.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_idle_connection_survives_receive_timeout(server, monkeypatch):
    # Like the gateway: answers WS pings, never replies to application pings.
    endpoint, _sockets, headers, ready, _responses = server
    monkeypatch.setitem(transport.ENVIRONMENTS, "dev", ("unused", endpoint))
    monkeypatch.setattr(transport, "HEARTBEAT_SECONDS", 0.2)
    monkeypatch.setattr(transport, "WS_PING_SECONDS", 0.1)
    monkeypatch.setattr(transport, "RECEIVE_TIMEOUT_SECONDS", 0.3)
    status = Mock()
    async with aiohttp.ClientSession() as session:
        bridge = transport.BridgeTransport(
            session, "secret", "dev", AsyncMock(), status, Mock()
        )
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(ready.wait(), 2)
        await asyncio.sleep(1.2)  # four receive-timeout windows
        assert len(headers) == 1
        status.assert_called_with("connected")
        await bridge.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
