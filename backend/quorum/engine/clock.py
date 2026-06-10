"""Injectable clock and id generation for the engine.

The engine must be deterministic and testable, so it never calls ``time.time()``
or a random id generator directly — it asks an injected :class:`Clock` and an id
factory. Tests pass a fake clock/counter; production passes the system ones.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Epoch seconds."""
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()


class FixedClock:
    """A controllable clock for tests."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class MonotonicCounter:
    """Sequential id source: ``n1``, ``n2``, ... — deterministic, replay-safe.

    A monotonic counter (not a random uuid) keeps node ids stable across replays
    of the same event log, which matters for event sourcing and tests.
    """

    def __init__(self, prefix: str = "n") -> None:
        self._prefix = prefix
        self._i = 0

    def next(self) -> str:
        self._i += 1
        return f"{self._prefix}{self._i}"


IdFactory = Callable[[], str]
