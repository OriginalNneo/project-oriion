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

Validation repair pipeline ("model proposes, code disposes"):
  1. *Clamp* — out-of-range x/y/width/height/points coordinates are clamped into
     the 0..100 box rather than rejected; path `d` data is left for the domain
     validator (clamping individual path numbers would silently corrupt curves).
  2. *Salvage* — if a group has N parts and only some fail validation after
     clamping, the bad parts are dropped; the group survives with the rest
     (requires >= 1 surviving part).
  3. *Retry* — if the whole payload is still invalid after clamp+salvage, ONE
     additional LLM call is made with the pydantic error appended as a corrective
     user message. The existing 429/5xx retry is orthogonal; total worst-case
     calls per utterance = 2 (rate-limit) x 2 (validation) = 4, but never more.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from quorum.config.settings import Backend, Settings
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.domain.parts import PartsPatch, apply_patch
from quorum.observability import get_logger
from quorum.pipeline.intent import has_3d_intent

_log = get_logger("pipeline.llm")

# Maximum tokens requested from the LLM. The IR caps path data at 64 commands /
# 600 chars and full scenes are a few KB of JSON — 4096 tokens covers it
# comfortably. Tunable without a code change via QUORUM_LLM_MAX_TOKENS.
_MAX_TOKENS: int = int(os.environ.get("QUORUM_LLM_MAX_TOKENS", "4096"))

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
  "label": "<1-3 word name for the idea card, e.g. 'cat', 'coffee mug', or null>",
  "geometry": <GeometrySpec or null>,
  "patch": {"set": [{"part": "<existing part name>", "<field>": <new value>, ...}], "add": [<complete new parts>], "remove": ["<part name>"]} or null
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

PAINTER'S Z-ORDER: parts render in list order — later parts are drawn ON TOP of earlier ones. Build back-to-front: backgrounds first, foreground details last. For a filled body with a window: body rectangle first (filled), window on top. This is how occlusion works — embrace it.

Rules:
- "create" for a new idea; "branch" when it's a variant of the current focus; "modify" to change an existing node (set target_node_id from context); "focus" for preferences (preference_signal: "let's go with"≈1, "maybe"≈0.3, rejection negative); "prune" to remove; "connect" to link two existing nodes; "noop" if it is not a design intent.
- create vs modify: a NEW standalone object ("a cube", "a smartphone", "a 3D engine", "a bicycle") is ALWAYS "create" — even when a focus exists. Only pick "modify" when the words explicitly refer back to the current design using words like "add ...", "give it ...", "put a ... on it", "make it ...", "now ... to it". When in doubt, CREATE — replacing someone's idea is worse than adding a new card.
- COLOR: "stroke" is the outline; "fill" colors the body. When the speaker asks for color ("a red scarf", "colored in", "fill it in green"), set BOTH per part: fill = the color, fill_style = "solid" (or "hachure" for a sketchy fill), and keep the stroke a darker tone of it. No color mentioned → stroke #1f2937, fill null.
- 3D look ("a 3D X", "isometric X"): draw the 2-3 VISIBLE faces as separate polygons sharing edges — front face, then top and side as parallelograms offset up-right (Example E). Never draw hidden faces and never stack axis-aligned rectangles for 3D. Fills ON, three shades sell the depth: light top (#e5e7eb), medium front (#9ca3af), dark side (#6b7280). For a 3D assembly ("a 3D engine"), every component gets its faces and components OVERLAP into one connected body.
- GEOMETRIC RELATIONS are exact — compute the numbers, never just place shapes near each other:
  * tangent to a circle (center c, radius r): pick a touch point T = c + r*(cos a, sin a); the line passes through T perpendicular to the radius, i.e. along (-sin a, cos a). Endpoints = T ± L*(-sin a, cos a). The line's distance from c must equal r exactly — it touches at ONE point and never crosses the rim.
  * perpendicular: directions at 90° (dot product 0). parallel: equal directions, offset apart. concentric: identical center, different radii. inscribed: inner shape's rim touches the outer shape from inside. through the center / diameter: the segment passes through c.
  * angles ("at 45 degrees"): direction = (cos 45°, sin 45°) = (0.707, 0.707); remember y grows DOWNWARD, so "up at 45°" is (0.707, -0.707).
- Resolve references like "the circle" or "the second one" against context.candidates and set target_node_id.
- EDITING the current design — PREFER "patch" over "geometry". When the utterance changes, adds, or removes PARTS of context.focus_geometry, emit op_type "modify" with "patch" and leave "geometry" null. The system applies your delta to the stored scene (remove, then set, then add) — you never re-type the untouched parts, so nothing can drift. Rules: "set" entries name an EXISTING part (exact name from focus_geometry) plus ONLY the fields to change (never "kind"); "add" entries are complete parts with UNIQUE kebab-case role-position names ("eye-left", "wheel-2") placed correctly relative to the existing parts; "remove" lists part names to delete.
- Re-emit a full "geometry" ONLY for restructures a patch cannot express (e.g. rearranging everything). If you do: copy EVERY surviving part from context.focus_geometry BYTE-FOR-BYTE — same kind, name, x, y, width, height, points — your geometry REPLACES the node's geometry entirely, and omitting a part deletes it.
- PLACEMENT words are spatial commands, not decoration. "inside X" / "in it": the new part's box lies FULLY within the existing scene's box — center it there unless told otherwise — and comes AFTER the parts it sits in, so it paints on top. "on top of X": its bottom edge touches X's top edge. "on X" in a 3D scene: it sits on the visible top face. Never drop the new part outside the scene it extends.
- RESTYLING the current design ("make it orange", "shade it into a tabby", "give it stripes"): op_type "modify" with a "patch" — "set" entries changing ONLY stroke / fill / fill_style per part, plus "add" entries for small detail parts (stripes) when the style demands them. Detail parts stay SMALL and well-placed: stripes/spots are SEVERAL thin shapes (each height <= 4) following the body's outline near its edges — never one big block, and never covering key features (eyes, face, screen). NEVER redraw, simplify, or flatten the object: a 3D object keeps exactly its shaded faces, just re-tinted; shading = the same hue in light/medium/dark variants per face.
- Set "label" to a 1-3 word name for the idea ("cat", "coffee mug"). On modify you may refine it ("orange cat") or leave it null to inherit the existing name.
- For a named object ("a snowman", "a rocket", "a funnel on its side"), first decompose it into named parts (body, head, nozzle, fins, ...), pick the best primitive for each part. Parts ATTACH and OVERLAP — neighbouring parts' boxes share area or at least an edge (a snowman = three circles stacked and overlapping); never lay components out disjoint side-by-side — that is an exploded blueprint, not a sketch. Even a "simple"/"basic" object gets its 2-4 signature parts (a phone = body + screen + camera dot; a car = body + cabin + 2 wheels) — one lone rectangle is never a recognizable sketch. Orientation matters: "on its side"/"upside down" means emit the rotated silhouette's points/path directly.
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

Example G — "a coffee mug with steam, colored in" (CREATE; parts attach & overlap, painter's z-order: body first, the coffee surface painted ON TOP of the body's rim, handle overlapping the body's right edge, steam touching the rim):
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.85,"geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"rectangle","name":"body","x":46,"y":60,"width":28,"height":30,"corner_radius":2,"stroke":"#1f2937","fill":"#f3f4f6","fill_style":"solid","parts":[]},{"kind":"ellipse","name":"coffee","x":46,"y":45,"width":24,"height":6,"corner_radius":0,"stroke":"#1f2937","fill":"#92400e","fill_style":"solid","parts":[]},{"kind":"path","name":"handle","x":66,"y":60,"width":16,"height":24,"corner_radius":0,"stroke":"#1f2937","d":"M 58 50 C 74 48 74 72 58 70","parts":[]},{"kind":"path","name":"steam","x":43,"y":34,"width":10,"height":20,"corner_radius":0,"stroke":"#9ca3af","d":"M 42 44 C 38 38 48 32 44 24","parts":[]}]}}

Example H — "add two eyes to it" while context.focus_geometry is a mouse group whose parts are named part-1..part-4 (head region around x 25-45, y 30-55). An ADD-only patch — the existing parts are never re-typed:
{"op_type":"modify","target_shape":"group","target_node_id":"n1","relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"label":null,"geometry":null,"patch":{"set":[],"add":[{"kind":"circle","name":"eye-left","x":31,"y":40,"width":4,"height":4,"corner_radius":0,"stroke":"#1f2937","fill":"#1f2937","fill_style":"solid","parts":[]},{"kind":"circle","name":"eye-right","x":40,"y":40,"width":4,"height":4,"corner_radius":0,"stroke":"#1f2937","fill":"#1f2937","fill_style":"solid","parts":[]}],"remove":[]}}

Example I — "make the left eye bigger" while focus_geometry has parts eye-left and eye-right. A SET-only patch — two fields, nothing else emitted:
{"op_type":"modify","target_shape":"group","target_node_id":"n2","relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"label":null,"geometry":null,"patch":{"set":[{"part":"eye-left","width":7,"height":7}],"add":[],"remove":[]}}
"""


def _clamp(v: float, lo: float, hi: float) -> float:
    """Return v clamped to [lo, hi]."""
    return max(lo, min(hi, v))


def _split_concatenated_pair(value: Any) -> list[float] | None:
    """Recover a `[3040]` points entry as `[30, 40]` — a live llama-4-scout
    malformation: the comma between a coordinate pair gets dropped, fusing
    the two numbers. Only fires when the digits split UNIQUELY into two valid
    coordinates (each 0..100, no leading zeros) — ambiguity means we leave it
    for the validator to reject rather than guess.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if value != int(value) or not 100 < value:  # a legal lone coord can't split
        return None
    digits = str(int(value))
    candidates: list[list[float]] = []
    for cut in range(1, len(digits)):
        a, b = digits[:cut], digits[cut:]
        if (a != "0" and a.startswith("0")) or (b != "0" and b.startswith("0")):
            continue
        if int(a) <= 100 and int(b) <= 100:
            candidates.append([float(a), float(b)])
    return candidates[0] if len(candidates) == 1 else None


def _repair_geometry_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Clamp out-of-range scalar geometry fields in a raw dict in place.

    Only the fields that GeometrySpec validates with ge/le bounds are touched
    here.  Path `d` data is NOT touched — corrupting individual numbers in a
    curve would change its shape; the domain validator is the right gatekeeper.
    Returns the same dict (mutated) for convenience.
    """
    # x, y: centers in the 0..100 box
    for key in ("x", "y"):
        if isinstance(raw.get(key), (int, float)):
            raw[key] = _clamp(float(raw[key]), 0.0, 100.0)
    # width, height: gt=0 le=100 (domain uses gt, so floor at a tiny positive)
    for key in ("width", "height"):
        if isinstance(raw.get(key), (int, float)):
            raw[key] = _clamp(float(raw[key]), 0.001, 100.0)
    # corner_radius: ge=0 le=50
    if isinstance(raw.get("corner_radius"), (int, float)):
        raw["corner_radius"] = _clamp(float(raw["corner_radius"]), 0.0, 50.0)
    # font_size: gt=0 le=20
    if isinstance(raw.get("font_size"), (int, float)):
        raw["font_size"] = _clamp(float(raw["font_size"]), 0.001, 20.0)
    # stroke_width: gt=0 le=10 (only if present and not None)
    if isinstance(raw.get("stroke_width"), (int, float)):
        raw["stroke_width"] = _clamp(float(raw["stroke_width"]), 0.001, 10.0)
    # polygon points: each coordinate must be in 0..100
    if isinstance(raw.get("points"), list):
        clamped_points: list[Any] = []
        for pt in raw["points"]:
            if isinstance(pt, (list, tuple)) and len(pt) == 1:
                pt = _split_concatenated_pair(pt[0]) or pt
            if isinstance(pt, (list, tuple)) and len(pt) == 2:
                clamped_points.append(
                    [_clamp(float(pt[0]), 0.0, 100.0), _clamp(float(pt[1]), 0.0, 100.0)]
                )
            else:
                clamped_points.append(pt)  # leave malformed points for the validator to reject
        raw["points"] = clamped_points
    # recurse into parts
    if isinstance(raw.get("parts"), list):
        for part in raw["parts"]:
            if isinstance(part, dict):
                _repair_geometry_dict(part)
    return raw


def _salvage_group_parts(raw: dict[str, Any]) -> GeometrySpec | None:
    """Attempt to salvage a group whose parts fail validation individually.

    Strategy: validate each part independently; keep the ones that pass, drop
    the rest. A group with >= 1 surviving part is returned; if no parts survive
    the whole spec is un-salvageable and we return None.

    This only applies to groups — non-group specs with a bad payload cannot be
    meaningfully salvaged without changing the shape's meaning.
    """
    if raw.get("kind") != "group":
        return None
    raw_parts: list[Any] = raw.get("parts") or []
    if not raw_parts:
        return None
    good_parts: list[dict[str, Any]] = []
    for part in raw_parts:
        if not isinstance(part, dict):
            continue
        _repair_geometry_dict(part)
        try:
            GeometrySpec.model_validate(part)
            good_parts.append(part)
        except (ValidationError, ValueError) as exc:
            _log.warning(
                "llm_part_dropped",
                kind=part.get("kind"),
                name=part.get("name"),
                reason=str(exc),
            )
    if not good_parts:
        return None
    salvaged = {**raw, "parts": good_parts}
    try:
        return GeometrySpec.model_validate(salvaged)
    except (ValidationError, ValueError):
        return None


def _parse_and_repair(raw_json: str) -> _LLMPayload | None:
    """Parse the LLM's raw JSON string, applying the clamp+salvage repair pass.

    Returns a validated _LLMPayload, or None if the payload is un-repairable.
    The domain validators (GeometrySpec) are NOT loosened — we only pre-process
    the raw dict before handing it to Pydantic.
    """
    try:
        data: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    # Clamp geometry fields before validation
    if isinstance(data.get("geometry"), dict):
        _repair_geometry_dict(data["geometry"])
    # The same clamp applies to a patch's added parts and set-merge fields
    # (plan.md §13 N3) — out-of-range numbers get clamped, not rejected.
    if isinstance(data.get("patch"), dict):
        patch_raw = data["patch"]
        if isinstance(patch_raw.get("add"), list):
            for entry in patch_raw["add"]:
                if isinstance(entry, dict):
                    _repair_geometry_dict(entry)
        if isinstance(patch_raw.get("set"), list):
            for entry in patch_raw["set"]:
                if isinstance(entry, dict):
                    _repair_geometry_dict(entry)

    # First attempt: validate the full payload as-is (post-clamp)
    try:
        return _LLMPayload.model_validate(data)
    except (ValidationError, ValueError):
        pass

    # Second attempt: salvage — if geometry is a group, try dropping bad parts
    if isinstance(data.get("geometry"), dict):
        salvaged_geom = _salvage_group_parts(data["geometry"])
        if salvaged_geom is not None:
            try:
                repaired = {**data, "geometry": salvaged_geom.model_dump(mode="python")}
                return _LLMPayload.model_validate(repaired)
            except (ValidationError, ValueError):
                pass

    return None


class _LLMPayload(BaseModel):
    """The strict JSON contract the model must emit (validated, not trusted)."""

    op_type: OpType = OpType.NOOP
    target_shape: ShapeKind | None = None
    target_node_id: str | None = None
    relation_to_node: str | None = None
    modifiers: list[str] = Field(default_factory=list)
    preference_signal: float = Field(default=0.0, ge=-1.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Concept name for the idea card ("cat", "coffee mug"); None on modify
    # means "inherit the node's existing label" (plan.md §12 R3).
    label: str | None = Field(default=None, max_length=40)
    geometry: GeometrySpec | None = None
    # Scene-edit DELTA (plan.md §13 N3): set/add/remove against the focused
    # scene's named parts. Preferred over re-emitting `geometry` for edits —
    # research-verified to be far more reliable than verbatim re-serialization
    # (the model emits only what changes; our code composes the new scene).
    patch: PartsPatch | None = None


def payload_to_op(
    payload: _LLMPayload,
    *,
    speaker_id: str,
    utterance_id: str,
    raw_text: str,
    focus_geometry: GeometrySpec | None = None,
    focus_node_id: str | None = None,
) -> DesignOp:
    """Stamp a validated LLM payload with provenance to make a real DesignOp.

    Exact geometric relations the utterance names (tangency, containment) are
    SNAPPED here: the model supplies intent and rough placement; the
    arithmetic is ours (a live tangent came back 7 units off — LLMs don't do
    math). `focus_geometry` tells the containment snap which parts already
    existed, so only the ADDED parts get moved inside.

    A `patch` payload (plan.md §13) is composed against `focus_geometry` here
    — model proposes the delta, code disposes the scene — so the engine still
    receives a plain replacement geometry and replay is untouched. A patch
    whose every clause was dropped by validation degrades to a no-geometry op
    (the engine treats it as no change) rather than guessing.
    """
    from quorum.pipeline.relations import snap_relations
    from quorum.pipeline.templates import match

    # Label fallback: a CREATE/BRANCH without a model-supplied label takes the
    # matched template concept name ("a snowman" -> "snowman") so the node is
    # still addressable by name later ("make the snowman blue"). MODIFY stays
    # None so the engine inherits the parent node's label (plan.md §12 R3).
    label = payload.label
    if label is None and payload.op_type in (OpType.CREATE, OpType.BRANCH):
        hits = match(raw_text, limit=1)
        if hits:
            label = hits[0][0]

    geometry = payload.geometry
    target_node_id = payload.target_node_id
    if payload.patch is not None:
        if focus_geometry is None:
            _log.warning("llm_patch_without_focus", utterance_id=utterance_id)
        else:
            patched, warnings = apply_patch(focus_geometry, payload.patch)
            for w in warnings:
                _log.warning("llm_patch_clause_dropped", reason=w, utterance_id=utterance_id)
            if patched == focus_geometry:
                geometry = None  # every clause dropped -> change nothing
            else:
                geometry = patched
                # The patch was computed against the FOCUS scene; pointing the
                # op anywhere else would graft this geometry onto the wrong node.
                target_node_id = focus_node_id or payload.target_node_id

    return DesignOp(
        op_type=payload.op_type,
        target_shape=payload.target_shape,
        target_node_id=target_node_id,
        relation_to_node=payload.relation_to_node,
        modifiers=payload.modifiers,
        preference_signal=payload.preference_signal,
        geometry=snap_relations(raw_text, geometry, focus_geometry=focus_geometry),
        label=label,
        speaker_id=speaker_id,
        utterance_id=utterance_id,
        confidence=payload.confidence,
        source_stage="llm",
        raw_text=raw_text,
    )


def _noop(*, speaker_id: str, utterance_id: str, raw_text: str) -> DesignOp:
    """Zero-confidence NOOP — the graceful degradation result."""
    return DesignOp(
        op_type=OpType.NOOP,
        speaker_id=speaker_id,
        utterance_id=utterance_id,
        confidence=0.0,
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
            payload = _parse_and_repair(raw)

            if payload is None:
                # Repair failed — make ONE corrective retry with the validation
                # error fed back to the model so it can self-correct.
                payload = await self._corrective_retry(raw, text, context)

            if payload is None:
                # Both attempts exhausted — degrade gracefully.
                _log.warning(
                    "llm_classify_failed_after_retry",
                    backend=str(self._backend),
                )
                return _noop(speaker_id=speaker_id, utterance_id=utterance_id, raw_text=text)

            op = payload_to_op(
                payload,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                raw_text=text,
                focus_geometry=context.focus_geometry,
                focus_node_id=context.focus_node_id,
            )
            _log.debug("llm_classified", op_type=str(op.op_type), confidence=op.confidence)
            return op
        except Exception as exc:
            # Degrade, never break the loop: the cascade falls back to rules.
            _log.warning("llm_classify_failed", error=str(exc), backend=str(self._backend))
            return _noop(speaker_id=speaker_id, utterance_id=utterance_id, raw_text=text)

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
                        {
                            "node_id": c.node_id,
                            "shape": str(c.shape) if c.shape else None,
                            "label": c.label,
                        }
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
                    # Flat QuickDraw doodles fight 3D intent, so suppress them.
                    "reference_sketches": (
                        None  # flat doodles fight 3D intent — suppress them
                        if has_3d_intent(text)
                        else [
                            {
                                "name": name,
                                "geometry": spec.model_dump(mode="json", exclude_defaults=True),
                            }
                            for name, _, spec in match(text, limit=2)
                        ] or None
                    ),
                },
            }
        )

    async def _complete(self, text: str, context: ClassifierContext) -> str:
        user = self._user_payload(text, context)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        return await self._send(messages)

    async def _send(self, messages: list[dict[str, str]]) -> str:
        """Send a message list to the configured backend; return the raw content string."""
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
                        "max_tokens": _MAX_TOKENS,
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
                    "options": {"temperature": 0, "num_predict": _MAX_TOKENS},
                },
            )
            resp.raise_for_status()
            ollama_content: str = resp.json()["message"]["content"]
            return ollama_content

    async def _corrective_retry(
        self,
        bad_raw: str,
        text: str,
        context: ClassifierContext,
    ) -> _LLMPayload | None:
        """Feed the bad reply + a corrective prompt back to the model for ONE retry.

        This is the validation-repair retry — orthogonal to the rate-limit retry
        in ``_post_with_retry``.  The total worst-case call count per utterance is
        2 (rate-limit) x 2 (validation) = 4, but no retry-on-retry explosion is
        possible because this method never calls itself.
        """
        user = self._user_payload(text, context)
        # Try to extract the pydantic error message from the bad payload so the
        # model knows exactly what to fix.
        try:
            _LLMPayload.model_validate_json(bad_raw)
            error_hint = "The JSON did not conform to the expected schema."
        except Exception as exc:
            error_hint = str(exc)[:400]  # keep it short; the model only needs the gist

        corrective_message = (
            f"Your previous reply was invalid. Error: {error_hint}\n"
            "Please reply with a corrected JSON object that satisfies the schema. "
            "All coordinates must be numbers in the range 0..100. "
            "Return ONLY the JSON object, nothing else."
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": bad_raw},
            {"role": "user", "content": corrective_message},
        ]
        try:
            raw2 = await self._send(messages)
        except Exception as exc:
            _log.warning("llm_corrective_retry_failed", error=str(exc))
            return None

        payload = _parse_and_repair(raw2)
        if payload is None:
            _log.warning("llm_corrective_retry_still_invalid", backend=str(self._backend))
        else:
            _log.info("llm_corrective_retry_succeeded", backend=str(self._backend))
        return payload

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
