"""Rules-classifier (cascade stage A) unit tests.

The rules stage must catch the obvious majority cheaply (plan.md §3.3): shape
words, preference phrases, bare modifiers. Anything it can't handle returns NOOP
(Phase 4 escalates those to the LLM behind the same Protocol).
"""

from __future__ import annotations

import pytest

from quorum.domain.geometry import ShapeKind
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
