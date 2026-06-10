"""The Design State Engine — the single source of truth per session.

The engine is the ONLY writer of session state (RULES.md §5). Every other stage
produces a :class:`~quorum.domain.op.DesignOp`; the engine applies it to the
idea-tree DAG, appends an immutable event, and returns a
:class:`~quorum.domain.messages.StateDiff` to broadcast.

State = a deterministic fold over the append-only event log. The in-memory tree
is a cache of that fold, so replay/undo/persistence are clean add-ons.
"""

from quorum.engine.clock import Clock, MonotonicCounter, SystemClock
from quorum.engine.state import DesignStateEngine

__all__ = ["Clock", "DesignStateEngine", "MonotonicCounter", "SystemClock"]
