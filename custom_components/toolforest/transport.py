"""Async protocol-v1 outbound WSS transport, independent of HA execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import random

import aiohttp

from .const import ENVIRONMENTS, VERSION

HEARTBEAT_SECONDS = 60
WS_PING_SECONDS = 30
RECEIVE_TIMEOUT_SECONDS = 90


class BridgeTransport:
    def __init__(self, session, token, environment, execute, status, reauth):
        self.session, self.token = session, token
        self.endpoint = ENVIRONMENTS[environment][1]
        self.execute, self.status, self.reauth = execute, status, reauth
        self.ws = None
        self.request_task = None
        self.stopped = False

    async def close(self):
        self.stopped = True
        if self.request_task:
            self.request_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, aiohttp.ClientError):
                await self.request_task
        if self.ws:
            await self.ws.close()

    async def _heartbeat(self, ws):
        await asyncio.gather(self._app_ping(ws), self._ws_ping(ws))

    async def _app_ping(self, ws):
        # Refreshes the gateway's connection TTL; the gateway sends no reply.
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await ws.send_json({"v": 1, "type": "ping"})

    async def _ws_ping(self, ws):
        # The gateway is silent while idle, so its pong is the only inbound
        # frame keeping ws_receive from dropping the connection. Owned here
        # rather than aiohttp's heartbeat=, whose timer can outlive close().
        while True:
            await asyncio.sleep(WS_PING_SECONDS)
            await ws.ping()

    async def _reply(self, ws, message):
        result = await self.execute(message)
        reply = {
            "v": 1,
            "type": "response",
            "correlation_id": message.get("correlation_id"),
            "status": 200,
            "body": result,
        }
        raw = json.dumps(reply)
        if len(raw.encode()) > 28 * 1024:
            reply["body"] = {"error": {"code": "PAYLOAD_TOO_LARGE"}}
        await ws.send_json(reply)

    async def run(self):
        backoff = 1
        while not self.stopped:
            heartbeat = None
            self.status("connecting")
            try:
                async with self.session.ws_connect(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "X-Bridge-Protocol-Version": "1",
                        "X-Bridge-Agent-Version": VERSION,
                        "X-Bridge-Capability": "home_assistant",
                    },
                    # _heartbeat sends WS pings; a missing pong ends the
                    # connection through ws_receive.
                    max_msg_size=128 * 1024,
                    timeout=aiohttp.ClientWSTimeout(
                        ws_close=5, ws_receive=RECEIVE_TIMEOUT_SECONDS
                    ),
                ) as ws:
                    self.ws = ws
                    self.status("connected")
                    backoff = 1
                    heartbeat = asyncio.create_task(self._heartbeat(ws))
                    async for frame in ws:
                        if frame.type != aiohttp.WSMsgType.TEXT:
                            break
                        try:
                            message = json.loads(frame.data)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(message, dict) or message.get("v") != 1:
                            continue
                        kind = message.get("type")
                        if kind in ("revoked", "displaced"):
                            self.status(kind)
                            if kind == "revoked":
                                self.reauth()
                            await self.close()
                            return
                        if kind == "request":
                            if self.request_task and not self.request_task.done():
                                await ws.send_json(
                                    {
                                        "v": 1,
                                        "type": "response",
                                        "status": 200,
                                        "correlation_id": message.get("correlation_id"),
                                        "body": {"error": {"code": "BUSY"}},
                                    }
                                )
                            else:
                                if self.request_task:
                                    # Observe a send error from the preceding request.
                                    await self.request_task
                                self.request_task = asyncio.create_task(
                                    self._reply(ws, message)
                                )
            except aiohttp.WSServerHandshakeError as exc:
                if exc.status in (401, 403):
                    self.status("revoked")
                    self.reauth()
                    return
                self.status("reconnecting")
            except (aiohttp.ClientError, OSError, TimeoutError):
                self.status("reconnecting")
            finally:
                if heartbeat:
                    heartbeat.cancel()
                    with contextlib.suppress(
                        asyncio.CancelledError, aiohttp.ClientError
                    ):
                        await heartbeat
                if self.request_task:
                    self.request_task.cancel()
                    with contextlib.suppress(
                        asyncio.CancelledError, aiohttp.ClientError
                    ):
                        await self.request_task
                    self.request_task = None
                self.ws = None
            if not self.stopped:
                self.status("reconnecting")
                await asyncio.sleep(backoff + random.uniform(0, 0.5))
                backoff = min(30, backoff * 2)
