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

import asyncio
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
  shared fields: {"kind": "...", "x": 0..100, "y": 0..100, "width": 0..100, "height": 0..100, "corner_radius": 0..50, "stroke": "#rrggbb", "fill": "#rrggbb or null", "name": "<optional label for this part, for later targeted edits>", "stroke_width": 0..10, "fill_style": "hachure|solid|none", "parts": [...]}
  Coordinates are CENTERS in an abstract 0..100 box (x→right, y→DOWN: y=0 top, y=100 bottom).
  - "rectangle"/"circle"/"triangle"/"ellipse": use x,y (center) + width,height.
  - "line": a stroke from (x,y) to (x+width, y+height-50)... prefer "path" for anything non-trivial.
  - "polygon": EXACT straight-edged shapes. Set "points": [[x,y],[x,y],...] 3-32 vertices in the 0..100 box, in order around the outline. Use for star, hexagon, pentagon, arrow, diamond, chevron, isometric/cube faces, gears-as-outline, any custom angular silhouette.
  - "path": smooth or complex outlines. Set "d": a constrained SVG path. ABSOLUTE UPPERCASE COMMANDS ONLY (M L H V C Q A Z) — never lowercase/relative. All numbers in 0..100. Use for curves, blobs, leaves, hearts, speech bubbles, road/river curves.
  - "text": a label. Set "label": "the words" and "font_size": 2..12 (default 4 ≈ 15px). x,y is the text center.
  - "group": a SCENE of several primitives. Put every primitive in "parts" (each with absolute coords in the SAME 0..100 box) and leave the group's own x/y/width/height at defaults. Parts may be any kind EXCEPT group (no nesting). Give meaningful parts a "name".

Rules:
- "create" for a new idea; "branch" when it's a variant of the current focus; "modify" to change an existing node (set target_node_id from context); "focus" for preferences (preference_signal: "let's go with"≈1, "maybe"≈0.3, rejection negative); "prune" to remove; "connect" to link two existing nodes; "noop" if it is not a design intent.
- create vs modify: a NEW standalone object ("a cube", "a smartphone") is "create" — even when a focus exists. Pick "modify" ONLY when the words refer back to the current design: "add ...", "give it ...", "put a ... on it", "make it ...", "now ... to it". When in doubt, create — replacing someone's idea is worse than adding a card.
- COLOR: "stroke" is the outline; "fill" colors the body. When the speaker asks for color ("a red scarf", "colored in", "fill it in green"), set BOTH per part: fill = the color, fill_style = "solid" (or "hachure" for a sketchy fill), and keep the stroke a darker tone of it. No color mentioned → stroke #1f2937, fill null.
- 3D look ("a 3D cube", "an isometric box"): draw the 2-3 VISIBLE faces as separate polygons — front face, then top and side as parallelograms sharing its edges, offset up-right. Never draw hidden faces and never stack axis-aligned rectangles for 3D.
- GEOMETRIC RELATIONS are exact — compute the numbers, never just place shapes near each other:
  * tangent to a circle (center c, radius r): pick a touch point T = c + r*(cos a, sin a); the line passes through T perpendicular to the radius, i.e. along (-sin a, cos a). Endpoints = T ± L*(-sin a, cos a). The line's distance from c must equal r exactly — it touches at ONE point and never crosses the rim.
  * perpendicular: directions at 90° (dot product 0). parallel: equal directions, offset apart. concentric: identical center, different radii. inscribed: inner shape's rim touches the outer shape from inside. through the center / diameter: the segment passes through c.
  * angles ("at 45 degrees"): direction = (cos 45°, sin 45°) = (0.707, 0.707); remember y grows DOWNWARD, so "up at 45°" is (0.707, -0.707).
- Resolve references like "the circle" or "the second one" against context.candidates and set target_node_id.
- EXTENDING the current design ("add five thrusters", "give it a chimney", "put a hat on it"): emit op_type "modify" with target_node_id = context.focus_node_id and geometry = the COMPLETE new scene as a group — copy every part from context.focus_geometry unchanged (keep their names and coordinates), then append the new parts. Never send only the new parts: your geometry REPLACES the node's geometry entirely.
- For a named object ("a snowman", "a rocket", "a funnel on its side"), first decompose it into named parts (body, head, nozzle, fins, ...), pick the best primitive for each part, then position the parts coherently in the 0..100 box. Even a "simple"/"basic" object gets its 2-4 signature parts (a phone = body + screen + camera dot; a car = body + cabin + 2 wheels) — one lone rectangle is never a recognizable sketch. Orientation matters: "on its side"/"upside down" means emit the rotated silhouette's points/path directly.
- context.reference_sketches: known-good geometry for concepts the utterance mentions, mined from real human drawings. When present, ADAPT the reference — reposition, rescale, recolor, combine with other parts — instead of inventing the concept from scratch. References are drawn full-canvas: shrink them when they are only one part of a larger scene.
- Compose generously and use the RICH primitives — favor polygon/path/text over stacks of rectangles when they capture the shape better. Keep every coordinate inside 0..100 and the result visually coherent and centered.

Example A — "a five-pointed star" (single exact polygon):
{"op_type":"create","target_shape":"polygon","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"geometry":{"kind":"polygon","x":50,"y":50,"width":50,"height":50,"corner_radius":0,"stroke":"#1f2937","points":[[50,12],[61,38],[89,38],[66,56],[75,84],[50,67],[25,84],[34,56],[11,38],[39,38]],"parts":[]}}

Example B — "a house with a door and two windows" (group mixing rectangle, polygon roof, text):
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.85,"geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"rectangle","name":"wall","x":50,"y":64,"width":48,"height":40,"corner_radius":0,"stroke":"#1f2937","parts":[]},{"kind":"polygon","name":"roof","x":50,"y":36,"width":56,"height":24,"corner_radius":0,"stroke":"#b91c1c","points":[[24,44],[50,22],[76,44]],"parts":[]},{"kind":"rectangle","name":"door","x":50,"y":74,"width":10,"height":20,"corner_radius":0,"stroke":"#92400e","parts":[]},{"kind":"rectangle","name":"window-left","x":36,"y":58,"width":9,"height":9,"corner_radius":0,"stroke":"#2563eb","parts":[]},{"kind":"rectangle","name":"window-right","x":64,"y":58,"width":9,"height":9,"corner_radius":0,"stroke":"#2563eb","parts":[]}]}}

Example C — "a heart" (smooth path, absolute uppercase commands):
{"op_type":"create","target_shape":"path","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.88,"geometry":{"kind":"path","x":50,"y":50,"width":60,"height":54,"corner_radius":0,"stroke":"#dc2626","d":"M50 78 C20 56 22 30 40 30 C48 30 50 38 50 42 C50 38 52 30 60 30 C78 30 80 56 50 78 Z","parts":[]}}

Example D — "now add five thrusters" while context.focus_node_id="n3" and context.focus_geometry is a group whose parts contain {"kind":"polygon","name":"funnel-body","points":[[12,28],[12,72],[58,56],[86,52],[86,48],[58,44]],...} (a funnel on its side). Copy the funnel part verbatim, append the thrusters, op is modify:
{"op_type":"modify","target_shape":"group","target_node_id":"n3","relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.85,"geometry":{"kind":"group","x":50,"y":50,"width":90,"height":60,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"polygon","name":"funnel-body","x":50,"y":50,"width":74,"height":44,"corner_radius":0,"stroke":"#1f2937","points":[[12,28],[12,72],[58,56],[86,52],[86,48],[58,44]],"parts":[]},{"kind":"rectangle","name":"thruster-1","x":7,"y":32,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c","parts":[]},{"kind":"rectangle","name":"thruster-2","x":7,"y":41,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c","parts":[]},{"kind":"rectangle","name":"thruster-3","x":7,"y":50,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c","parts":[]},{"kind":"rectangle","name":"thruster-4","x":7,"y":59,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c","parts":[]},{"kind":"rectangle","name":"thruster-5","x":7,"y":68,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c","parts":[]}]}}

Example E — "a 3D cube" (CREATE a new idea even though a focus exists; isometric = 3 visible faces, fill shading sells the depth):
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"polygon","name":"face-front","x":50,"y":60,"width":36,"height":36,"corner_radius":0,"stroke":"#1f2937","fill":"#9ca3af","fill_style":"solid","points":[[32,42],[68,42],[68,78],[32,78]],"parts":[]},{"kind":"polygon","name":"face-top","x":57,"y":35,"width":50,"height":14,"corner_radius":0,"stroke":"#1f2937","fill":"#e5e7eb","fill_style":"solid","points":[[32,42],[46,28],[82,28],[68,42]],"parts":[]},{"kind":"polygon","name":"face-right","x":75,"y":53,"width":14,"height":50,"corner_radius":0,"stroke":"#1f2937","fill":"#6b7280","fill_style":"solid","points":[[68,42],[82,28],[82,64],[68,78]],"parts":[]}]}}

Example F — "now draw a line tangent to it" while context.focus_geometry is {"kind":"circle","name":"circle","x":40,"y":55,"width":44,"height":44} (center (40,55), r=22). Touch point at angle -45°: T = (40+22*0.707, 55-22*0.707) = (55.6,39.4); the tangent runs along (0.707,0.707), endpoints T ± 28 in that direction. Distance from (40,55) to the line = 22 = r, exactly:
{"op_type":"modify","target_shape":"group","target_node_id":"n2","relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.88,"geometry":{"kind":"group","x":50,"y":50,"width":80,"height":70,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"circle","name":"circle","x":40,"y":55,"width":44,"height":44,"corner_radius":0,"stroke":"#1f2937","parts":[]},{"kind":"path","name":"tangent-line","x":55.6,"y":39.4,"width":39.6,"height":39.6,"corner_radius":0,"stroke":"#b91c1c","d":"M 35.8 19.6 L 75.4 59.2","parts":[]}]}}
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
    """Stamp a validated LLM payload with provenance to make a real DesignOp.

    Exact geometric relations the utterance names (tangency) are SNAPPED here:
    the model supplies intent and rough placement; the arithmetic is ours
    (a live tangent came back 7 units off — LLMs don't do math).
    """
    from quorum.pipeline.relations import snap_relations

    return DesignOp(
        op_type=payload.op_type,
        target_shape=payload.target_shape,
        target_node_id=payload.target_node_id,
        relation_to_node=payload.relation_to_node,
        modifiers=payload.modifiers,
        preference_signal=payload.preference_signal,
        geometry=snap_relations(raw_text, payload.geometry),
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
    @staticmethod
    def _user_payload(text: str, context: ClassifierContext) -> str:
        from quorum.pipeline.templates import match

        return json.dumps(
            {
                "utterance": text,
                "context": {
                    "focus_node_id": context.focus_node_id,
                    "candidates": [
                        {"node_id": c.node_id, "shape": str(c.shape) if c.shape else None}
                        for c in context.candidates
                    ],
                    # The focused node's current scene, so "add five thrusters"
                    # can re-emit it extended. exclude_defaults keeps it small.
                    "focus_geometry": (
                        context.focus_geometry.model_dump(mode="json", exclude_defaults=True)
                        if context.focus_geometry is not None
                        else None
                    ),
                    # Known-good sketches for concepts the utterance mentions
                    # (mined from real drawings) — the model adapts, not invents.
                    "reference_sketches": [
                        {
                            "name": name,
                            "geometry": spec.model_dump(mode="json", exclude_defaults=True),
                        }
                        for name, _, spec in match(text, limit=2)
                    ]
                    or None,
                },
            }
        )

    async def _complete(self, text: str, context: ClassifierContext) -> str:
        user = self._user_payload(text, context)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if self._backend is Backend.GROQ:
                resp = await self._post_with_retry(
                    client,
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

    @staticmethod
    async def _post_with_retry(
        client: httpx.AsyncClient, url: str, **kwargs: object
    ) -> httpx.Response:
        """POST with ONE retry on 429/5xx after a short backoff.

        Groq rate-limits back-to-back utterances in a lively session; without
        the retry the intricate drawing is silently lost to the rules fallback.
        Backoff honours Retry-After but is capped so a stage-C answer still
        lands inside the latency budget; any second failure degrades as before.
        """
        resp = await client.post(url, **kwargs)  # type: ignore[arg-type]
        if resp.status_code == 429 or resp.status_code >= 500:
            try:
                backoff = float(resp.headers.get("retry-after", "1"))
            except ValueError:
                backoff = 1.0
            await asyncio.sleep(min(backoff, 2.0))
            resp = await client.post(url, **kwargs)  # type: ignore[arg-type]
        return resp
