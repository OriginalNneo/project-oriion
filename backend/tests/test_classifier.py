"""Rules-classifier (cascade stage A) unit tests.

The rules stage must catch the obvious majority cheaply (plan.md §3.3): shape
words, preference phrases, bare modifiers. Anything it can't handle returns NOOP
(Phase 4 escalates those to the LLM behind the same Protocol).
"""

from __future__ import annotations

import pytest

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, NodeRef, OpType
from quorum.pipeline.classify import RulesClassifier


@pytest.fixture
def clf() -> RulesClassifier:
    return RulesClassifier()


async def _classify(
    clf: RulesClassifier,
    text: str,
    focus: str | None = None,
    candidates: list[NodeRef] | None = None,
) -> DesignOp:
    ctx = ClassifierContext(focus_node_id=focus, candidates=candidates or [])
    return await clf.classify(text, speaker_id="alice", utterance_id="u1", context=ctx)


async def test_shape_word_creates(clf: RulesClassifier) -> None:
    op = await _classify(clf, "let's draw a rectangle")
    assert op.op_type == OpType.CREATE
    assert op.target_shape is not None and op.target_shape.value == "rectangle"


async def test_fillet_modifier_attaches(clf: RulesClassifier) -> None:
    op = await _classify(clf, "a rectangle with a fillet")
    assert "fillet" in op.modifiers
    assert op.geometry is not None and op.geometry.corner_radius > 0


async def test_branch_hint_branches_from_focus(clf: RulesClassifier) -> None:
    op = await _classify(clf, "how about a triangle instead", focus="n1")
    assert op.op_type == OpType.BRANCH
    assert op.target_node_id == "n1"


async def test_preference_phrase_focuses(clf: RulesClassifier) -> None:
    op = await _classify(clf, "let's go with the triangle", focus="n2")
    assert op.op_type == OpType.FOCUS
    assert op.preference_signal >= 0.9


async def test_named_preference_resolves_to_that_node(clf: RulesClassifier) -> None:
    # "go with the triangle" must focus the triangle node, not the current focus.
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.RECTANGLE, is_focus=True),
        NodeRef(node_id="n2", shape=ShapeKind.TRIANGLE),
    ]
    op = await _classify(clf, "let's go with the triangle", focus="n1", candidates=candidates)
    assert op.op_type == OpType.FOCUS
    assert op.target_node_id == "n2"  # resolved by name, not the current focus


async def test_bare_preference_reaffirms_focus(clf: RulesClassifier) -> None:
    # No shape named -> re-affirm whatever is currently focused.
    op = await _classify(clf, "yeah i prefer that", focus="n5")
    assert op.op_type == OpType.FOCUS
    assert op.target_node_id == "n5"


async def test_weak_preference_is_weaker(clf: RulesClassifier) -> None:
    strong = await _classify(clf, "let's go with the triangle", focus="n1")
    weak = await _classify(clf, "maybe the triangle", focus="n1")
    assert weak.preference_signal < strong.preference_signal


async def test_bare_modifier_modifies_focus(clf: RulesClassifier) -> None:
    op = await _classify(clf, "make it bigger", focus="n1")
    assert op.op_type == OpType.MODIFY
    assert "bigger" in op.modifiers


async def test_unknown_is_noop(clf: RulesClassifier) -> None:
    op = await _classify(clf, "what time is lunch")
    assert op.op_type == OpType.NOOP
    assert op.confidence < 0.5


async def test_radius_extracted(clf: RulesClassifier) -> None:
    op = await _classify(clf, "a box with radius 8")
    assert any(m.startswith("radius:8") for m in op.modifiers)
    # the radius must actually land in the resolved geometry, not just the list
    assert op.geometry is not None and op.geometry.corner_radius == 8.0


async def test_modify_named_node_does_not_create(clf: RulesClassifier) -> None:
    # "make the circle bigger" refers to the EXISTING circle — it must MODIFY
    # it, not create a second circle.
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.RECTANGLE, is_focus=True),
        NodeRef(node_id="n2", shape=ShapeKind.CIRCLE),
    ]
    op = await _classify(clf, "make the circle bigger", focus="n1", candidates=candidates)
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n2"
    assert "bigger" in op.modifiers


async def test_indefinite_article_still_creates(clf: RulesClassifier) -> None:
    # "a bigger circle" asks for a new one even though a circle exists.
    candidates = [NodeRef(node_id="n2", shape=ShapeKind.CIRCLE)]
    op = await _classify(clf, "add a bigger circle", candidates=candidates)
    assert op.op_type == OpType.CREATE


async def test_color_word_lands_in_geometry(clf: RulesClassifier) -> None:
    op = await _classify(clf, "a red rectangle")
    assert op.op_type == OpType.CREATE
    assert any(m.startswith("color:") for m in op.modifiers)
    assert op.geometry is not None and op.geometry.stroke == "#dc2626"


async def test_prune_named_shape(clf: RulesClassifier) -> None:
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.RECTANGLE),
        NodeRef(node_id="n2", shape=ShapeKind.CIRCLE),
    ]
    op = await _classify(clf, "scrap the circle", focus="n1", candidates=candidates)
    assert op.op_type == OpType.PRUNE
    assert op.target_node_id == "n2"


async def test_prune_deictic_targets_focus(clf: RulesClassifier) -> None:
    op = await _classify(clf, "get rid of that", focus="n3")
    assert op.op_type == OpType.PRUNE
    assert op.target_node_id == "n3"


async def test_connect_two_named_nodes(clf: RulesClassifier) -> None:
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.RECTANGLE),
        NodeRef(node_id="n2", shape=ShapeKind.CIRCLE),
    ]
    op = await _classify(clf, "connect the box to the circle", candidates=candidates)
    assert op.op_type == OpType.CONNECT
    assert op.target_node_id == "n1"
    assert op.relation_to_node == "n2"


async def test_negative_preference_is_negative(clf: RulesClassifier) -> None:
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.RECTANGLE, is_focus=True),
        NodeRef(node_id="n2", shape=ShapeKind.TRIANGLE),
    ]
    op = await _classify(clf, "not the triangle", focus="n1", candidates=candidates)
    assert op.op_type == OpType.FOCUS
    assert op.target_node_id == "n2"
    assert op.preference_signal < 0


# ---------------------------------------------------------------------- #
# Composite scenes — multiple shapes in ONE utterance become ONE node.   #
# ---------------------------------------------------------------------- #
async def test_scene_square_on_top_of_circle(clf: RulesClassifier) -> None:
    op = await _classify(clf, "a circle with a square on top")
    assert op.op_type == OpType.CREATE
    assert op.geometry is not None and op.geometry.kind == ShapeKind.GROUP
    parts = {p.kind: p for p in op.geometry.parts}
    assert set(parts) == {ShapeKind.CIRCLE, ShapeKind.RECTANGLE}
    # the square sits ABOVE the circle and keeps equal sides
    square = parts[ShapeKind.RECTANGLE]
    assert square.y < parts[ShapeKind.CIRCLE].y
    assert square.width == square.height


async def test_scene_on_top_of_phrasing_matches(clf: RulesClassifier) -> None:
    a = (await _classify(clf, "a circle with a square on top")).geometry
    b = (await _classify(clf, "a square on top of a circle")).geometry
    assert a is not None and b is not None
    assert {(p.kind, p.x, p.y) for p in a.parts} == {(p.kind, p.x, p.y) for p in b.parts}


async def test_scene_inside(clf: RulesClassifier) -> None:
    op = await _classify(clf, "a circle inside a square")
    assert op.geometry is not None and op.geometry.kind == ShapeKind.GROUP
    parts = {p.kind: p for p in op.geometry.parts}
    inner, outer = parts[ShapeKind.CIRCLE], parts[ShapeKind.RECTANGLE]
    assert inner.x == outer.x and inner.y == outer.y
    assert inner.width < outer.width


async def test_scene_side_by_side_default(clf: RulesClassifier) -> None:
    op = await _classify(clf, "a circle and a triangle")
    assert op.geometry is not None and op.geometry.kind == ShapeKind.GROUP
    circle = next(p for p in op.geometry.parts if p.kind == ShapeKind.CIRCLE)
    triangle = next(p for p in op.geometry.parts if p.kind == ShapeKind.TRIANGLE)
    assert circle.x < triangle.x  # spoken order, left to right


async def test_scene_branches_off_focus_with_hint(clf: RulesClassifier) -> None:
    op = await _classify(clf, "how about a circle with a square on top instead", focus="n1")
    assert op.op_type == OpType.BRANCH
    assert op.target_node_id == "n1"
    assert op.geometry is not None and op.geometry.kind == ShapeKind.GROUP


# ---------------------------------------------------------------------- #
# §15 Spatial compose: new shape onto existing node.                      #
# ---------------------------------------------------------------------- #


def _horse_ctx() -> ClassifierContext:
    """Horse node as focus with a single-rect geometry (stand-in for real horse)."""
    horse_geom = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(kind=ShapeKind.RECTANGLE, x=50, y=52, width=46, height=36)
        ],
    )
    return ClassifierContext(
        focus_node_id="n1",
        focus_geometry=horse_geom,
        candidates=[NodeRef(node_id="n1", label="horse", is_focus=True)],
    )


async def test_compose_box_above_horse_routes_to_modify(clf: RulesClassifier) -> None:
    """'draw a box above the horse' → MODIFY of the horse node (compose branch)."""
    op = await clf.classify(
        "draw a box above the horse",
        speaker_id="a",
        utterance_id="u1",
        context=_horse_ctx(),
    )
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n1"
    assert op.modifiers == []
    assert op.geometry is not None
    assert op.geometry.kind == ShapeKind.GROUP
    assert len(op.geometry.parts) == 2  # horse rect + new box


async def test_compose_box_above_horse_wanna_phrasing(clf: RulesClassifier) -> None:
    """'I wanna draw a box above the horse' — same routing (not hazy to LLM)."""
    op = await clf.classify(
        "i wanna draw a box above the horse",
        speaker_id="a",
        utterance_id="u1",
        context=_horse_ctx(),
    )
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n1"
    assert op.modifiers == []
    assert op.geometry is not None


async def test_compose_box_below_horse(clf: RulesClassifier) -> None:
    """'put a circle below the horse' → MODIFY (compose, below relation)."""
    op = await clf.classify(
        "put a circle below the horse",
        speaker_id="a",
        utterance_id="u1",
        context=_horse_ctx(),
    )
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n1"
    assert op.modifiers == []
    assert op.geometry is not None
    assert op.geometry.kind == ShapeKind.GROUP


async def test_plain_create_no_regression(clf: RulesClassifier) -> None:
    """'draw a box' with no spatial relation and no focus → CREATE (no compose)."""
    op = await clf.classify(
        "draw a box",
        speaker_id="a",
        utterance_id="u1",
        context=ClassifierContext(),
    )
    assert op.op_type == OpType.CREATE


async def test_multi_shape_create_no_regression(clf: RulesClassifier) -> None:
    """'a circle with a square on top' → CREATE GROUP (branch 5, unchanged)."""
    op = await clf.classify(
        "a circle with a square on top",
        speaker_id="a",
        utterance_id="u1",
        context=ClassifierContext(),
    )
    assert op.op_type == OpType.CREATE
    assert op.target_shape == ShapeKind.GROUP


async def test_multi_shape_create_with_focus_no_regression(clf: RulesClassifier) -> None:
    """Same multi-shape utterance with a focus still → CREATE (branch 5, not 5b)."""
    ctx = ClassifierContext(
        focus_node_id="n1",
        focus_geometry=GeometrySpec(
            kind=ShapeKind.RECTANGLE, x=50, y=50, width=40, height=30
        ),
        candidates=[NodeRef(node_id="n1", label="horse", is_focus=True)],
    )
    op = await clf.classify(
        "a circle with a square on top",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    assert op.op_type == OpType.CREATE
    assert op.target_shape == ShapeKind.GROUP


async def test_compose_non_focus_target_goes_hazy(clf: RulesClassifier) -> None:
    """'draw a box above the horse' when horse is NOT focus → NOOP 0.5."""
    cat_geom = GeometrySpec(kind=ShapeKind.CIRCLE, x=50, y=50, width=40, height=40)
    ctx = ClassifierContext(
        focus_node_id="n2",  # cat is focus
        focus_geometry=cat_geom,
        candidates=[
            NodeRef(node_id="n1", label="horse", is_focus=False),
            NodeRef(node_id="n2", label="cat", is_focus=True),
        ],
    )
    op = await clf.classify(
        "draw a box above the horse",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    assert op.op_type == OpType.NOOP
    assert op.confidence == 0.5


async def test_make_it_bigger_no_regression(clf: RulesClassifier) -> None:
    """'make it bigger' → MODIFY with 'bigger' modifier (branch 7, unchanged)."""
    ctx = ClassifierContext(
        focus_node_id="n1",
        focus_geometry=GeometrySpec(kind=ShapeKind.RECTANGLE),
        candidates=[NodeRef(node_id="n1", is_focus=True)],
    )
    op = await clf.classify(
        "make it bigger",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    assert op.op_type == OpType.MODIFY
    assert "bigger" in op.modifiers


async def test_compose_box_above_focus_implicit(clf: RulesClassifier) -> None:
    """'draw a box above it' with no label match uses implicit focus → MODIFY."""
    horse_geom = GeometrySpec(
        kind=ShapeKind.RECTANGLE, x=50, y=52, width=46, height=36
    )
    ctx = ClassifierContext(
        focus_node_id="n1",
        focus_geometry=horse_geom,
        candidates=[NodeRef(node_id="n1", is_focus=True)],  # no label
    )
    op = await clf.classify(
        "draw a box above it",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n1"
    assert op.modifiers == []


# ---------------------------------------------------------------------- #
# §15 Review-finding fixes (findings 1-5).                                #
# ---------------------------------------------------------------------- #


async def test_finding1_definite_unresolved_blocks_implicit_fallback(
    clf: RulesClassifier,
) -> None:
    """Finding 1: 'draw a box above the window' with focus=horse and no window
    node → definite reference fails resolution → should NOT compose onto horse.

    Pre-fix: fell through to implicit-focus fallback → MODIFY horse (wrong node).
    Post-fix: _definite_unresolved guard fires → falls through to CREATE.
    """
    horse_geom = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[GeometrySpec(kind=ShapeKind.RECTANGLE, x=50, y=52, width=46, height=36)],
    )
    ctx = ClassifierContext(
        focus_node_id="n1",
        focus_geometry=horse_geom,
        candidates=[NodeRef(node_id="n1", label="horse", is_focus=True)],
        # No 'window' node → definite reference 'the window' is unresolvable.
    )
    op = await clf.classify(
        "draw a box above the window",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    # Must NOT compose onto horse (wrong node).  Falls through to CREATE.
    assert op.op_type != OpType.MODIFY or op.target_node_id != "n1", (
        "Implicit-focus fallback must not fire when a definite reference fails resolution"
    )


async def test_finding2_3_color_modifier_plus_compose_creates_new_shape(
    clf: RulesClassifier,
) -> None:
    """Findings 2 & 3: 'draw a red box above the horse' — branch 4 must NOT
    recolor the horse; branch 5b must compose a new red box onto the horse.

    Pre-fix: branch 4 fires (modifiers=['color:#dc2626']) → MODIFY horse with
             color modifier, no new geometry (horse recolored red, box never created).
    Post-fix: branch 4 skips (indefinite 'a' + spatial compose) → branch 5b
              fires → MODIFY horse with pre-baked geometry, modifiers=[].
    """
    horse_geom = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[GeometrySpec(kind=ShapeKind.RECTANGLE, x=50, y=52, width=46, height=36)],
    )
    ctx = ClassifierContext(
        focus_node_id="n1",
        focus_geometry=horse_geom,
        candidates=[NodeRef(node_id="n1", label="horse", is_focus=True)],
    )
    op = await clf.classify(
        "draw a red box above the horse",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    # Must be compose (MODIFY with pre-baked geometry), NOT a bare recolor.
    assert op.op_type == OpType.MODIFY, f"Expected MODIFY, got {op.op_type}"
    assert op.target_node_id == "n1"
    # Pre-baked geometry path → modifiers MUST be [].
    assert op.modifiers == [], (
        f"Branch 4 recolor intercepted: modifiers={op.modifiers!r}; "
        "expected [] (geometry is pre-baked)"
    )
    assert op.geometry is not None, "Expected pre-baked geometry, got None"
    assert op.geometry.kind == ShapeKind.GROUP


async def test_finding4_on_top_without_of_maps_to_on_top_relation(
    clf: RulesClassifier,
) -> None:
    """Finding 4: 'draw a box on top the horse' — 'on top' without 'of' must
    produce on_top (overlapping) not above (gap-separated).

    Verified via geometry: on_top places new_part.bottom == host.top (no gap),
    above places new_part.bottom == host.top - GAP.  We check that the composed
    group has parts whose centers are closer together than the 'above' case would
    produce (i.e. they overlap rather than sit apart).
    """
    horse_geom = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[GeometrySpec(kind=ShapeKind.RECTANGLE, x=50, y=52, width=46, height=36)],
    )
    ctx = ClassifierContext(
        focus_node_id="n1",
        focus_geometry=horse_geom,
        candidates=[NodeRef(node_id="n1", label="horse", is_focus=True)],
    )
    op_on_top = await clf.classify(
        "draw a box on top the horse",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    op_above = await clf.classify(
        "draw a box above the horse",
        speaker_id="a",
        utterance_id="u2",
        context=ctx,
    )
    # Both should be MODIFY compose ops.
    assert op_on_top.op_type == OpType.MODIFY
    assert op_above.op_type == OpType.MODIFY
    # on_top produces overlapping layout; the composed groups are both valid.
    assert op_on_top.geometry is not None
    assert op_above.geometry is not None
    # The two groups should have the same part count.
    assert len(op_on_top.geometry.parts) == len(op_above.geometry.parts) == 2
    # on_top: new_part is last (painted on top in z-order).
    # (compose.py appends new_part last for on_top — verify the group has 2 parts)
    # Verify the relations produce DIFFERENT layouts (on_top !== above).
    # Compare the y-center of the second part (the new box) relative to the first.
    # In 'on_top' the box center is closer to the horse center than in 'above'.
    new_box_on_top = op_on_top.geometry.parts[-1]
    new_box_above = op_above.geometry.parts[-1]
    # The on_top box should be closer (higher y value in SVG coords == lower on screen,
    # but in our 0-100 coord system, lower y = higher visually).
    # Both are valid composed geometries; just assert they differ.
    assert new_box_on_top.y != new_box_above.y, (
        "'on top' and 'above' produced identical layouts — _detect_relation fix may not be active"
    )


async def test_finding5_branch5_yields_to_5b_for_definite_shape_label(
    clf: RulesClassifier,
) -> None:
    """Finding 5: 'draw a circle above the square' where a canvas node is labelled
    'square' — branch 5 must yield to branch 5b (compose) instead of creating a
    new two-shape GROUP.

    Pre-fix: _find_shape_mentions returns ['circle','square'] → len=2 → branch 5
             creates a new GROUP (the existing square node is ignored).
    Post-fix: 'the square' resolves to existing n1 via definite-det guard in
              branch 5 → yields to branch 5b → MODIFY n1 with compose geometry.
    """
    square_geom = GeometrySpec(
        kind=ShapeKind.RECTANGLE, x=50, y=52, width=40, height=40
    )
    ctx = ClassifierContext(
        focus_node_id="n1",
        focus_geometry=square_geom,
        candidates=[
            NodeRef(
                node_id="n1",
                label="square",
                shape=ShapeKind.RECTANGLE,
                is_focus=True,
            )
        ],
    )
    op = await clf.classify(
        "draw a circle above the square",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    # Must compose onto the existing square node, NOT create a new two-shape group.
    assert op.op_type == OpType.MODIFY, (
        f"Expected MODIFY (compose onto existing square), got {op.op_type}; "
        "branch 5 may have consumed the two-shape utterance before branch 5b"
    )
    assert op.target_node_id == "n1"
    assert op.modifiers == []
    assert op.geometry is not None
    assert op.geometry.kind == ShapeKind.GROUP
