"""WebSocket wire protocol — the single contract between client and gateway.

All realtime comms go over one WebSocket; clients hold no authoritative state,
only a view of broadcast diffs (RULES.md §4). Messages are discriminated unions
keyed on ``type`` so both Python (pydantic) and TypeScript can validate them.

Client -> Server (:class:`ClientMessage`):
  - ``join``        : join a room with a role (participant | display) and id.
  - ``audio``       : a base64 PCM frame (Phase 1+); ignored in Phase 0.
  - ``utterance``   : a finished transcript the client endpointed (Phase 1 path /
                      Phase 0 manual trigger types text directly).
  - ``demo_op``     : Phase 0 — a hardcoded DesignOp request to prove the loop.
  - ``correction``  : "I meant X" affordance (plan.md §7 transparency).

Server -> Client (:class:`ServerMessage`):
  - ``welcome``     : ack a join, hand back session/room info + current snapshot.
  - ``snapshot``    : the full tree (sent on join / resync).
  - ``diff``        : an incremental state diff (the normal broadcast).
  - ``transcript``  : what the system heard a speaker say (transparency).
  - ``status``      : pipeline status for latency-masking UI ("listening…").
  - ``error``       : a problem the client should surface.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.tree import IdeaNode, NodeStatus


class Role(StrEnum):
    PARTICIPANT = "participant"
    DISPLAY = "display"


# --------------------------------------------------------------------------- #
# Views (what the client renders) — a flattened, client-friendly projection.   #
# --------------------------------------------------------------------------- #
class NodeView(BaseModel):
    """Client-facing projection of an IdeaNode (kept stable for the UI)."""

    id: str
    geometry: GeometrySpec
    svg: str | None = None
    parent_ids: list[str]
    affirmation_score: float
    status: NodeStatus
    label: str | None = None
    suggested_by: str | None = None  # speaker_id, for the "suggested by ___" chip


class TreeSnapshot(BaseModel):
    """The whole tree — sent on join and on explicit resync."""

    room: str
    nodes: list[NodeView]
    focus_node_id: str | None = None
    seq: int = 0  # last applied event seq; lets clients detect gaps


class StateDiff(BaseModel):
    """An incremental change to broadcast. Clients animate from old -> new."""

    room: str
    seq: int
    upserted: list[NodeView] = Field(default_factory=list)
    removed_ids: list[str] = Field(default_factory=list)
    focus_node_id: str | None = None


# --------------------------------------------------------------------------- #
# Client -> Server                                                             #
# --------------------------------------------------------------------------- #
class JoinMessage(BaseModel):
    type: Literal["join"] = "join"
    room: str
    role: Role = Role.PARTICIPANT
    speaker_id: str  # the logged-in user == the mic == the speaker (F2)
    display_name: str | None = None


class AudioMessage(BaseModel):
    type: Literal["audio"] = "audio"
    speaker_id: str
    # base64-encoded 16kHz mono PCM16 frame. Phase 1+ consumes this.
    pcm_b64: str
    seq: int = 0


class UtteranceMessage(BaseModel):
    """A completed transcript (Phase 1 server-side STT will normally produce this,
    but a client may also submit text directly — e.g. the correction box)."""

    type: Literal["utterance"] = "utterance"
    speaker_id: str
    text: str


class DemoOpMessage(BaseModel):
    """Phase 0 loop-prover: ask the server to materialize a known shape.

    This is the manual trigger that stands in for the (not-yet-built) audio
    pipeline so we can prove client -> WS -> engine -> render -> broadcast.
    """

    type: Literal["demo_op"] = "demo_op"
    speaker_id: str
    shape: ShapeKind
    fillet: bool = False
    branch_from: str | None = None  # if set, spawn as a sibling variant
    focus: bool = False


class CorrectionMessage(BaseModel):
    type: Literal["correction"] = "correction"
    speaker_id: str
    utterance_id: str
    corrected_text: str


ClientMessage = Annotated[
    JoinMessage | AudioMessage | UtteranceMessage | DemoOpMessage | CorrectionMessage,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
# Server -> Client                                                             #
# --------------------------------------------------------------------------- #
class WelcomeMessage(BaseModel):
    type: Literal["welcome"] = "welcome"
    room: str
    speaker_id: str
    role: Role
    snapshot: TreeSnapshot


class SnapshotMessage(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    snapshot: TreeSnapshot


class DiffMessage(BaseModel):
    type: Literal["diff"] = "diff"
    diff: StateDiff


class TranscriptMessage(BaseModel):
    """What the system heard a speaker say (plan.md §7 transparency)."""

    type: Literal["transcript"] = "transcript"
    speaker_id: str
    utterance_id: str
    text: str
    final: bool = True


class PipelineStatus(StrEnum):
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    SKETCHING = "sketching"
    IDLE = "idle"


class StatusMessage(BaseModel):
    """Latency-masking UI hint (plan.md §7)."""

    type: Literal["status"] = "status"
    speaker_id: str | None = None
    status: PipelineStatus


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    detail: str


ServerMessage = Annotated[
    WelcomeMessage
    | SnapshotMessage
    | DiffMessage
    | TranscriptMessage
    | StatusMessage
    | ErrorMessage,
    Field(discriminator="type"),
]


def node_to_view(node: IdeaNode) -> NodeView:
    """Project an engine IdeaNode into the client-facing NodeView."""
    return NodeView(
        id=node.id,
        geometry=node.geometry,
        svg=node.svg,
        parent_ids=node.parent_ids,
        affirmation_score=node.affirmation_score,
        status=node.status,
        label=node.label,
        suggested_by=node.provenance.speaker_id,
    )
