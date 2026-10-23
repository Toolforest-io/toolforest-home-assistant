"""Native HA fixtures; HTTP/WSS tests are restricted to ephemeral loopback servers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.toolforest.const import DOMAIN, ENVIRONMENTS


@pytest.fixture
def config_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="My HA",
        unique_id="prod:old-instance",
        data={
            "name": "My HA",
            "environment": "prod",
            "device_id": "old-instance",
            "access_token": "old-token",
        },
        options={
            "read_entities": ["light.allowed"],
            "turn_on_entities": ["light.allowed"],
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_setup_entry(monkeypatch):
    setup = AsyncMock(return_value=True)
    monkeypatch.setattr("custom_components.toolforest.async_setup_entry", setup)
    return setup


@pytest.fixture
async def device_api(aiohttp_server, socket_enabled, monkeypatch):
    state = SimpleNamespace(
        calls=[],
        sockets=[],
        connected=asyncio.Event(),
        responses={},
        code={
            "device_code": "device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://example.invalid/activate",
            "expires_in": 600,
            "interval": 5,
        },
        token={"access_token": "new-token", "device_id": "new-instance"},
        handshake_status=101,
    )

    async def post(request):
        state.calls.append(
            (request.path, await request.json(), request.headers.get("Authorization"))
        )
        value = state.responses.get(request.path)
        if isinstance(value, list):
            value = value.pop(0)
        if value is None:
            value = (
                200,
                state.code
                if request.path.endswith("/code")
                else state.token
                if request.path.endswith("/token")
                else {},
            )
        status, payload = value
        return web.json_response(payload, status=status)

    async def websocket(request):
        if state.handshake_status != 101:
            return web.Response(status=state.handshake_status)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        state.sockets.append(ws)
        state.connected.set()
        async for _ in ws:
            pass
        return ws

    app = web.Application()
    app.router.add_post("/{environment}/device/{action}", post)
    app.router.add_get("/{environment}/bridge", websocket)
    server = await aiohttp_server(app)
    for environment in ENVIRONMENTS:
        http = str(server.make_url(f"/{environment}"))
        monkeypatch.setitem(
            ENVIRONMENTS, environment, (http, http.replace("http:", "ws:") + "/bridge")
        )
    yield state
    for ws in state.sockets:
        await ws.close()
