"""Transport-agnostic client connection.

Room logic talks to a :class:`Connection`, not to a raw WebSocket, so the
broadcast/fan-out logic can be unit-tested with an in-memory fake (see tests).
:class:`WebSocketConnection` adapts a Starlette/FastAPI WebSocket.
"""

from __future__ import annotations

from typing import Protocol

from quorum.domain.messages import Role, ServerMessage
from quorum.observability import get_logger

_log = get_logger("gateway.conn")


class Connection(Protocol):
    """One connected client (a participant or a display)."""

    speaker_id: str
    role: Role

    async def send(self, message: ServerMessage) -> None:
        """Serialize and send a server message. Must not raise on a dead socket —
        swallow + log, so one broken client can't break the broadcast loop."""
        ...


class WebSocketConnection:
    """Adapts a FastAPI WebSocket to the :class:`Connection` protocol."""

    def __init__(self, ws: object, speaker_id: str, role: Role) -> None:
        # `ws` is a starlette WebSocket; typed as object to keep the gateway
        # importable without FastAPI in pure-logic tests.
        self._ws = ws
        self.speaker_id = speaker_id
        self.role = role
        self.alive = True

    async def send(self, message: ServerMessage) -> None:
        if not self.alive:
            return
        try:
            # pydantic discriminated-union member -> JSON text frame
            await self._ws.send_text(message.model_dump_json())  # type: ignore[attr-defined]
        except Exception as exc:
            self.alive = False
            _log.info("send_failed", speaker_id=self.speaker_id, error=str(exc))
