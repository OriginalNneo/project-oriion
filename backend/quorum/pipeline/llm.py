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

Render→critique→repair (opt-in, ``QUORUM_LLM_CRITIQUE``, default OFF): a valid
CREATE scene is additionally scored against the utterance with the keyless
adherence scorer (``quorum.eval``); below the threshold, ONE further LLM call
feeds the scorer's concrete failure notes back to the model and the
higher-scoring attempt wins. Adds at most one call per utterance (worst case
with everything on: 4 + the rate-limit-retried critique call = 6), never fires
on the rules/template fast path, and trivial single-part results skip it.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from pydantic import BaseModel, Field, ValidationError

from quorum.config.settings import Backend, Settings

if TYPE_CHECKING:
    from quorum.pipeline.retrieval import SemanticRetrieval
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.domain.parts import PartsPatch, apply_patch
from quorum.observability import get_logger
from quorum.pipeline.intent import has_volumetric_intent

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
  "target_shape": "rectangle|circle|triangle|ellipse|line|polygon|path|text|group|node|edge" or JSON null — never the STRING "null",
  "target_node_id": "<id from context.candidates or null>",
  "relation_to_node": "<second node id, only for connect, else null>",
  "modifiers": ["fillet", "radius:8", "bigger", "smaller", "color:#dc2626"],
  "preference_signal": -1.0..1.0,
  "confidence": 0.0..1.0,
  "label": "<1-3 word name for the idea card, e.g. 'cat', 'coffee mug', or null>",
  "geometry": <GeometrySpec or null>,
  "patch": {"set": [{"part": "<existing part name>", "<field>": <new value>, ...}], "add": [<complete new parts>], "remove": ["<part name>"]} or null,
  "solids": [{"shape": "box|cylinder|wedge|sphere|hemisphere", "x": 0..100, "y": 0..100, "z": 0..100, "w": >0, "d": >0, "h": >0, "color": "#rrggbb or null", "name": "<part name>"}] or null
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
- create vs modify: a NEW standalone object or arrangement ("a cube", "a smartphone", "a 3D engine", "a bicycle", "two spheres", "three boxes in a row") is ALWAYS "create" — even when a focus exists. Only pick "modify" when the words explicitly refer back to the current design using words like "add ...", "give it ...", "put a ... on it", "make it ...", "now ... to it". When in doubt, CREATE — replacing someone's idea is worse than adding a new card.
- COLOR: "stroke" is the outline; "fill" colors the body. When the speaker asks for color ("a red scarf", "colored in", "fill it in green"), set BOTH per part: fill = the color, fill_style = "solid" (or "hachure" for a sketchy fill), and keep the stroke a darker tone of it. No color mentioned → stroke #1f2937, fill null.
- TRUE 3D — PREFER "solids" for anything volumetric ("a 3D box/cube", "a cylinder", "an isometric engine", "a wedge/ramp", any solid or assembly of solids). Emit op_type "create" (or "modify" to rebuild the focus as 3D), set "target_shape" to "group", set "geometry" and "patch" to null, and give a "solids" list — even for a SINGLE solid ("a 3D sphere" = a one-element list). Map the spoken solid to the closest shape: a ramp/doorstop/(triangular) prism → "wedge"; a can/tube/pipe/rod → "cylinder"; a ball/orb/planet → "sphere"; a dome/igloo → "hemisphere"; a cube/block → "box". Each solid is an axis-aligned block placed in a RELATIVE 3D space — x→right, y→UP, z→toward you (depth); (x,y,z) is its near-bottom-left corner and (w,d,h) its size along x / z / y. ONLY relative position and size matter: the system does the exact 30° isometric projection, face shading (light top, medium front, dark side), hidden-face removal and depth-sorting, then centers and scales the whole result. Build an assembly by OVERLAPPING and stacking solids into one connected body (a piston engine = one wide block box with cylinders sitting on its top face, example J). "sphere" is a ball inscribed in its (w,d,h) box (a snowman body, a planet); "hemisphere" is a dome resting flat-side-down at y (an igloo, a radar dome). A spoken "sphere"/"hemisphere"/"orb" is ALWAYS a solid, NEVER a flat circle — "two spheres and a bigger sphere" = THREE sphere solids in ONE list (Example K); "a snowman out of spheres" = three sphere solids stacked along y. Give each solid its own "color" and a "name". Do NOT compute faces or projection yourself when you use solids — that is the system's job.
- 3D by hand (only when "solids" can't express it — a single tilted panel, a wireframe): draw the 2-3 VISIBLE faces as polygons sharing edges, offset up-right (Example E); never draw hidden faces or stack axis-aligned rectangles. Fills ON, three shades: light top (#e5e7eb), medium front (#9ca3af), dark side (#6b7280). For real solids/assemblies prefer "solids" above — its projection is exact.
- MULTI-OBJECT scenes: a counted arrangement ("two spheres and a bigger sphere", "three boxes in a row") is ONE "create" containing ALL N objects — count them in your output; never fewer, and never a "modify" of the focus. SIZE words are quantitative: "bigger"/"big" means ≥ 1.5x the diameter of its plain neighbours, "small"/"little" ≤ 0.6x — after placing your numbers, re-check that the comparative object really IS the largest/smallest in the scene. NO size word ("three spheres in a row") = ALL IDENTICAL sizes, evenly spaced; a "row" of solids shares one ground y and one depth z, spread along x. DISTINCT side-by-side objects NEVER overlap: leave a visible gap between their boxes ("in the middle"/"between" = the middle object centered with the others flanking it symmetrically); overlap only what physically attaches (a snowman's stacked spheres sink slightly into each other). Keep every object fully inside the canvas: center ± half-size stays within 0..100.
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

Example E — "a 3D cube" drawn BY HAND (FALLBACK ONLY — for a real solid like a cube PREFER "solids" / Example J; this polygon-face form is for tilted panels or wireframes that "solids" cannot express). CREATE a new idea even though a focus exists; isometric = 3 visible faces, fill shading sells the depth:
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"polygon","name":"face-front","x":50,"y":60,"width":36,"height":36,"corner_radius":0,"stroke":"#1f2937","fill":"#9ca3af","fill_style":"solid","points":[[32,42],[68,42],[68,78],[32,78]],"parts":[]},{"kind":"polygon","name":"face-top","x":57,"y":35,"width":50,"height":14,"corner_radius":0,"stroke":"#1f2937","fill":"#e5e7eb","fill_style":"solid","points":[[32,42],[46,28],[82,28],[68,42]],"parts":[]},{"kind":"polygon","name":"face-right","x":75,"y":53,"width":14,"height":50,"corner_radius":0,"stroke":"#1f2937","fill":"#6b7280","fill_style":"solid","points":[[68,42],[82,28],[82,64],[68,78]],"parts":[]}]}}

Example F — "now draw a line tangent to it" while context.focus_geometry is {"kind":"circle","name":"circle","x":40,"y":55,"width":44,"height":44} (center (40,55), r=22). Touch point at angle -45°: T = (40+22*0.707, 55-22*0.707) = (55.6,39.4); the tangent runs along (0.707,0.707), endpoints T ± 28 in that direction. Distance from (40,55) to the line = 22 = r, exactly:
{"op_type":"modify","target_shape":"group","target_node_id":"n2","relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.88,"geometry":{"kind":"group","x":50,"y":50,"width":80,"height":70,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"circle","name":"circle","x":40,"y":55,"width":44,"height":44,"corner_radius":0,"stroke":"#1f2937","parts":[]},{"kind":"path","name":"tangent-line","x":55.6,"y":39.4,"width":39.6,"height":39.6,"corner_radius":0,"stroke":"#b91c1c","d":"M 35.8 19.6 L 75.4 59.2","parts":[]}]}}

Example G — "a coffee mug with steam, colored in" (CREATE; parts attach & overlap, painter's z-order: body first, the coffee surface painted ON TOP of the body's rim, handle overlapping the body's right edge, steam touching the rim):
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.85,"geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"corner_radius":0,"stroke":"#1f2937","parts":[{"kind":"rectangle","name":"body","x":46,"y":60,"width":28,"height":30,"corner_radius":2,"stroke":"#1f2937","fill":"#f3f4f6","fill_style":"solid","parts":[]},{"kind":"ellipse","name":"coffee","x":46,"y":45,"width":24,"height":6,"corner_radius":0,"stroke":"#1f2937","fill":"#92400e","fill_style":"solid","parts":[]},{"kind":"path","name":"handle","x":66,"y":60,"width":16,"height":24,"corner_radius":0,"stroke":"#1f2937","d":"M 58 50 C 74 48 74 72 58 70","parts":[]},{"kind":"path","name":"steam","x":43,"y":34,"width":10,"height":20,"corner_radius":0,"stroke":"#9ca3af","d":"M 42 44 C 38 38 48 32 44 24","parts":[]}]}}

Example H — "add two eyes to it" while context.focus_geometry is a mouse group whose parts are named part-1..part-4 (head region around x 25-45, y 30-55). An ADD-only patch — the existing parts are never re-typed:
{"op_type":"modify","target_shape":"group","target_node_id":"n1","relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"label":null,"geometry":null,"patch":{"set":[],"add":[{"kind":"circle","name":"eye-left","x":31,"y":40,"width":4,"height":4,"corner_radius":0,"stroke":"#1f2937","fill":"#1f2937","fill_style":"solid","parts":[]},{"kind":"circle","name":"eye-right","x":40,"y":40,"width":4,"height":4,"corner_radius":0,"stroke":"#1f2937","fill":"#1f2937","fill_style":"solid","parts":[]}],"remove":[]}}

Example I — "make the left eye bigger" while focus_geometry has parts eye-left and eye-right. A SET-only patch — two fields, nothing else emitted:
{"op_type":"modify","target_shape":"group","target_node_id":"n2","relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"label":null,"geometry":null,"patch":{"set":[{"part":"eye-left","width":7,"height":7}],"add":[],"remove":[]}}

Example J — "a 3D engine with three pistons" (TRUE 3D via solids — you only place axis-aligned blocks in relative space, overlapping into one body; the system projects, shades, hides back faces, depth-sorts, and fits the result. The block is y=0..22; the pistons sit on its top face at y=22):
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"label":"engine","geometry":null,"patch":null,"solids":[{"shape":"box","x":8,"y":0,"z":10,"w":64,"d":34,"h":22,"color":"#6b7280","name":"block"},{"shape":"cylinder","x":16,"y":22,"z":20,"w":12,"d":12,"h":20,"color":"#9ca3af","name":"piston-1"},{"shape":"cylinder","x":34,"y":22,"z":20,"w":12,"d":12,"h":20,"color":"#9ca3af","name":"piston-2"},{"shape":"cylinder","x":52,"y":22,"z":20,"w":12,"d":12,"h":20,"color":"#9ca3af","name":"piston-3"}]}

Example K — "two spheres and a bigger sphere in the middle" (multi-object solids: ALL THREE spheres in one list, resting on the same ground y=0, the middle one genuinely bigger — 40 vs 26 diameter — and a clear gap between the boxes: x spans 0-26, 30-70, 74-100 never overlap):
{"op_type":"create","target_shape":"group","target_node_id":null,"relation_to_node":null,"modifiers":[],"preference_signal":0.0,"confidence":0.9,"label":"three spheres","geometry":null,"patch":null,"solids":[{"shape":"sphere","x":0,"y":0,"z":20,"w":26,"d":26,"h":26,"color":"#e5e7eb","name":"sphere-left"},{"shape":"sphere","x":30,"y":0,"z":13,"w":40,"d":40,"h":40,"color":"#d1d5db","name":"sphere-middle"},{"shape":"sphere","x":74,"y":0,"z":20,"w":26,"d":26,"h":26,"color":"#e5e7eb","name":"sphere-right"}]}
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


# Literal strings some models emit where the schema means JSON null.
_NULL_STRINGS: frozenset[str] = frozenset({"", "null", "none"})

# The solid-shape vocabulary `project_solids` understands, plus a deterministic
# synonym map so a spoken "prism"/"ball"/"tube" still lands on a projectable
# solid. Anything else defaults to "box" — a volumetric request must never die
# on a naming quibble ("model proposes, code disposes").
_KNOWN_SOLID_SHAPES: frozenset[str] = frozenset(
    {"box", "cylinder", "wedge", "sphere", "hemisphere"}
)
_SOLID_SHAPE_SYNONYMS: dict[str, str] = {
    "cube": "box",
    "block": "box",
    "cuboid": "box",
    "rectangular prism": "box",
    "prism": "wedge",
    "triangular prism": "wedge",
    "ramp": "wedge",
    "doorstop": "wedge",
    "ball": "sphere",
    "orb": "sphere",
    "globe": "sphere",
    "tube": "cylinder",
    "can": "cylinder",
    "pipe": "cylinder",
    "rod": "cylinder",
    "disc": "cylinder",
    "disk": "cylinder",
    "dome": "hemisphere",
    "half-sphere": "hemisphere",
    "half sphere": "hemisphere",
}

_SHAPE_KIND_VALUES: frozenset[str] = frozenset(k.value for k in ShapeKind)


def _normalize_solid_shape(shape: str) -> str:
    """Map a model-emitted solid shape onto the projector's vocabulary."""
    s = shape.strip().lower()
    if s in _KNOWN_SOLID_SHAPES:
        return s
    return _SOLID_SHAPE_SYNONYMS.get(s, "box")


def _normalize_payload_fields(data: dict[str, Any]) -> None:
    """Deterministic pre-validation cleanup of known model quirks (in place).

    The dominant 3D failure (measured 2026-07-11): gemini-2.5-flash-lite emits
    the STRING "null" for target_shape on single-solid answers (reading the
    schema's "...|null" literally), which failed ShapeKind validation and threw
    away otherwise-perfect solids payloads — and the temperature-0 corrective
    retry repeated the same string. Salvage, don't reject:
      * literal "null"/"none" strings in nullable fields become JSON null;
      * a target_shape outside the ShapeKind vocabulary (it is advisory only)
        degrades to None instead of failing the whole payload;
      * a bare solids OBJECT is accepted as a one-element list;
      * solid shapes are synonym-normalized (prism→wedge, ball→sphere, …) so
        every solids payload projects to SOMETHING valid.
    """
    for key in ("target_shape", "target_node_id", "relation_to_node", "label"):
        value = data.get(key)
        if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
            data[key] = None
    shape = data.get("target_shape")
    if isinstance(shape, str) and shape.strip().lower() not in _SHAPE_KIND_VALUES:
        data["target_shape"] = None
    if isinstance(data.get("solids"), dict):
        data["solids"] = [data["solids"]]
    if isinstance(data.get("solids"), list):
        for solid in data["solids"]:
            if not isinstance(solid, dict):
                continue
            if isinstance(solid.get("shape"), str):
                solid["shape"] = _normalize_solid_shape(solid["shape"])
            for key in ("color", "name"):
                value = solid.get(key)
                if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
                    solid[key] = None


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
    if not isinstance(data, dict):
        return None

    # Normalize known model quirks (string-"null", solid-shape synonyms, bare
    # solids object) before any validation — the 3D-invalid fix (seg 1).
    _normalize_payload_fields(data)

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

    # Solids (plan.md §11 D3): clamp placement into 0..100 and sizes positive
    # before validation — repair, not reject. project_solids fits the assembly
    # to the box afterward, so loose numbers still produce a valid drawing.
    if isinstance(data.get("solids"), list):
        for solid in data["solids"]:
            if not isinstance(solid, dict):
                continue
            for key in ("x", "y", "z"):
                if isinstance(solid.get(key), (int, float)):
                    solid[key] = _clamp(float(solid[key]), 0.0, 100.0)
            for key in ("w", "d", "h"):
                if isinstance(solid.get(key), (int, float)):
                    solid[key] = _clamp(float(solid[key]), 0.001, 100.0)

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


class _SolidSpec(BaseModel):
    """One axis-aligned 3D solid the model places in a RELATIVE world space
    (plan.md §11 D3). The model only supplies rough placement/size; the code
    (``domain/isometric.project_solids``) does ALL projection, shading,
    hidden-face removal, depth-sorting and fitting — "model proposes, code
    disposes", the same pattern as tangency/recolor/extrusion. Out-of-range
    numbers are clamped before validation (see ``_repair_geometry_dict``)."""

    shape: str = "box"
    x: float = Field(default=0.0, ge=0, le=100)
    y: float = Field(default=0.0, ge=0, le=100)
    z: float = Field(default=0.0, ge=0, le=100)
    w: float = Field(default=20.0, gt=0, le=100)
    d: float = Field(default=20.0, gt=0, le=100)
    h: float = Field(default=20.0, gt=0, le=100)
    color: str | None = None
    name: str | None = Field(default=None, max_length=40)


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
    # TRUE 3D (plan.md §11 D3): axis-aligned solids the code projects to an
    # exact isometric GROUP. Transient — never stored; projected in
    # `payload_to_op` before the op leaves this stage, so the engine/replay and
    # both renderers only ever see the resulting flat polygon/path GROUP.
    solids: list[_SolidSpec] | None = None


def _payload_kind(payload: _LLMPayload) -> str:
    """Which output channel the model used — for the D4 adherence diagnostic.

    Precedence mirrors ``payload_to_op``: solids project to a 3D group, else a
    patch composes against the focus, else a full geometry, else nothing.
    """
    if payload.solids:
        return "solids"
    if payload.patch is not None:
        return "patch"
    if payload.geometry is not None:
        return "geometry"
    return "none"


def payload_to_op(
    payload: _LLMPayload,
    *,
    speaker_id: str,
    utterance_id: str,
    raw_text: str,
    focus_geometry: GeometrySpec | None = None,
    focus_node_id: str | None = None,
    max_parts: int = 60,
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
    # Projected 3D is already exact — it must NOT pass through snap_relations,
    # whose `inside`/`within` snap would yank a cylinder cap into the body.
    from_solids = False
    if payload.patch is not None:
        if focus_geometry is None:
            _log.warning("llm_patch_without_focus", utterance_id=utterance_id)
        else:
            patched, warnings = apply_patch(focus_geometry, payload.patch, max_parts=max_parts)
            for w in warnings:
                _log.warning("llm_patch_clause_dropped", reason=w, utterance_id=utterance_id)
            if patched == focus_geometry:
                geometry = None  # every clause dropped -> change nothing
            else:
                geometry = patched
                # The patch was computed against the FOCUS scene; pointing the
                # op anywhere else would graft this geometry onto the wrong node.
                target_node_id = focus_node_id or payload.target_node_id
    elif payload.solids:
        # TRUE 3D (plan.md §11 D3): the model placed axis-aligned solids in
        # relative space; WE do the exact 30° isometric projection, shading,
        # hidden-face removal, depth-sort and fit. The engine and both
        # renderers only ever see the resulting flat polygon/path GROUP, so
        # replay and the wire contract are untouched.
        from quorum.domain.isometric import Solid, project_solids

        if payload.geometry is not None:
            # The prompt says emit geometry=null with solids; if the model sent
            # both, the projection wins — log it so the discard is traceable.
            _log.warning("llm_solids_overrides_geometry", utterance_id=utterance_id)
        projected = project_solids(
            [
                Solid(
                    shape=s.shape,
                    x=s.x,
                    y=s.y,
                    z=s.z,
                    w=s.w,
                    d=s.d,
                    h=s.h,
                    color=s.color,
                    name=s.name,
                )
                for s in payload.solids
            ],
            max_parts=max_parts,
        )
        if projected is not None:
            geometry = projected
            from_solids = True
            # On a MODIFY the projection replaces the whole scene; aim it at the
            # FOCUSED node (mirror the patch branch) so a hallucinated
            # target_node_id can't graft the 3D body onto the wrong card. A
            # CREATE keeps target_node_id None (it's a new idea).
            if payload.op_type is OpType.MODIFY:
                target_node_id = focus_node_id or payload.target_node_id

    return DesignOp(
        op_type=payload.op_type,
        target_shape=payload.target_shape,
        target_node_id=target_node_id,
        relation_to_node=payload.relation_to_node,
        modifiers=payload.modifiers,
        preference_signal=payload.preference_signal,
        geometry=(
            geometry
            if from_solids
            else snap_relations(raw_text, geometry, focus_geometry=focus_geometry)
        ),
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


@dataclass(frozen=True)
class _Tier:
    """One model endpoint the classifier can send to (fast or escalation).

    Immutable so a single instance can be shared across concurrent rooms and
    threaded through a request's calls without any mutable per-request state on
    the process-wide classifier.
    """

    backend: Backend
    model: str
    api_key: str | None


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
        record_diagnostics: bool = False,
        retrieval: SemanticRetrieval | None = None,
        critique: bool = False,
        critique_threshold: float = 0.8,
        max_scene_parts: int = 60,
        escalation_backend: Backend | None = None,
        escalation_model: str = "",
        escalation_api_key: str | None = None,
    ) -> None:
        self._backend = backend
        self._model = model
        self._api_key = api_key
        self._ollama_url = ollama_url.rstrip("/")
        self._timeout = timeout_s
        # Two-tier routing (D4 part 2, default OFF). The fast tier serves every
        # utterance; the escalation tier — a stronger model — serves only ones
        # flagged intricate/3D (see `_pick_tier`). When no escalation tier is
        # configured, `_escalation_tier` is None and every call uses the fast
        # tier, so behavior is byte-identical to the single-tier default.
        self._fast_tier = _Tier(backend=backend, model=model, api_key=api_key)
        self._escalation_tier: _Tier | None = (
            _Tier(
                backend=escalation_backend,
                model=escalation_model,
                api_key=escalation_api_key,
            )
            if escalation_backend is not None
            else None
        )
        # Optional embeddings tier (plan.md §3.3 stage B): semantic few-shot
        # references + a near-duplicate CREATE cache. None = off (the default).
        self._retrieval = retrieval
        # Opt-in render→critique→repair pass (QUORUM_LLM_CRITIQUE, default OFF):
        # score a CREATE scene with the keyless adherence scorer; below the
        # threshold, spend ONE extra LLM call on a repair and keep the better
        # attempt. Stage C only — the rules fast path never sees this.
        self._critique = critique
        self._critique_threshold = critique_threshold
        # Soft parts-per-scene cap (QUORUM_MAX_SCENE_PARTS, default 60) applied
        # by the projection/patch code paths this stage drives.
        self._max_parts = max_scene_parts
        # Opt-in eval hook (plan.md §11 D4): when True, `classify` records the
        # shape of each raw payload ("solids"/"patch"/"geometry"/"none") so the
        # adherence harness can report which path the model chose. Default OFF —
        # the server never reads it, so no shared mutable state is written there.
        self._record_diagnostics = record_diagnostics
        self.last_payload_kind: str | None = None

    def _pick_tier(self, text: str) -> _Tier:
        """Fast tier for everything; escalation tier for intricate/3D prompts.

        The gate is ``has_volumetric_intent`` — the 3D signal the rules stage
        uses to force escalation to stage C, widened with solids named outright
        ("sphere"/"hemisphere") — so an "engine with pistons", "isometric cube"
        or "two spheres and a bigger sphere" routes to the stronger model while
        flat shapes stay fast. No escalation tier configured ⇒ always fast.
        """
        if self._escalation_tier is not None and has_volumetric_intent(text):
            return self._escalation_tier
        return self._fast_tier

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMClassifier:
        from quorum.pipeline.retrieval import get_retrieval

        retrieval = get_retrieval(settings)  # process-wide singleton (shared across rooms)
        esc_backend = settings.llm_escalation_backend
        shared: dict[str, Any] = {
            "timeout_s": settings.llm_timeout_s,
            "retrieval": retrieval,
            "critique": settings.llm_critique,
            "critique_threshold": settings.llm_critique_threshold,
            "max_scene_parts": settings.max_scene_parts,
            "escalation_backend": esc_backend,
            "escalation_model": settings.llm_escalation_model,
            "escalation_api_key": (
                settings.require_key_for(esc_backend) if esc_backend is not None else None
            ),
        }
        if settings.llm_backend is Backend.GROQ:
            return cls(
                backend=Backend.GROQ,
                model=settings.groq_model,
                api_key=settings.require_groq_key(),
                **shared,
            )
        if settings.llm_backend is Backend.OPENROUTER:
            return cls(
                backend=Backend.OPENROUTER,
                model=settings.openrouter_model,
                api_key=settings.require_openrouter_key(),
                **shared,
            )
        return cls(
            backend=Backend.LOCAL,
            model=settings.ollama_model,
            ollama_url=settings.ollama_url,
            **shared,
        )

    async def classify(
        self,
        text: str,
        *,
        speaker_id: str,
        utterance_id: str,
        context: ClassifierContext,
    ) -> DesignOp:
        if self._record_diagnostics:
            self.last_payload_kind = None
        try:
            # Embeddings tier (optional): warm the reference index once, then try
            # the near-duplicate CREATE cache before spending an LLM round-trip.
            cache_op, refs = await self._retrieve(text, speaker_id, utterance_id)
            if cache_op is not None:
                return cache_op  # near-duplicate create — LLM skipped

            # Pick the model tier ONCE per utterance and use it for every call
            # this request makes (initial, corrective retry, critique repair).
            tier = self._pick_tier(text)

            raw = await self._complete(text, context, references=refs, tier=tier)
            payload = _parse_and_repair(raw)

            if payload is None:
                # Repair failed — make ONE corrective retry with the validation
                # error fed back to the model so it can self-correct.
                payload = await self._corrective_retry(raw, text, context, tier=tier)

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
                max_parts=self._max_parts,
            )

            if self._critique:
                # Render→critique→repair (default OFF): at most ONE extra call.
                payload, op = await self._critique_and_repair(
                    payload,
                    op,
                    text,
                    context,
                    speaker_id=speaker_id,
                    utterance_id=utterance_id,
                    tier=tier,
                )

            if self._record_diagnostics:
                self.last_payload_kind = _payload_kind(payload)
            # Remember a fresh standalone CREATE so a near-duplicate request can
            # reuse it later (skipping the LLM). Modifies/composes are excluded
            # (target_node_id set) — reusing those would be context-wrong.
            if (
                self._retrieval is not None
                and op.op_type is OpType.CREATE
                and op.geometry is not None
                and op.target_node_id is None
            ):
                await self._retrieval.remember(text, op.geometry)
            _log.debug("llm_classified", op_type=str(op.op_type), confidence=op.confidence)
            return op
        except Exception as exc:
            # Degrade, never break the loop: the cascade falls back to rules.
            _log.warning("llm_classify_failed", error=str(exc), backend=str(self._backend))
            return _noop(speaker_id=speaker_id, utterance_id=utterance_id, raw_text=text)

    async def _retrieve(
        self, text: str, speaker_id: str, utterance_id: str
    ) -> tuple[DesignOp | None, list[tuple[str, GeometrySpec]] | None]:
        """Embeddings-tier work for one utterance. Returns ``(cache_op, refs)``:
        a ready CREATE op on a near-duplicate cache hit (then refs is None), else
        the semantic few-shot references. ``(None, None)`` when retrieval is off."""
        if self._retrieval is None:
            return None, None
        if not self._retrieval.indexed:
            from quorum.pipeline.templates import all_templates

            await asyncio.to_thread(self._retrieval.index_references, all_templates())
        cached = await self._retrieval.cached(text)
        if cached is not None:
            if self._record_diagnostics:
                self.last_payload_kind = "cache"
            _log.info("llm_cache_hit", utterance_id=utterance_id)
            from quorum.pipeline.templates import match

            label = cached.label
            if label is None:
                hits = match(text, limit=1)
                label = hits[0][0] if hits else None
            cache_op = DesignOp(
                op_type=OpType.CREATE,
                target_shape=cached.kind,
                geometry=cached,
                label=label,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                confidence=0.9,
                source_stage="cache",
                raw_text=text,
            )
            return cache_op, None
        return None, await self._retrieval.references(text)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _user_payload(
        text: str,
        context: ClassifierContext,
        references: list[tuple[str, GeometrySpec]] | None = None,
    ) -> str:
        from quorum.pipeline.templates import match

        # Known-good reference sketches the model ADAPTS (not invents). Semantic
        # references (embeddings tier) win when supplied; otherwise fall back to
        # keyword template match. Suppressed on volumetric intent — flat QuickDraw
        # doodles fight 3D requests, and the flat circle+equator 'sphere' template
        # teaches the model to answer "two spheres" with flat circles instead of
        # sphere solids.
        if has_volumetric_intent(text):
            ref_pairs: list[tuple[str, GeometrySpec]] = []
        elif references is not None:
            ref_pairs = references
        else:
            ref_pairs = [(name, spec) for name, _, spec in match(text, limit=2)]
        reference_sketches = [
            {"name": name, "geometry": spec.model_dump(mode="json", exclude_defaults=True)}
            for name, spec in ref_pairs
        ] or None

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
                    "reference_sketches": reference_sketches,
                },
            }
        )

    async def _complete(
        self,
        text: str,
        context: ClassifierContext,
        *,
        references: list[tuple[str, GeometrySpec]] | None = None,
        tier: _Tier | None = None,
    ) -> str:
        user = self._user_payload(text, context, references)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        return await self._send(messages, tier=tier)

    # Per-backend OpenAI-compatible endpoint URLs.
    _OPENAI_COMPAT_URLS: ClassVar[dict[Backend, str]] = {
        Backend.GROQ: "https://api.groq.com/openai/v1/chat/completions",
        Backend.OPENROUTER: "https://openrouter.ai/api/v1/chat/completions",
    }

    async def _send(self, messages: list[dict[str, str]], *, tier: _Tier | None = None) -> str:
        """Send a message list to a model tier; return the raw content string.

        ``tier`` selects the endpoint (fast vs escalation). None = the fast tier,
        so existing single-tier callers are unaffected.
        """
        t = tier or self._fast_tier
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if t.backend in (Backend.GROQ, Backend.OPENROUTER):
                url = self._OPENAI_COMPAT_URLS[t.backend]
                headers: dict[str, str] = {"Authorization": f"Bearer {t.api_key}"}
                if t.backend is Backend.OPENROUTER:
                    headers["HTTP-Referer"] = "https://github.com/quorum"
                    headers["X-Title"] = "Quorum"
                resp = await self._post_with_retry(
                    client,
                    url,
                    headers=headers,
                    json={
                        "model": t.model,
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
                    "model": t.model,
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
        *,
        tier: _Tier | None = None,
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
            raw2 = await self._send(messages, tier=tier)
        except Exception as exc:
            _log.warning("llm_corrective_retry_failed", error=str(exc))
            return None

        payload = _parse_and_repair(raw2)
        if payload is None:
            _log.warning("llm_corrective_retry_still_invalid", backend=str(self._backend))
        else:
            _log.info("llm_corrective_retry_succeeded", backend=str(self._backend))
        return payload

    async def _critique_and_repair(
        self,
        payload: _LLMPayload,
        op: DesignOp,
        text: str,
        context: ClassifierContext,
        *,
        speaker_id: str,
        utterance_id: str,
        tier: _Tier | None = None,
    ) -> tuple[_LLMPayload, DesignOp]:
        """Render→critique→repair pass — the D4 adherence scorer applied LIVE.

        Score the CREATE scene against expectations parsed from the utterance
        (keyless, pure — ``quorum.eval``); when it falls below the configured
        threshold, make ONE further LLM call whose user payload carries the
        previous JSON answer plus the scorer's concrete failure notes, then
        keep whichever attempt scores higher (ties keep the first — the repair
        must be STRICTLY better to replace it). Same degradation stance as the
        corrective retry: any failure in here returns the original attempt.
        Trivial results (single-part geometry) skip the pass entirely.
        """
        from quorum.eval.adherence import score
        from quorum.eval.expectations import parse_expectation
        from quorum.pipeline.renderer import get_renderer

        if op.op_type is not OpType.CREATE or op.geometry is None:
            return payload, op
        geom = op.geometry
        n_parts = len(geom.parts) if geom.kind is ShapeKind.GROUP else 1
        if n_parts < 2:
            return payload, op  # trivial — not worth the extra call

        def _rendered_ok(g: GeometrySpec) -> bool:
            try:
                get_renderer().render(g)  # pure + cached; no I/O
                return True
            except Exception:
                return False

        expect = parse_expectation(text)
        first = score(
            geom,
            expect,
            rendered_ok=_rendered_ok(geom),
            payload_kind=_payload_kind(payload),
        )
        if first.overall >= self._critique_threshold:
            return payload, op

        # ONE repair turn: the original user payload extended with the previous
        # answer and the scorer's failure notes as explicit feedback.
        feedback: dict[str, Any] = json.loads(self._user_payload(text, context))
        feedback["previous_attempt"] = payload.model_dump(mode="json", exclude_none=True)
        feedback["critique"] = list(first.notes)
        feedback["instruction"] = "Fix these issues; return the full corrected JSON."
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(feedback)},
        ]
        try:
            raw2 = await self._send(messages, tier=tier)
        except Exception as exc:
            _log.warning("llm_critique_call_failed", error=str(exc))
            return payload, op

        payload2 = _parse_and_repair(raw2)
        if payload2 is None:
            _log.warning("llm_critique_repair_invalid", backend=str(self._backend))
            return payload, op
        op2 = payload_to_op(
            payload2,
            speaker_id=speaker_id,
            utterance_id=utterance_id,
            raw_text=text,
            focus_geometry=context.focus_geometry,
            focus_node_id=context.focus_node_id,
            max_parts=self._max_parts,
        )
        if op2.op_type is not OpType.CREATE or op2.geometry is None:
            _log.warning("llm_critique_repair_not_create", utterance_id=utterance_id)
            return payload, op
        second = score(
            op2.geometry,
            expect,
            rendered_ok=_rendered_ok(op2.geometry),
            payload_kind=_payload_kind(payload2),
        )
        if second.overall > first.overall:
            _log.info(
                "llm_critique_repaired",
                first=round(first.overall, 2),
                second=round(second.overall, 2),
                utterance_id=utterance_id,
            )
            return payload2, op2
        _log.info(
            "llm_critique_kept_first",
            first=round(first.overall, 2),
            second=round(second.overall, 2),
            utterance_id=utterance_id,
        )
        return payload, op

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
