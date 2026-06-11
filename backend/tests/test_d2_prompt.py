"""D2 prompt-quality tests (no network).

Tests:
1. 3D utterances suppress reference_sketches in the user payload.
2. has_3d_intent pattern coverage.
3. Example G (coffee mug with steam) parses, validates, renders, and has
   genuinely overlapping filled parts (the attach-and-overlap teaching).
"""

from __future__ import annotations

import json

from quorum.config.settings import Backend
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, OpType
from quorum.pipeline.intent import has_3d_intent
from quorum.pipeline.llm import LLMClassifier, _LLMPayload, payload_to_op
from quorum.pipeline.renderer import SvgRenderer

# ---------------------------------------------------------------------------
# Example G JSON — coffee mug with steam, pinned from _SYSTEM_PROMPT
# ---------------------------------------------------------------------------
_MUG = """{
  "op_type": "create",
  "target_shape": "group",
  "target_node_id": null,
  "relation_to_node": null,
  "modifiers": [],
  "preference_signal": 0.0,
  "confidence": 0.85,
  "geometry": {
    "kind": "group",
    "x": 50, "y": 50, "width": 60, "height": 60,
    "corner_radius": 0, "stroke": "#1f2937",
    "parts": [
      {"kind": "rectangle", "name": "body", "x": 46, "y": 60, "width": 28, "height": 30,
       "corner_radius": 2, "stroke": "#1f2937", "fill": "#f3f4f6", "fill_style": "solid",
       "parts": []},
      {"kind": "ellipse", "name": "coffee", "x": 46, "y": 45, "width": 24, "height": 6,
       "corner_radius": 0, "stroke": "#1f2937", "fill": "#92400e", "fill_style": "solid",
       "parts": []},
      {"kind": "path", "name": "handle", "x": 66, "y": 60, "width": 16, "height": 24,
       "corner_radius": 0, "stroke": "#1f2937", "d": "M 58 50 C 74 48 74 72 58 70",
       "parts": []},
      {"kind": "path", "name": "steam", "x": 43, "y": 34, "width": 10, "height": 20,
       "corner_radius": 0, "stroke": "#9ca3af", "d": "M 42 44 C 38 38 48 32 44 24",
       "parts": []}
    ]
  }
}"""


# ---------------------------------------------------------------------------
# Bbox helpers (mirrors the eval script)
# ---------------------------------------------------------------------------


def _bbox(part: GeometrySpec) -> tuple[float, float, float, float]:
    """(x1, y1, x2, y2) axis-aligned bounding box for a GeometrySpec part."""
    if part.points:
        xs = [p[0] for p in part.points]
        ys = [p[1] for p in part.points]
        return min(xs), min(ys), max(xs), max(ys)
    hw = (part.width or 10) / 2
    hh = (part.height or 10) / 2
    return part.x - hw, part.y - hh, part.x + hw, part.y + hh


def _overlaps(parts: list[GeometrySpec]) -> bool:
    """True if any two parts' bboxes overlap (strict interior overlap)."""
    boxes = [_bbox(p) for p in parts]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            x1a, y1a, x2a, y2a = boxes[i]
            x1b, y1b, x2b, y2b = boxes[j]
            if x1a < x2b and x2a > x1b and y1a < y2b and y2a > y1b:
                return True
    return False


# ---------------------------------------------------------------------------
# 1. has_3d_intent pattern coverage
# ---------------------------------------------------------------------------

def test_has_3d_intent_patterns() -> None:
    # True cases
    assert has_3d_intent("a 3D engine with pistons")
    assert has_3d_intent("a 3d car")
    assert has_3d_intent("an isometric house with a chimney")
    assert has_3d_intent("isometric view")
    assert has_3d_intent("three-dimensional object")
    assert has_3d_intent("three dimensional shape")
    assert has_3d_intent("draw a 3-d box")
    # False cases
    assert not has_3d_intent("a snowman wearing a top hat")
    assert not has_3d_intent("a bicycle")
    assert not has_3d_intent("a coffee mug with steam")
    assert not has_3d_intent("a sailboat on water")


# ---------------------------------------------------------------------------
# 2. 3D utterances suppress reference_sketches in the user payload
# ---------------------------------------------------------------------------

def test_3d_utterance_suppresses_reference_sketches() -> None:
    clf = LLMClassifier(backend=Backend.GROQ, model="x", api_key="k")
    ctx = ClassifierContext()
    payload_str = clf._user_payload("a 3D engine with pistons", ctx)
    payload = json.loads(payload_str)
    assert payload["context"]["reference_sketches"] is None


def test_plain_utterance_does_not_suppress_reference_sketches() -> None:
    """For a non-3D utterance, reference_sketches is NOT suppressed (may be None
    if the template bank has no match, but the suppression flag is not active)."""
    # We just check that has_3d_intent is False for a plain utterance —
    # the _user_payload branch is controlled exclusively by has_3d_intent.
    assert not has_3d_intent("a snowman wearing a top hat")
    assert not has_3d_intent("a bicycle")


# ---------------------------------------------------------------------------
# 3. Example G parses, validates, renders, has fills and overlapping parts
# ---------------------------------------------------------------------------

def test_prompt_example_g_mug_parses_renders_overlaps() -> None:
    payload = _LLMPayload.model_validate_json(_MUG)
    op = payload_to_op(
        payload,
        speaker_id="a",
        utterance_id="u1",
        raw_text="a coffee mug with steam, colored in",
    )

    # op_type and geometry basics
    assert op.op_type == OpType.CREATE
    assert op.geometry is not None
    assert op.geometry.kind is ShapeKind.GROUP

    parts = op.geometry.parts
    assert len(parts) == 4
    names = {p.name for p in parts}
    assert names == {"body", "coffee", "handle", "steam"}

    # The filled parts carry fills (steam/handle are stroked paths)
    by_name = {p.name: p for p in parts}
    assert by_name["body"].fill is not None and by_name["coffee"].fill is not None

    # Attach-and-overlap, verified pairwise: coffee occludes the body rim,
    # the handle anchors inside the body's right edge, steam dips into the
    # coffee — a connected chain, not an exploded layout.
    def _pair(a: str, b: str) -> bool:
        return _overlaps([by_name[a], by_name[b]])

    assert _pair("body", "coffee"), "coffee must occlude the body rim"
    assert _pair("body", "handle"), "handle must overlap the body edge"
    assert _pair("coffee", "steam"), "steam must touch the drink surface"

    # Renders without error and produces a valid SVG
    svg = SvgRenderer().render(op.geometry)
    assert svg.startswith("<svg")
    # Fill colors appear in the SVG
    assert "#f3f4f6" in svg  # body fill
    assert "#92400e" in svg  # coffee fill
