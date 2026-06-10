"""Gateway — WebSocket rooms, sessions/identity, broadcast fan-out.

The gateway is the only stateful-looking part in Phase 0, but the *authoritative*
state lives in the engine; the gateway just holds connections and routes
messages (RULES.md §5: gateways stay stateless w.r.t. design state — at Phase 5
the engine state moves to Redis and the gateway scales horizontally).

Transport is abstracted behind :class:`Connection` so the room logic is testable
without a real socket.
"""

from quorum.gateway.connection import Connection, WebSocketConnection
from quorum.gateway.rooms import Room, RoomManager

__all__ = ["Connection", "Room", "RoomManager", "WebSocketConnection"]
