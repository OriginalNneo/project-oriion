"""Rooms and the room manager — broadcast fan-out over WebSocket.

A :class:`Room` bundles one authoritative :class:`DesignStateEngine` with the set
of connected clients. Applying a DesignOp and broadcasting the resulting diff is
serialized per-room by an asyncio lock so concurrent speakers' ops apply
atomically (the engine is the single writer — RULES.md §5). Fan-out itself is
concurrent (``asyncio.gather``) so a slow client doesn't serialize the others.

N speakers in *different* rooms never contend; N speakers in the *same* room
contend only for the microsecond-scale engine apply, not for any I/O — so this
stays within the "process in parallel, not in a queue" rule (RULES.md §5).
"""

from __future__ import annotations

import asyncio

from quorum.domain.messages import (
    DiffMessage,
    ServerMessage,
    SnapshotMessage,
    StateDiff,
)
from quorum.domain.op import DesignOp
from quorum.engine import DesignStateEngine
from quorum.engine.clock import Clock, SystemClock
from quorum.gateway.connection import Connection
from quorum.observability import get_logger

_log = get_logger("gateway.rooms")


class Room:
    """One design session: an engine + its connected clients."""

    def __init__(self, name: str, *, clock: Clock | None = None) -> None:
        self.name = name
        self.engine = DesignStateEngine(room=name, clock=clock or SystemClock())
        self._conns: set[Connection] = set()
        self._lock = asyncio.Lock()

    # --- membership ---
    def add(self, conn: Connection) -> None:
        self._conns.add(conn)
        _log.info(
            "client_joined",
            room=self.name,
            speaker_id=conn.speaker_id,
            role=str(conn.role),
            clients=len(self._conns),
        )

    def remove(self, conn: Connection) -> None:
        self._conns.discard(conn)
        _log.info(
            "client_left", room=self.name, speaker_id=conn.speaker_id, clients=len(self._conns)
        )

    @property
    def is_empty(self) -> bool:
        return not self._conns

    @property
    def client_count(self) -> int:
        return len(self._conns)

    # --- the core write+broadcast path ---
    async def apply_and_broadcast(self, op: DesignOp) -> StateDiff:
        """Apply an op to the engine and push the diff to everyone. Serialized."""
        async with self._lock:
            diff = self.engine.apply(op)
        # Broadcast outside the lock: fan-out I/O shouldn't hold up the next op.
        if diff.upserted or diff.removed_ids or op.op_type.value == "focus":
            await self.broadcast(DiffMessage(diff=diff))
        return diff

    async def send_snapshot(self, conn: Connection) -> None:
        """Send the full current tree to one client (on join / resync)."""
        await conn.send(SnapshotMessage(snapshot=self.engine.snapshot()))

    async def broadcast(self, message: ServerMessage) -> None:
        """Fan a message out to all clients concurrently; prune dead ones."""
        if not self._conns:
            return
        targets = list(self._conns)
        results = await asyncio.gather(*(c.send(message) for c in targets), return_exceptions=True)
        for conn, res in zip(targets, results, strict=True):
            if isinstance(res, Exception):
                _log.info("broadcast_drop", speaker_id=conn.speaker_id, error=str(res))
                self._conns.discard(conn)


class RoomManager:
    """Creates/looks up rooms and garbage-collects empty ones."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._rooms: dict[str, Room] = {}
        self._clock = clock or SystemClock()
        self._lock = asyncio.Lock()

    async def get_or_create(self, name: str) -> Room:
        async with self._lock:
            room = self._rooms.get(name)
            if room is None:
                room = Room(name, clock=self._clock)
                self._rooms[name] = room
                _log.info("room_created", room=name)
            return room

    async def drop_if_empty(self, name: str) -> None:
        async with self._lock:
            room = self._rooms.get(name)
            if room is not None and room.is_empty:
                del self._rooms[name]
                _log.info("room_dropped", room=name)

    @property
    def rooms(self) -> dict[str, Room]:
        return dict(self._rooms)
