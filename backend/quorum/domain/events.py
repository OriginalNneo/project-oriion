"""The append-only event log (event sourcing).

The Design State Engine records every mutation as an immutable event before/while
applying it (plan.md §3.3 stage 4, RULES.md §5: append-only, never mutate past
events). This buys replay, audit, and undo for free, and makes durable
persistence a clean add-on at Phase 5.

The current tree state is a *fold* over these events; the in-memory tree is just
a cache of that fold.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from quorum.domain.op import DesignOp
from quorum.domain.tree import IdeaNode


class EventType(StrEnum):
    NODE_CREATED = "node_created"
    NODE_MODIFIED = "node_modified"
    NODE_BRANCHED = "node_branched"
    FOCUS_CHANGED = "focus_changed"
    NODE_PRUNED = "node_pruned"
    NODES_CONNECTED = "nodes_connected"
    AFFIRMATION_CHANGED = "affirmation_changed"


class DesignEvent(BaseModel):
    """One immutable fact about how the tree changed."""

    model_config = {"frozen": True}

    seq: int  # monotonic per session; defines total order for replay
    type: EventType
    ts: float  # epoch seconds, supplied by the engine
    # The op that caused this event (None for engine-internal events).
    op: DesignOp | None = None
    # A snapshot of the node after the change (so replay needs no re-derivation).
    node: IdeaNode | None = None
    # Misc structured payload (e.g. {"focus_node_id": "...", "previous": "..."}).
    payload: dict[str, str | float | None] = Field(default_factory=dict)
