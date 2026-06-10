"""Core domain contracts shared across every pipeline stage and the client.

These are the *interfaces between stages*: a stage never reaches into another's
internals (RULES.md §2) — it produces or consumes one of these typed objects.

- ``geometry``  — the geometry spec the renderer turns into SVG (pure data).
- ``op``        — :class:`DesignOp`, the structured intent the classifier emits.
- ``tree``      — the idea-tree :class:`Node` and DAG the engine maintains.
- ``events``    — the append-only event log entries (event sourcing).
- ``messages``  — the WebSocket wire protocol (client <-> gateway) and state diffs.
"""

from quorum.domain.events import DesignEvent, EventType
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.messages import (
    ClientMessage,
    NodeView,
    ServerMessage,
    StateDiff,
    TreeSnapshot,
)
from quorum.domain.op import DesignOp, OpType
from quorum.domain.tree import IdeaNode, NodeStatus

__all__ = [
    "ClientMessage",
    "DesignEvent",
    "DesignOp",
    "EventType",
    "GeometrySpec",
    "IdeaNode",
    "NodeStatus",
    "NodeView",
    "OpType",
    "ServerMessage",
    "ShapeKind",
    "StateDiff",
    "TreeSnapshot",
]
