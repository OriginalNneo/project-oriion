"""LLM classifier — cascade stage C (plan.md §3.3).

Handles what the rules stage can't: novel phrasing, relational references, and
*complicated scene generation* ("a snowman", "a house with a chimney"). The
model emits ONE strict-JSON design operation; geometry uses the same
:class:`~quorum.domain.geometry.GeometrySpec` the whole pipeline speaks, with
``kind="group"`` + positioned ``parts`` for multi-primitive scenes.

Backends (chosen by ``QUORUM_LLM_BACKEND``):
  * ``groq``  — OpenAI-compatible chat completions, JSON mode (fast, needs key).
  * ``local`` — Ollama ``/api/chat`` with ``format: json`` (private, needs ollama).

Fault tolerance (plan.md §9): ANY failure — network, timeout, bad JSON,
validation — degrades to a zero-confidence NOOP, and the cascade falls back to
the rules result. A dead LLM never takes the loop down.
"""

from __future__ import annotations

import json

import httpx
from pydantic import BaseModel, Field

from quorum.config.settings import Backend, Settings
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.observability import get_logger

_log = get_logger("pipeline.llm")

_SYSTEM_PROMPT = """\
You turn ONE spoken utterance from a live collaborative design session into ONE JSON design operation. Reply with a single JSON object and nothing else.

Schema:
{
  "op_type": "create|branch|modify|focus|prune|connect|noop",
  "target_shape": "rectangle|circle|triangle|ellipse|line|group|node|edge|null",
  "target_node_id": "<id from context.candidates or null>",
  "relation_to_node": "<second node id, only for connect, else null>",
  "modifiers": ["fillet", "radius:8", "bigger", "smaller", "color:#dc2626"],
  "preference_signal": -1.0..1.0,
  "confidence": 0.0..1.0,
  "geometry": <GeometrySpec or null>
}

GeometrySpec: {"kind": "...", "x": 0..100, "y": 0..100, "width": 0..100, "height": 0..100, "corner_radius": 0..50, "stroke": "#rrggbb", "parts": [...]}
Coordinates are centers in an abstract 0..100 box. For a scene made of SEVERAL primitives, use kind "group" and put every primitive in "parts" with absolute coordinates in the same box; leave the group's own x/y/width/height at defaults.

Rules:
- "create" for a new idea; "branch" when it's a variant of the current focus; "modify" to change an existing node (set target_node_id from context); "focus" for preferences (preference_signal: "let's go with"≈1, "maybe"≈0.3, rejection negative); "prune" to remove; "connect" to link two existing nodes; "noop" if it is not a design intent.
- Resolve references like "the circle" or "the second one" against context.candidates and set target_node_id.
- Compose generously: "a snowman" => group of three stacked circles (e.g. big circle y≈75 d≈34, middle y≈50 d≈26, head y≈30 d≈18). "a house" => group of a rectangle (y≈62, 44x30) with a triangle roof (y≈36, 48x22). Keep parts inside 0..100 and visually coherent.

Example — utterance: "a snowman with a black hat"
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.85,"geometry":{"kind":"group","x":50,"y":50,"width":40,"height":30,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"circle","x":50,"y":76,"width":32,"height":32,"corner_radius":0,"stroke":"#1f2937","parts":[]},{"kind":"circle","x":50,"y":52,"width":24,"height":24,"corner_radius":0,"stroke":"#1f2937","parts":[]},{"kind":"circle","x":50,"y":33,"width":16,"height":16,"corner_radius":0,"stroke":"#1f2937","parts":[]},{"kind":"rectangle","x":50,"y":22,"width":14,"height":8,"corner_radius":0,"stroke":"#111111","parts":[]}]}}
"""


class _LLMPayload(BaseModel):
    """The strict JSON contract the model must emit (validated, not trusted)."""

    op_type: OpType = OpType.NOOP
    target_shape: ShapeKind | None = None
    target_node_id: str | None = None
    relation_to_node: str | None = None
    modifiers: list[str] = Field(default_factory=list)
    preference_signal: float = Field(default=0.0, ge=-1.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    geometry: GeometrySpec | None = None


def payload_to_op(
    payload: _LLMPayload, *, speaker_id: str, utterance_id: str, raw_text: str
) -> DesignOp:
    """Stamp a validated LLM payload with provenance to make a real DesignOp."""
    return DesignOp(
        op_type=payload.op_type,
        target_shape=payload.target_shape,
        target_node_id=payload.target_node_id,
        relation_to_node=payload.relation_to_node,
        modifiers=payload.modifiers,
        preference_signal=payload.preference_signal,
        geometry=payload.geometry,
        speaker_id=speaker_id,
        utterance_id=utterance_id,
        confidence=payload.confidence,
        source_stage="llm",
        raw_text=raw_text,
    )


class LLMClassifier:
    """Stage C. Satisfies the :class:`~quorum.pipeline.interfaces.Classifier`
    Protocol so the cascade can hold it behind the same seam as the rules stage."""

    def __init__(
        self,
        *,
        backend: Backend,
        model: str,
        api_key: str | None = None,
        ollama_url: str = "http://localhost:11434",
        timeout_s: float = 8.0,
    ) -> None:
        self._backend = backend
        self._model = model
        self._api_key = api_key
        self._ollama_url = ollama_url.rstrip("/")
        self._timeout = timeout_s

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMClassifier:
        if settings.llm_backend is Backend.GROQ:
            return cls(
                backend=Backend.GROQ,
                model=settings.groq_model,
                api_key=settings.require_groq_key(),
                timeout_s=settings.llm_timeout_s,
            )
        return cls(
            backend=Backend.LOCAL,
            model=settings.ollama_model,
            ollama_url=settings.ollama_url,
            timeout_s=settings.llm_timeout_s,
        )

    async def classify(
        self,
        text: str,
        *,
        speaker_id: str,
        utterance_id: str,
        context: ClassifierContext,
    ) -> DesignOp:
        try:
            raw = await self._complete(text, context)
            payload = _LLMPayload.model_validate_json(raw)
            op = payload_to_op(
                payload, speaker_id=speaker_id, utterance_id=utterance_id, raw_text=text
            )
            _log.debug("llm_classified", op_type=str(op.op_type), confidence=op.confidence)
            return op
        except Exception as exc:
            # Degrade, never break the loop: the cascade falls back to rules.
            _log.warning("llm_classify_failed", error=str(exc), backend=str(self._backend))
            return DesignOp(
                op_type=OpType.NOOP,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                confidence=0.0,
                source_stage="llm",
                raw_text=text,
            )

    # ------------------------------------------------------------------ #
    async def _complete(self, text: str, context: ClassifierContext) -> str:
        user = json.dumps(
            {
                "utterance": text,
                "context": {
                    "focus_node_id": context.focus_node_id,
                    "candidates": [
                        {"node_id": c.node_id, "shape": str(c.shape) if c.shape else None}
                        for c in context.candidates
                    ],
                },
            }
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if self._backend is Backend.GROQ:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "messages": messages,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content: str = resp.json()["choices"][0]["message"]["content"]
                return content
            resp = await client.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            ollama_content: str = resp.json()["message"]["content"]
            return ollama_content
