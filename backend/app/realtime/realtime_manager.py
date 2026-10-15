"""Best-effort, server-to-client WebSocket delivery for OutputEvent messages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from fastapi import WebSocket

from backend.app.domain.events import OutputEvent
from backend.app.realtime.protocol import SystemReadyMessage


class RealtimeManager:
    """Manage active sockets and isolate a slow or broken client from other clients.

    Delivery is intentionally in-memory and best-effort. The manager does not provide
    durable delivery, replay, or exactly-once semantics; those belong to later slices.
    """

    def __init__(
        self,
        *,
        send_timeout_seconds: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        if send_timeout_seconds <= 0:
            raise ValueError("send_timeout_seconds must be greater than zero")
        self._send_timeout_seconds = send_timeout_seconds
        self._logger = logger or logging.getLogger("interactive_live_engine.realtime")
        self._connections: set[WebSocket] = set()
        self._connections_lock = asyncio.Lock()
        self._publish_lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        """Return the current in-process connection count."""

        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept and register a socket, then send the mandatory ready envelope."""

        await websocket.accept()
        async with self._connections_lock:
            self._connections.add(websocket)

        ready_message = SystemReadyMessage().model_dump(mode="json")
        if not await self._send_json(websocket, ready_message):
            await self.disconnect(websocket)
            return False
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a socket safely; repeated calls are harmless."""

        async with self._connections_lock:
            self._connections.discard(websocket)

    async def publish(self, output: OutputEvent) -> int:
        """Broadcast one validated output and return the number of successful sends.

        All clients are sent concurrently, with an independent timeout per client.
        Broadcast calls are serialized to preserve message order for each client.
        """

        if not isinstance(output, OutputEvent):
            raise TypeError("RealtimeManager.publish() requires an OutputEvent")

        payload = output.model_dump(mode="json")
        async with self._publish_lock:
            async with self._connections_lock:
                connections = tuple(self._connections)

            if not connections:
                return 0

            results = await asyncio.gather(
                *(self._send_to_connection(connection, payload) for connection in connections)
            )
        return sum(results)

    async def publish_many(self, outputs: Iterable[OutputEvent]) -> int:
        """Publish outputs in order and return the total number of successful client sends."""

        delivered = 0
        for output in outputs:
            delivered += await self.publish(output)
        return delivered

    async def _send_to_connection(
        self,
        websocket: WebSocket,
        payload: dict[str, object],
    ) -> int:
        if await self._send_json(websocket, payload):
            return 1
        await self.disconnect(websocket)
        return 0

    async def _send_json(self, websocket: WebSocket, payload: dict[str, object]) -> bool:
        try:
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=self._send_timeout_seconds,
            )
        except Exception as exc:
            # Do not log event payloads: they may contain viewer identifiers or comments.
            self._logger.warning(
                "WebSocket send failed; connection will be removed",
                extra={"failure_type": type(exc).__name__},
            )
            return False
        return True
