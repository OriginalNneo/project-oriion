"""Rules-classifier (cascade stage A) unit tests.

The rules stage must catch the obvious majority cheaply (plan.md §3.3): shape
words, preference phrases, bare modifiers. Anything it can't handle returns NOOP
(Phase 4 escalates those to the LLM behind the same Protocol).
"""

from __future__ import annotations

import pytest

from quorum.domain.geometry import ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, NodeRef, OpType
from quorum.pipeline.classify import MockClassifier


@pytest.fixture
def clf() -> MockClassifier:
    return MockClassifier()


async def _classify(
    clf: MockClassifier,
    text: str,
    focus: str | None = None,
    candidates: list[NodeRef] | None = None,
) -> DesignOp:
    ctx = ClassifierContext(focus_node_id=focus, candidates=candidates or [])
    return await clf.classify(text, speaker_id="alice", utterance_id="u1", context=ctx)


async def test_shape_word_creates(clf: MockClassifier) -> None:
    op = await _classify(clf, "let's draw a rectangle")
    assert op.op_type == OpType.CREATE
    assert op.target_shape is not None and op.target_shape.value == "rectangle"


async def test_fillet_modifier_attaches(clf: MockClassifier) -> None:
    op = await _classify(clf, "a rectangle with a fillet")
    assert "fillet" in op.modifiers
    assert op.geometry is not None and op.geometry.corner_radius > 0


async def test_branch_hint_branches_from_focus(clf: MockClassifier) -> None:
    op = await _classify(clf, "how about a triangle instead", focus="n1")
    assert op.op_type == OpType.BRANCH
    assert op.target_node_id == "n1"


async def test_preference_phrase_focuses(clf: MockClassifier) -> None:
    op = await _classify(clf, "let's go with the triangle", focus="n2")
    assert op.op_type == OpType.FOCUS
    assert op.preference_signal >= 0.9


async def test_named_preference_resolves_to_that_node(clf: MockClassifier) -> None:
    # "go with the triangle" must focus the triangle node, not the current focus.
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.RECTANGLE, is_focus=True),
        NodeRef(node_id="n2", shape=ShapeKind.TRIANGLE),
    ]
    op = await _classify(clf, "let's go with the triangle", focus="n1", candidates=candidates)
    assert op.op_type == OpType.FOCUS
    assert op.target_node_id == "n2"  # resolved by name, not the current focus


async def test_bare_preference_reaffirms_focus(clf: MockClassifier) -> None:
    # No shape named -> re-affirm whatever is currently focused.
    op = await _classify(clf, "yeah i prefer that", focus="n5")
    assert op.op_type == OpType.FOCUS
    assert op.target_node_id == "n5"


async def test_weak_preference_is_weaker(clf: MockClassifier) -> None:
    strong = await _classify(clf, "let's go with the triangle", focus="n1")
    weak = await _classify(clf, "maybe the triangle", focus="n1")
    assert weak.preference_signal < strong.preference_signal


async def test_bare_modifier_modifies_focus(clf: MockClassifier) -> None:
    op = await _classify(clf, "make it bigger", focus="n1")
    assert op.op_type == OpType.MODIFY
    assert "bigger" in op.modifiers


async def test_unknown_is_noop(clf: MockClassifier) -> None:
    op = await _classify(clf, "what time is lunch")
    assert op.op_type == OpType.NOOP
    assert op.confidence < 0.5


async def test_radius_extracted(clf: MockClassifier) -> None:
    op = await _classify(clf, "a box with radius 8")
    assert any(m.startswith("radius:8") for m in op.modifiers)
