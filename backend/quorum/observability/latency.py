"""Per-stage latency timing and the latency ledger.

The ledger is the in-process source of truth for "how fast is each stage,
really". The benchmark harness reads it; the context.md latency ledger is
populated from it. We track p50 *and* p95 — the tail is what makes conversation
feel laggy (RULES.md §6).

Usage::

    async with stage_timer("stt", utterance_id=uid):
        text = await transcriber.transcribe(audio)

The elapsed milliseconds are recorded against the stage name and logged.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from quorum.observability.logging import get_logger

_log = get_logger("latency")


@dataclass(frozen=True, slots=True)
class StageTiming:
    """A single measured stage execution."""

    stage: str
    millis: float
    utterance_id: str | None = None


@dataclass
class _Samples:
    """Accumulated millisecond samples for one stage."""

    values: list[float] = field(default_factory=list)

    def add(self, ms: float) -> None:
        self.values.append(ms)

    @property
    def count(self) -> int:
        return len(self.values)

    def percentile(self, p: float) -> float:
        """Nearest-rank percentile (p in 0..100). 0 if no samples."""
        if not self.values:
            return 0.0
        if p <= 0:
            return min(self.values)
        ordered = sorted(self.values)
        # nearest-rank
        rank = max(1, min(len(ordered), round(p / 100 * len(ordered))))
        return ordered[rank - 1]

    @property
    def p50(self) -> float:
        return median(self.values) if self.values else 0.0

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0


class LatencyLedger:
    """Aggregates stage timings across the process lifetime.

    Thread-safety note: writes happen from the async event loop (single thread
    per worker), so no lock is needed for the common case. If we later move to
    threaded executors, wrap ``record`` in a lock.
    """

    def __init__(self) -> None:
        self._stages: dict[str, _Samples] = defaultdict(_Samples)

    def record(self, timing: StageTiming) -> None:
        self._stages[timing.stage].add(timing.millis)

    def summary(self) -> dict[str, dict[str, float]]:
        """Return ``{stage: {count, p50, p95, mean}}`` for every recorded stage."""
        return {
            stage: {
                "count": float(s.count),
                "p50_ms": round(s.p50, 2),
                "p95_ms": round(s.p95, 2),
                "mean_ms": round(s.mean, 2),
            }
            for stage, s in self._stages.items()
        }

    def reset(self) -> None:
        self._stages.clear()


# Process-wide ledger. A singleton is appropriate here: latency is a global
# property of the running system, and the harness/metrics read one ledger.
_LEDGER = LatencyLedger()


def get_ledger() -> LatencyLedger:
    return _LEDGER


def _finish(stage: str, start: float, utterance_id: str | None, **fields: Any) -> float:
    millis = (time.perf_counter() - start) * 1000.0
    _LEDGER.record(StageTiming(stage=stage, millis=millis, utterance_id=utterance_id))
    _log.debug(
        "stage_timing", stage=stage, ms=round(millis, 2), utterance_id=utterance_id, **fields
    )
    return millis


@contextmanager
def stage_timer_sync(
    stage: str, *, utterance_id: str | None = None, **fields: Any
) -> Iterator[None]:
    """Synchronous variant for pure/CPU stages (e.g. the SVG renderer)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        _finish(stage, start, utterance_id, **fields)


@asynccontextmanager
async def stage_timer(stage: str, *, utterance_id: str | None = None, **fields: Any) -> Any:
    """Async context manager that times a pipeline stage and records it."""
    start = time.perf_counter()
    try:
        yield
    finally:
        _finish(stage, start, utterance_id, **fields)
