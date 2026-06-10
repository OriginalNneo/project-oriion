"""Per-connection message handling — the Phase 0 loop wiring.

Decodes a :class:`ClientMessage`, routes it, and drives the pipeline tail
(classify -> engine -> broadcast). This is where the Phase-0 ``demo_op`` and a
typed ``utterance`` both become real DesignOps applied by the engine and fanned
out as diffs — i.e. the loop the phase must prove.

Kept separate from the FastAPI endpoint so it is unit-testable with fake
connections and without a live socket.
"""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from quorum.domain.messages import (
    ClientMessage,
    CorrectionMessage,
    DemoOpMessage,
    ErrorMessage,
    JoinMessage,
    PipelineStatus,
    StatusMessage,
    TranscriptMessage,
    UtteranceMessage,
    WelcomeMessage,
)
from quorum.domain.op import OpType
from quorum.gateway.connection import Connection
from quorum.gateway.rooms import Room
from quorum.observability import get_logger
from quorum.observability.latency import stage_timer
from quorum.pipeline.classify import build_classifier, demo_op_to_designop

_log = get_logger("gateway.handler")
_client_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class MessageHandler:
    """Stateless dispatcher for one room. Holds the classifier (swappable)."""

    def __init__(self, room: Room) -> None:
        self.room = room
        # Rules-only by default; rules+LLM cascade when QUORUM_LLM_BACKEND is set.
        self.classifier = build_classifier()
        self._utterance_seq = 0

    def _next_utterance_id(self, speaker_id: str) -> str:
        self._utterance_seq += 1
        return f"{speaker_id}:u{self._utterance_seq}"

    async def handle_raw(self, conn: Connection, raw: str) -> None:
        """Parse and dispatch one raw text frame from a client."""
        try:
            msg = _client_adapter.validate_json(raw)
        except ValidationError as exc:
            await conn.send(ErrorMessage(detail=f"bad message: {exc.error_count()} errors"))
            return
        await self.dispatch(conn, msg)

    async def dispatch(self, conn: Connection, msg: ClientMessage) -> None:
        if isinstance(msg, JoinMessage):
            await self._on_join(conn, msg)
        elif isinstance(msg, DemoOpMessage):
            await self._on_demo_op(conn, msg)
        elif isinstance(msg, UtteranceMessage):
            await self._on_utterance(conn, msg)
        elif isinstance(msg, CorrectionMessage):
            await self._on_correction(conn, msg)
        # AudioMessage is accepted by the schema but a no-op until Phase 1.

    # ------------------------------------------------------------------ #
    async def _on_join(self, conn: Connection, msg: JoinMessage) -> None:
        await conn.send(
            WelcomeMessage(
                room=self.room.name,
                speaker_id=msg.speaker_id,
                role=msg.role,
                snapshot=self.room.engine.snapshot(),
            )
        )

    async def _on_demo_op(self, conn: Connection, msg: DemoOpMessage) -> None:
        """Phase 0 manual trigger: known shape -> DesignOp -> engine -> broadcast."""
        uid = self._next_utterance_id(msg.speaker_id)
        await self.room.broadcast(
            StatusMessage(speaker_id=msg.speaker_id, status=PipelineStatus.SKETCHING)
        )
        op = demo_op_to_designop(msg, uid)
        await self.room.apply_and_broadcast(op)
        await self.room.broadcast(StatusMessage(status=PipelineStatus.IDLE))

    async def _on_utterance(self, conn: Connection, msg: UtteranceMessage) -> None:
        """A finished transcript -> classify -> engine -> broadcast.

        This is the Phase-1 tail already wired: server-side STT will feed text in
        here instead of the client typing it, with no change to this path.
        """
        uid = self._next_utterance_id(msg.speaker_id)
        # Transparency: echo back what we heard (plan.md §7).
        await self.room.broadcast(
            TranscriptMessage(speaker_id=msg.speaker_id, utterance_id=uid, text=msg.text)
        )
        async with stage_timer("classify", utterance_id=uid):
            op = await self.classifier.classify(
                msg.text,
                speaker_id=msg.speaker_id,
                utterance_id=uid,
                context=self.room.engine.classifier_context(),
            )
        if op.op_type is OpType.NOOP:
            _log.debug("utterance_noop", text=msg.text)
            return
        await self.room.apply_and_broadcast(op)

    async def _on_correction(self, conn: Connection, msg: CorrectionMessage) -> None:
        """'I meant X' — reclassify the corrected text as a fresh utterance."""
        await self._on_utterance(
            conn, UtteranceMessage(speaker_id=msg.speaker_id, text=msg.corrected_text)
        )
