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
  "target_shape": "rectangle|circle|triangle|ellipse|line|polygon|path|text|group|node|edge|null",
  "target_node_id": "<id from context.candidates or null>",
  "relation_to_node": "<second node id, only for connect, else null>",
  "modifiers": ["fillet", "radius:8", "bigger", "smaller", "color:#dc2626"],
  "preference_signal": -1.0..1.0,
  "confidence": 0.0..1.0,
  "geometry": <GeometrySpec or null>
}

GeometrySpec — pick the SIMPLEST kind that expresses the intent:
  shared fields: {"kind": "...", "x": 0..100, "y": 0..100, "width": 0..100, "height": 0..100, "corner_radius": 0..50, "stroke": "#rrggbb", "name": "<optional label for this part, for later targeted edits>", "stroke_width": 0..10, "fill_style": "hachure|solid|none", "parts": [...]}
  Coordinates are CENTERS in an abstract 0..100 box (x→right, y→DOWN: y=0 top, y=100 bottom).
  - "rectangle"/"circle"/"triangle"/"ellipse": use x,y (center) + width,height.
  - "line": a stroke from (x,y) to (x+width, y+height-50)... prefer "path" for anything non-trivial.
  - "polygon": EXACT straight-edged shapes. Set "points": [[x,y],[x,y],...] 3-32 vertices in the 0..100 box, in order around the outline. Use for star, hexagon, pentagon, arrow, diamond, chevron, isometric/cube faces, gears-as-outline, any custom angular silhouette.
  - "path": smooth or complex outlines. Set "d": a constrained SVG path. ABSOLUTE UPPERCASE COMMANDS ONLY (M L H V C Q A Z) — never lowercase/relative. All numbers in 0..100. Use for curves, blobs, leaves, hearts, speech bubbles, road/river curves.
  - "text": a label. Set "label": "the words" and "font_size": 2..12 (default 4 ≈ 15px). x,y is the text center.
  - "group": a SCENE of several primitives. Put every primitive in "parts" (each with absolute coords in the SAME 0..100 box) and leave the group's own x/y/width/height at defaults. Parts may be any kind EXCEPT group (no nesting). Give meaningful parts a "name".

Rules:
- "create" for a new idea; "branch" when it's a variant of the current focus; "modify" to change an existing node (set target_node_id from context); "focus" for preferences (preference_signal: "let's go with"≈1, "maybe"≈0.3, rejection negative); "prune" to remove; "connect" to link two existing nodes; "noop" if it is not a design intent.
- Resolve references like "the circle" or "the second one" against context.candidates and set target_node_id.
- Compose generously and use the RICH primitives — favor polygon/path/text over stacks of rectangles when they capture the shape better. Keep every coordinate inside 0..100 and the result visually coherent and centered.

Example A — "a five-pointed star" (single exact polygon):
{"op_type":"create","target_shape":"polygon","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"geometry":{"kind":"polygon","x":50,"y":50,"width":50,"height":50,"corner_radius":0,"stroke":"#1f2937","points":[[50,12],[61,38],[89,38],[66,56],[75,84],[50,67],[25,84],[34,56],[11,38],[39,38]],"parts":[]}}

Example B — "a house with a door and two windows" (group mixing rectangle, polygon roof, text):
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.85,"geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"rectangle","name":"wall","x":50,"y":64,"width":48,"height":40,"corner_radius":0,"stroke":"#1f2937","parts":[]},{"kind":"polygon","name":"roof","x":50,"y":36,"width":56,"height":24,"corner_radius":0,"stroke":"#b91c1c","points":[[24,44],[50,22],[76,44]],"parts":[]},{"kind":"rectangle","name":"door","x":50,"y":74,"width":10,"height":20,"corner_radius":0,"stroke":"#92400e","parts":[]},{"kind":"rectangle","name":"window-left","x":36,"y":58,"width":9,"height":9,"corner_radius":0,"stroke":"#2563eb","parts":[]},{"kind":"rectangle","name":"window-right","x":64,"y":58,"width":9,"height":9,"corner_radius":0,"stroke":"#2563eb","parts":[]}]}}

Example C — "a heart" (smooth path, absolute uppercase commands):
{"op_type":"create","target_shape":"path","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.88,"geometry":{"kind":"path","x":50,"y":50,"width":60,"height":54,"corner_radius":0,"stroke":"#dc2626","d":"M50 78 C20 56 22 30 40 30 C48 30 50 38 50 42 C50 38 52 30 60 30 C78 30 80 56 50 78 Z","parts":[]}}
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
