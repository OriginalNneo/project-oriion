"""N1 / N2 / N4 routing tests (plan.md §13).

Pins:
  N1 — demonstratives (this/that) are definite references → MODIFY, not CREATE.
  N4 — deterministic extrusion routing for focus shapes and "a 3D <shape>".
  N2 — part-scoped fast path and fallback inversion.
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, NodeRef, OpType
from quorum.domain.shapes import named_shape
from quorum.pipeline.classify import _HAZY_CONFIDENCE, RulesClassifier

_CLF = RulesClassifier()


async def _classify(
    text: str,
    focus: str | None = None,
    candidates: list[NodeRef] | None = None,
    focus_geometry: GeometrySpec | None = None,
) -> DesignOp:
    ctx = ClassifierContext(
        focus_node_id=focus,
        candidates=candidates or [],
        focus_geometry=focus_geometry,
    )
    return await _CLF.classify(text, speaker_id="alice", utterance_id="u1", context=ctx)


# ---------------------------------------------------------------------------
# Helpers — reusable geometry fixtures
# ---------------------------------------------------------------------------

def _hexagon_geom() -> GeometrySpec:
    """A standalone hexagon polygon spec (as produced by named_shape)."""
    spec = named_shape("hexagon")
    assert spec is not None
    return spec


def _mouse_group() -> GeometrySpec:
    """A GROUP with parts named eye-left and eye-right, plus body."""
    eye_left = GeometrySpec(
        kind=ShapeKind.CIRCLE, name="eye-left", x=35.0, y=40.0, width=10.0, height=10.0
    )
    eye_right = GeometrySpec(
        kind=ShapeKind.CIRCLE, name="eye-right", x=65.0, y=40.0, width=10.0, height=10.0
    )
    body = GeometrySpec(
        kind=ShapeKind.CIRCLE, name="body", x=50.0, y=60.0, width=40.0, height=35.0
    )
    return GeometrySpec(kind=ShapeKind.GROUP, parts=[body, eye_left, eye_right])


def _mouse_no_eyes() -> GeometrySpec:
    """A GROUP with parts that have NO eye part (only body + tail)."""
    body = GeometrySpec(
        kind=ShapeKind.CIRCLE, name="body", x=50.0, y=60.0, width=40.0, height=35.0
    )
    tail = GeometrySpec(
        kind=ShapeKind.LINE, name="tail", x=80.0, y=80.0, width=20.0, height=5.0
    )
    return GeometrySpec(kind=ShapeKind.GROUP, parts=[body, tail])


# ===========================================================================
# N1 — demonstratives as definite references
# ===========================================================================

async def test_this_hexagon_pink_modifies_focused_node() -> None:
    """N1: 'turn this hexagon pink' with focused hexagon → MODIFY, not CREATE."""
    candidates = [NodeRef(node_id="n1", shape=None, label="hexagon", is_focus=True)]
    op = await _classify(
        "turn this hexagon pink",
        focus="n1",
        candidates=candidates,
        focus_geometry=_hexagon_geom(),
    )
    assert op.op_type == OpType.MODIFY, f"expected MODIFY, got {op.op_type}"
    assert op.target_node_id == "n1"
    assert any(m.startswith("color:") for m in op.modifiers), f"no color modifier: {op.modifiers}"
    assert op.confidence >= 0.7, f"confidence {op.confidence} below 0.7"
    assert op.source_stage == "rules"


async def test_that_hexagon_should_be_blue() -> None:
    """N1: 'that hexagon should be blue' → MODIFY the focused node."""
    candidates = [NodeRef(node_id="n1", shape=None, label="hexagon", is_focus=True)]
    op = await _classify(
        "that hexagon should be blue",
        focus="n1",
        candidates=candidates,
    )
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n1"
    assert any(m.startswith("color:") for m in op.modifiers)


async def test_indefinite_article_still_creates() -> None:
    """N1 non-regression: 'a hexagon' with no determiner still CREATEs (conf 0.85)."""
    candidates = [NodeRef(node_id="n1", shape=None, label="hexagon")]
    op = await _classify("a hexagon", candidates=candidates)
    assert op.op_type == OpType.CREATE, f"expected CREATE, got {op.op_type}"
    assert op.confidence == 0.85, f"expected conf 0.85, got {op.confidence}"


async def test_bare_hexagon_no_focus_creates() -> None:
    """'a hexagon' with no focus, no candidates → CREATE."""
    op = await _classify("a hexagon")
    assert op.op_type == OpType.CREATE


# ===========================================================================
# N4 — deterministic extrusion
# ===========================================================================

async def test_make_this_hexagon_3d_modifies_with_extruded_group() -> None:
    """N4: 'make this hexagon three dimensional' with hexagon focus → MODIFY,
    geometry = extruded group with ≥ 3 face-* parts, conf 0.8, source rules."""
    candidates = [NodeRef(node_id="n1", shape=None, label="hexagon", is_focus=True)]
    op = await _classify(
        "make this hexagon three dimensional",
        focus="n1",
        candidates=candidates,
        focus_geometry=_hexagon_geom(),
    )
    assert op.op_type == OpType.MODIFY, f"expected MODIFY, got {op.op_type}"
    assert op.target_node_id == "n1"
    assert op.geometry is not None, "geometry must be set for extruded result"
    assert op.geometry.kind == ShapeKind.GROUP, "extruded result must be GROUP"
    face_parts = [p for p in op.geometry.parts if p.name and p.name.startswith("face-")]
    assert len(face_parts) >= 3, f"expected ≥3 face-* parts, got {len(face_parts)}"
    assert op.confidence == 0.8, f"expected conf 0.8, got {op.confidence}"
    assert op.source_stage == "rules"


async def test_make_it_3d_with_focus_polygon() -> None:
    """N4: 'make it 3d' with focus polygon → MODIFY, extruded group, conf 0.8."""
    # Use a simple rectangle as focus geometry.
    rect_geom = GeometrySpec(kind=ShapeKind.RECTANGLE, x=50.0, y=50.0, width=40.0, height=30.0)
    op = await _classify(
        "make it 3d",
        focus="n1",
        focus_geometry=rect_geom,
    )
    assert op.op_type == OpType.MODIFY
    assert op.geometry is not None
    assert op.geometry.kind == ShapeKind.GROUP
    assert op.confidence == 0.8


async def test_a_3d_hexagon_no_focus_creates_extruded() -> None:
    """N4: 'a 3D hexagon' with no focus → CREATE with extruded group, conf 0.8."""
    op = await _classify("a 3D hexagon")
    assert op.op_type == OpType.CREATE, f"expected CREATE, got {op.op_type}"
    assert op.geometry is not None
    assert op.geometry.kind == ShapeKind.GROUP
    face_parts = [p for p in op.geometry.parts if p.name and p.name.startswith("face-")]
    assert len(face_parts) >= 3, f"expected ≥3 face-* parts, got {len(face_parts)}"
    assert op.confidence == 0.8, f"expected conf 0.8, got {op.confidence}"


async def test_a_3d_cube_still_hazy_template_path() -> None:
    """N4 non-regression: 'a 3D cube' rules op confidence must be below the
    cascade threshold (0.55) — 'cube' is not in _SHAPE_WORDS or NAMED_SHAPES,
    so the template path wins downstream (test_d1_routing pins this in detail).
    The N4 CREATE freebie must NOT fire for 'cube' because it is not in those
    tables; the rules stage must stay at its original hazy/NOOP confidence."""
    op = await _classify("a 3D cube")
    # Rules stage must be below threshold so template can answer.
    assert op.confidence < 0.55, (
        f"'a 3D cube' rules op confidence {op.confidence} >= 0.55; "
        "would block template escalation and kill the isometric cuboid path"
    )


async def test_extrude_verb_triggers_3d_routing() -> None:
    """N4: the verb 'extrude' is treated as 3D intent ('extrude this')."""
    rect_geom = GeometrySpec(kind=ShapeKind.RECTANGLE, x=50.0, y=50.0, width=40.0, height=30.0)
    op = await _classify(
        "extrude this",
        focus="n1",
        focus_geometry=rect_geom,
    )
    assert op.op_type == OpType.MODIFY
    assert op.geometry is not None and op.geometry.kind == ShapeKind.GROUP
    assert op.confidence == 0.8


# ===========================================================================
# N2 — part-scoped edits
# ===========================================================================

async def test_make_left_eye_bigger_resolves_part() -> None:
    """N2: 'make the left eye bigger' with mouse focus → MODIFY, only eye-left
    changed in geometry, conf 0.75."""
    mouse = _mouse_group()
    eye_left_before = next(p for p in mouse.parts if p.name == "eye-left")
    op = await _classify(
        "make the left eye bigger",
        focus="n1",
        focus_geometry=mouse,
    )
    assert op.op_type == OpType.MODIFY, f"expected MODIFY, got {op.op_type}"
    assert op.target_node_id == "n1"
    assert op.geometry is not None, "geometry must be set for part edit"
    # The geometry is a patched group; eye-left must be bigger.
    eye_left_after = next(p for p in op.geometry.parts if p.name == "eye-left")
    eye_right_after = next(p for p in op.geometry.parts if p.name == "eye-right")
    # After "bigger" the part should be larger (area proxy: width*height).
    assert eye_left_after.width > eye_left_before.width, (
        "eye-left should have grown"
    )
    # eye-right must be unchanged (part isolation).
    eye_right_before = next(p for p in mouse.parts if p.name == "eye-right")
    assert eye_right_after.width == eye_right_before.width, (
        "eye-right must not change when only eye-left is targeted"
    )
    assert op.confidence == 0.75, f"expected conf 0.75, got {op.confidence}"


async def test_turn_the_eyes_red_recolors_both() -> None:
    """N2: 'turn the eyes red' → both eyes recolored, body untouched."""
    mouse = _mouse_group()
    body_before = next(p for p in mouse.parts if p.name == "body")
    op = await _classify(
        "turn the eyes red",
        focus="n1",
        focus_geometry=mouse,
    )
    assert op.op_type == OpType.MODIFY
    assert op.geometry is not None
    assert op.confidence == 0.75
    # Both eyes must have the red color in their stroke or fill.
    eye_left_after = next(p for p in op.geometry.parts if p.name == "eye-left")
    eye_right_after = next(p for p in op.geometry.parts if p.name == "eye-right")
    assert "#dc2626" in (eye_left_after.stroke or ""), (
        f"eye-left stroke not red: {eye_left_after.stroke}"
    )
    assert "#dc2626" in (eye_right_after.stroke or ""), (
        f"eye-right stroke not red: {eye_right_after.stroke}"
    )
    # Body must be untouched.
    body_after = next(p for p in op.geometry.parts if p.name == "body")
    assert body_after == body_before, "body must not be changed"


async def test_make_left_eye_bigger_no_part_match_is_noop() -> None:
    """N2 fallback inversion: 'make the left eye bigger' when focus group has NO
    eye part → rules op is NOOP conf 0.5 (escalates; dead LLM does nothing)."""
    no_eyes = _mouse_no_eyes()
    op = await _classify(
        "make the left eye bigger",
        focus="n1",
        focus_geometry=no_eyes,
    )
    assert op.op_type == OpType.NOOP, (
        f"expected NOOP for unresolvable part ref, got {op.op_type}"
    )
    assert op.confidence == _HAZY_CONFIDENCE, (
        f"expected conf {_HAZY_CONFIDENCE} to trigger cascade escalation, got {op.confidence}"
    )


async def test_make_left_eye_bigger_no_part_match_no_focus_geometry_is_noop() -> None:
    """N2 fallback inversion applies even without focus_geometry: unresolvable
    ref 'the left eye' when no geometry to check → NOOP not whole-scene MODIFY."""
    op = await _classify(
        "make the left eye bigger",
        focus="n1",
        focus_geometry=None,
    )
    # No geometry to check parts, but "the left eye" is an unresolvable ref.
    assert op.op_type == OpType.NOOP, (
        f"expected NOOP for unresolvable part ref (no geometry), got {op.op_type}"
    )


async def test_make_it_bigger_stays_fast_whole_scene_modify() -> None:
    """N2 non-regression: 'make it bigger' has no determiner+unexplained ref →
    still fast conf 0.7 MODIFY (not NOOP)."""
    op = await _classify("make it bigger", focus="n1")
    assert op.op_type == OpType.MODIFY, f"expected MODIFY, got {op.op_type}"
    assert op.confidence == 0.7, f"expected conf 0.7, got {op.confidence}"


async def test_part_scoped_modify_through_engine_touches_only_target() -> None:
    """Classifier+engine integration: modifiers are baked into the emitted
    geometry, so the engine must not fold them again (live bug: 'make one eye
    bigger' grew the WHOLE mouse x1.3 and the eye x1.69 via the double-fold)."""
    from quorum.domain.geometry import GeometrySpec, ShapeKind
    from quorum.engine import DesignStateEngine

    eng = DesignStateEngine(room="t")
    scene = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(kind=ShapeKind.PATH, name="body", x=40, y=55, width=42, height=34,
                         d="M 20 40 L 60 40 L 60 70 L 20 70 Z"),
            GeometrySpec(kind=ShapeKind.CIRCLE, name="eye-left", x=31, y=40, width=4, height=4),
            GeometrySpec(kind=ShapeKind.CIRCLE, name="eye-right", x=40, y=40, width=4, height=4),
        ],
    )
    eng.apply(DesignOp(op_type=OpType.CREATE, geometry=scene, label="mouse",
                       speaker_id="p", utterance_id="u0", confidence=1.0))
    clf = RulesClassifier()
    op = await clf.classify(
        "make one eye bigger than the other",
        speaker_id="p", utterance_id="u1", context=eng.classifier_context(),
    )
    assert op.op_type is OpType.MODIFY and op.modifiers == []
    diff = eng.apply(op)
    child = next(v for v in diff.upserted if v.id == diff.focus_node_id)
    by_name = {p.name: p for p in child.geometry.parts}
    assert by_name["eye-left"].width > 4.0          # the target grew
    assert by_name["eye-right"].width == 4.0        # sibling untouched
    assert by_name["body"].width == 42.0            # scene untouched
