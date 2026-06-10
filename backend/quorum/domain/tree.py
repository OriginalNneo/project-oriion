"""The idea tree (F6) — the branching DAG the Design State Engine maintains.

A node is one design suggestion. A variation becomes a child/sibling linked to
its origin, so derivations are visible (plan.md §4). The engine is the only
writer; these models are the data it stores and broadcasts.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from quorum.domain.geometry import GeometrySpec


class NodeStatus(StrEnum):
    """Lifecycle of an idea-tree node."""

    ACTIVE = "active"  # a live option in the idea cloud
    FOCUSED = "focused"  # the group's current preference
    PRUNED = "pruned"  # collapsed/de-emphasized (kept for replay/audit)


class Provenance(BaseModel):
    """Who/when/what produced this node — for group dynamics + the design record."""

    model_config = {"frozen": True}

    speaker_id: str
    utterance_id: str
    created_ts: float  # epoch seconds; supplied by the engine (testable clock)
    raw_text: str | None = None


class IdeaNode(BaseModel):
    """One node in the idea tree."""

    id: str
    geometry: GeometrySpec
    # SVG is rendered by the engine via the renderer stage and cached on the node
    # so clients that don't render locally still get a picture.
    svg: str | None = None
    parent_ids: list[str] = Field(default_factory=list)
    children_ids: list[str] = Field(default_factory=list)
    provenance: Provenance
    # How much the group has verbally favored this node (plan.md §4).
    affirmation_score: float = 0.0
    status: NodeStatus = NodeStatus.ACTIVE
    label: str | None = None
