"""Protocol interfaces for every swappable pipeline stage.

These are the contracts. An implementation (faster-whisper vs Groq, rules vs
LLM) is selected by config at the edge (a small factory per stage), so the rest
of the system depends only on the Protocol — never on a concrete backend
(plan.md §2 modularity, RULES.md §5).

Only the renderer is implemented in Phase 0; VAD/STT/Classifier are declared
here so Phases 1+ slot in against a fixed contract rather than reshaping it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from quorum.domain.geometry import GeometrySpec
from quorum.domain.op import ClassifierContext, DesignOp


@runtime_checkable
class Renderer(Protocol):
    """geometry spec -> SVG. Pure and deterministic (plan.md §3.3 stage 5).

    Implementations MUST be side-effect-free and must return identical output for
    identical input, so renders are cacheable and unit-testable.
    """

    def render(self, spec: GeometrySpec) -> str:
        """Return a complete ``<svg>...</svg>`` string for ``spec``."""
        ...


@runtime_checkable
class VAD(Protocol):
    """Voice-activity detection / endpointing (Phase 1).

    Fed PCM frames per stream; emits an "utterance complete" signal after a
    short silence window. The silence window is the key latency knob.
    """

    def push(self, speaker_id: str, pcm: bytes) -> bool:
        """Append a frame; return True if an utterance just completed."""
        ...

    def drain(self, speaker_id: str) -> bytes:
        """Return and clear the buffered audio for a completed utterance."""
        ...


@runtime_checkable
class Transcriber(Protocol):
    """STT (Phase 1). One completed utterance of audio -> text."""

    async def transcribe(self, pcm: bytes, *, speaker_id: str) -> str: ...


@runtime_checkable
class Classifier(Protocol):
    """Intent classifier cascade (Phase 1 rules -> Phase 4 full cascade).

    transcript text -> a structured DesignOp. The engine consumes the DesignOp;
    the classifier never touches tree state.
    """

    async def classify(
        self, text: str, *, speaker_id: str, utterance_id: str, context: ClassifierContext
    ) -> DesignOp: ...
