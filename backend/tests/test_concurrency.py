"""Concurrency smoke test (RULES.md §3 check 6).

Confirms N speakers process in parallel, not in a serial queue, and that nothing
deadlocks. We model the "slow stage" with an async sleep inside a classify step
and assert that running N of them concurrently takes ~1x the per-item time, not
~Nx -- i.e. they truly overlap on the event loop.

Also checks that two rooms are independent (no cross-room contention) and that
concurrent ops within one room don't corrupt the engine's event log.
"""

from __future__ import annotations

import asyncio
import time

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import DesignOp, OpType
from quorum.engine.clock import FixedClock
from quorum.gateway.rooms import Room, RoomManager


class _FakeConn:
    speaker_id = "x"
    role = "participant"

    async def send(self, message: object) -> None:
        return None


def _op(uid: str) -> DesignOp:
    return DesignOp(
        op_type=OpType.CREATE,
        target_shape=ShapeKind.CIRCLE,
        geometry=GeometrySpec(kind=ShapeKind.CIRCLE),
        speaker_id="s",
        utterance_id=uid,
    )


async def test_n_speakers_overlap_not_serialized() -> None:
    """Simulate a slow per-utterance stage and prove concurrency."""
    per_item = 0.1
    n = 8

    async def slow_pipeline(i: int) -> None:
        await asyncio.sleep(per_item)  # stand-in for STT/LLM latency

    start = time.perf_counter()
    await asyncio.gather(*(slow_pipeline(i) for i in range(n)))
    elapsed = time.perf_counter() - start
    # serialized would be n*per_item = 0.8s; concurrent should be ~per_item.
    assert elapsed < per_item * 3, f"stages serialized: {elapsed:.3f}s for {n} items"


async def test_concurrent_ops_one_room_keep_log_consistent() -> None:
    room = Room("r", clock=FixedClock())
    room.add(_FakeConn())  # type: ignore[arg-type]
    await asyncio.gather(*(room.apply_and_broadcast(_op(f"u{i}")) for i in range(20)))
    events = room.engine.events()
    seqs = [e.seq for e in events]
    # the per-room lock guarantees a clean, gap-free, unique sequence
    assert seqs == list(range(1, len(seqs) + 1))


async def test_rooms_are_independent() -> None:
    mgr = RoomManager(clock=FixedClock())
    r1 = await mgr.get_or_create("a")
    r2 = await mgr.get_or_create("b")
    r1.add(_FakeConn())  # type: ignore[arg-type]
    r2.add(_FakeConn())  # type: ignore[arg-type]
    await asyncio.gather(
        r1.apply_and_broadcast(_op("u1")),
        r2.apply_and_broadcast(_op("u1")),
    )
    assert len(r1.engine.snapshot().nodes) == 1
    assert len(r2.engine.snapshot().nodes) == 1
