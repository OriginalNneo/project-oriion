"""Gateway room/broadcast tests using an in-memory fake Connection.

Verifies fan-out reaches all clients, that a dead client doesn't break the
broadcast (fault tolerance, plan.md §9), and that apply+broadcast goes through
the engine (the single writer).
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.messages import Role, ServerMessage
from quorum.domain.op import DesignOp, OpType
from quorum.engine.clock import FixedClock
from quorum.gateway.rooms import Room


class FakeConn:
    def __init__(self, speaker_id: str, role: Role = Role.PARTICIPANT, *, fail: bool = False):
        self.speaker_id = speaker_id
        self.role = role
        self.fail = fail
        self.received: list[ServerMessage] = []

    async def send(self, message: ServerMessage) -> None:
        if self.fail:
            raise RuntimeError("dead socket")
        self.received.append(message)


def _create_op() -> DesignOp:
    return DesignOp(
        op_type=OpType.CREATE,
        target_shape=ShapeKind.CIRCLE,
        geometry=GeometrySpec(kind=ShapeKind.CIRCLE),
        speaker_id="alice",
        utterance_id="u1",
    )


async def test_broadcast_reaches_all_clients() -> None:
    room = Room("r", clock=FixedClock())
    a, b = FakeConn("alice"), FakeConn("display", Role.DISPLAY)
    room.add(a)
    room.add(b)
    await room.apply_and_broadcast(_create_op())
    assert any(m.type == "diff" for m in a.received)
    assert any(m.type == "diff" for m in b.received)


async def test_dead_client_does_not_break_broadcast() -> None:
    room = Room("r", clock=FixedClock())
    good = FakeConn("good")
    bad = FakeConn("bad", fail=True)
    room.add(good)
    room.add(bad)
    await room.apply_and_broadcast(_create_op())
    # good still got its diff; bad was pruned
    assert any(m.type == "diff" for m in good.received)
    assert room.client_count == 1


async def test_engine_is_the_state_source() -> None:
    room = Room("r", clock=FixedClock())
    room.add(FakeConn("alice"))
    diff = await room.apply_and_broadcast(_create_op())
    # the room never mutates state itself; the engine produced the diff + node
    assert diff.upserted and room.engine.snapshot().nodes
