"""DesignOp — the structured intent the classifier cascade emits (plan.md §3.3).

This is the contract between the *classifier* and the *Design State Engine*: the
classifier's only output, the engine's only input. Everything the engine needs
to mutate the idea tree is here; the classifier never touches the tree itself
(RULES.md §5: the engine is the only state writer).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from quorum.domain.geometry import GeometrySpec, ShapeKind


class OpType(StrEnum):
    """What the speaker wants done to the idea tree."""

    CREATE = "create"  # new root-ish idea
    MODIFY = "modify"  # change the focused/target node in place
    BRANCH = "branch"  # spawn a sibling variant of an existing node
    FOCUS = "focus"  # mark a node as the group's current preference
    PRUNE = "prune"  # collapse/remove a branch
    CONNECT = "connect"  # workflow mode: draw an edge between two nodes
    NOOP = "noop"  # classified as not a design intent (chit-chat)


class DesignOp(BaseModel):
    """One structured design intent, attributable to a speaker.

    The classifier fills as much as it can; ``confidence`` tells the engine and
    the escalation logic how much to trust the fast path vs. the LLM.
    """

    model_config = {"frozen": True}

    op_type: OpType
    target_shape: ShapeKind | None = None
    # Free-form modifiers, e.g. ["fillet", "radius:8", "bigger"].
    modifiers: list[str] = Field(default_factory=list)
    # If the op references an existing node (branch/modify/connect/focus).
    target_node_id: str | None = None
    relation_to_node: str | None = None  # second node, for CONNECT
    # Preference strength in [-1, 1]: "let's go with" ~ +1, "maybe" ~ +0.3,
    # "not the triangle" ~ -0.5. Stage C (LLM) is the main source of this.
    preference_signal: float = Field(default=0.0, ge=-1.0, le=1.0)
    # An explicit geometry the classifier already resolved (rules path often can).
    geometry: GeometrySpec | None = None
    # Human concept name for the node this op creates ("cat", "cuboid",
    # "rhombus"). The engine stores it on the IdeaNode (mind-map title) and
    # iterations inherit it; classifiers resolve "the cube"-style references
    # against it (plan.md §12 R3). Never rendered inside the sketch.
    label: str | None = None

    # Provenance / trust.
    speaker_id: str
    utterance_id: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Which cascade stage produced this op — useful for the latency story & UI.
    source_stage: str = "rules"  # rules | embeddings | llm | mock
    raw_text: str | None = None


class NodeRef(BaseModel):
    """A minimal, read-only reference to a tree node, given to the classifier.

    The classifier never sees (or touches) the full tree — only enough to resolve
    a *named* reference like "the triangle" to a node id. This keeps the engine
    the sole state owner while letting the rules/LLM stages do relational
    resolution (plan.md §3.3 stage C handles the harder cases).
    """

    model_config = {"frozen": True}

    node_id: str
    shape: ShapeKind | None = None
    label: str | None = None
    is_focus: bool = False


class ClassifierContext(BaseModel):
    """The read-only tree context handed to a classifier with each utterance."""

    model_config = {"frozen": True}

    focus_node_id: str | None = None
    candidates: list[NodeRef] = Field(default_factory=list)
    # The focused node's current geometry, so the LLM stage can EXTEND a scene
    # ("add five thrusters") by re-emitting the full group with new parts. Read
    # only — the engine remains the sole state writer.
    focus_geometry: GeometrySpec | None = None
