"""R3 label resolution tests.

Pins the two live failures described in plan.md §12:

1. "i want the cube to be red" with a focused node labelled "cuboid" must
   resolve to a clean MODIFY (conf ≥ 0.7) via label matching — zero LLM.

2. "make the cat orange" with a candidate node labelled "cat" (not focus)
   must target that cat node (conf ≥ 0.7).

Also pins non-regression cases:
- "add a red sphere inside" with focus → still hazy (≤ 0.5), _EXTEND_RE wins.
- "make it bigger" with focus → still conf 0.7 fast-path MODIFY.
- label resolution prefers ShapeKind match when both could match.
- TemplateClassifier stamps label on CREATE ops (R3).
"""

from __future__ import annotations

from quorum.domain.geometry import ShapeKind
from quorum.domain.op import ClassifierContext, NodeRef, OpType
from quorum.pipeline.classify import RulesClassifier
from quorum.pipeline.templates import TemplateClassifier

_CLF = RulesClassifier()


async def _clf(
    text: str,
    focus: str | None = None,
    candidates: list[NodeRef] | None = None,
    focus_geometry: object = None,
) -> object:
    ctx = ClassifierContext(
        focus_node_id=focus,
        candidates=candidates or [],
        focus_geometry=focus_geometry,
    )
    return await _CLF.classify(text, speaker_id="alice", utterance_id="u1", context=ctx)


# ---------------------------------------------------------------------------
# Core label-resolution cases
# ---------------------------------------------------------------------------

async def test_cube_reference_resolves_cuboid_label() -> None:
    """'i want the cube to be red' → MODIFY, target = cuboid node, red color."""
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.GROUP, label="cuboid", is_focus=True),
    ]
    op = await _clf("i want the cube to be red", focus="n1", candidates=candidates)
    assert op.op_type == OpType.MODIFY, f"expected MODIFY, got {op.op_type}"  # type: ignore[attr-defined]
    assert op.target_node_id == "n1"  # type: ignore[attr-defined]
    assert any(m.startswith("color:") for m in op.modifiers), f"no color modifier in {op.modifiers}"  # type: ignore[attr-defined]
    assert op.confidence >= 0.7, f"confidence {op.confidence} below 0.7"  # type: ignore[attr-defined]
    assert op.source_stage == "rules"  # type: ignore[attr-defined]


async def test_cube_resolves_specifically_to_dc2626() -> None:
    """The color modifier must be #dc2626 (red)."""
    candidates = [NodeRef(node_id="n1", shape=ShapeKind.GROUP, label="cuboid", is_focus=True)]
    op = await _clf("i want the cube to be red", focus="n1", candidates=candidates)
    assert "color:#dc2626" in op.modifiers  # type: ignore[attr-defined]


async def test_cat_label_resolves_non_focus_candidate() -> None:
    """'make the cat orange' must target the cat node even though it's not focus."""
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.GROUP, label="cuboid", is_focus=True),
        NodeRef(node_id="n2", shape=ShapeKind.GROUP, label="cat"),
    ]
    op = await _clf("make the cat orange", focus="n1", candidates=candidates)
    assert op.op_type == OpType.MODIFY  # type: ignore[attr-defined]
    assert op.target_node_id == "n2", f"expected n2 (cat), got {op.target_node_id}"  # type: ignore[attr-defined]
    assert op.confidence >= 0.7  # type: ignore[attr-defined]
    assert any(m.startswith("color:") for m in op.modifiers)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Non-regression: existing fast paths must not break
# ---------------------------------------------------------------------------

async def test_extend_intent_stays_hazy_with_focus() -> None:
    """'add a red sphere inside' with focus → hazy (≤ 0.5). _EXTEND_RE must win."""
    candidates = [NodeRef(node_id="n1", shape=ShapeKind.GROUP, label="cuboid", is_focus=True)]
    op = await _clf("add a red sphere inside", focus="n1", candidates=candidates)
    assert op.confidence <= 0.5, f"expected hazy (≤ 0.5), got {op.confidence}"  # type: ignore[attr-defined]


async def test_make_it_bigger_stays_fast_path() -> None:
    """'make it bigger' with focus → MODIFY, conf 0.7 (no label needed)."""
    op = await _clf("make it bigger", focus="n1")
    assert op.op_type == OpType.MODIFY  # type: ignore[attr-defined]
    assert op.confidence == 0.7  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Label match rules
# ---------------------------------------------------------------------------

async def test_exact_label_match() -> None:
    """Exact match: 'the cat' → node labelled 'cat'."""
    candidates = [NodeRef(node_id="n1", shape=None, label="cat")]
    op = await _clf("make the cat bigger", candidates=candidates)
    assert op.op_type == OpType.MODIFY  # type: ignore[attr-defined]
    assert op.target_node_id == "n1"  # type: ignore[attr-defined]


async def test_plural_label_match() -> None:
    """Plural: 'the cats' → node labelled 'cat'."""
    candidates = [NodeRef(node_id="n1", shape=None, label="cat")]
    op = await _clf("make the cats bigger", candidates=candidates)
    assert op.op_type == OpType.MODIFY  # type: ignore[attr-defined]
    assert op.target_node_id == "n1"  # type: ignore[attr-defined]


async def test_prefix_label_match_cube_cuboid() -> None:
    """Prefix: 'cube' matches label 'cuboid' via common 4-char prefix."""
    candidates = [NodeRef(node_id="n1", shape=ShapeKind.GROUP, label="cuboid")]
    op = await _clf("make the cube red", candidates=candidates)
    assert op.op_type == OpType.MODIFY  # type: ignore[attr-defined]
    assert op.target_node_id == "n1"  # type: ignore[attr-defined]


async def test_shapekind_preferred_over_label() -> None:
    """When both ShapeKind match and label match are available, ShapeKind wins.

    'make the circle bigger': there's a CIRCLE node (ShapeKind) AND a node
    with label 'circle'. The ShapeKind resolution goes first in branch 4.
    """
    candidates = [
        NodeRef(node_id="shapekind_node", shape=ShapeKind.CIRCLE, label=None),
        NodeRef(node_id="label_node", shape=ShapeKind.RECTANGLE, label="circle"),
    ]
    op = await _clf("make the circle bigger", candidates=candidates)
    assert op.op_type == OpType.MODIFY  # type: ignore[attr-defined]
    # ShapeKind match should win (it's tried first)
    assert op.target_node_id == "shapekind_node"  # type: ignore[attr-defined]


async def test_newest_candidate_wins() -> None:
    """When multiple nodes share the same label, the newest (last) wins."""
    candidates = [
        NodeRef(node_id="n1", shape=None, label="cat"),
        NodeRef(node_id="n2", shape=None, label="cat"),
    ]
    op = await _clf("make the cat bigger", candidates=candidates)
    assert op.op_type == OpType.MODIFY  # type: ignore[attr-defined]
    assert op.target_node_id == "n2"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Branch 1 (preference/FOCUS) label fallback
# ---------------------------------------------------------------------------

async def test_focus_phrase_resolves_by_label() -> None:
    """'let's go with the cat' where 'cat' is a label (no ShapeKind entry)."""
    candidates = [
        NodeRef(node_id="n1", shape=ShapeKind.GROUP, label="cuboid", is_focus=True),
        NodeRef(node_id="n2", shape=ShapeKind.GROUP, label="cat"),
    ]
    op = await _clf("let's go with the cat", focus="n1", candidates=candidates)
    assert op.op_type == OpType.FOCUS  # type: ignore[attr-defined]
    assert op.target_node_id == "n2"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TemplateClassifier stamps label (R3)
# ---------------------------------------------------------------------------

async def test_template_classifier_stamps_label() -> None:
    """A direct template hit must stamp label=<canonical name>."""
    from quorum.domain.op import ClassifierContext

    ctx = ClassifierContext()
    tc = TemplateClassifier()
    op = await tc.classify("draw a snowman", speaker_id="a", utterance_id="u1", context=ctx)
    assert op.op_type == OpType.CREATE
    assert op.label == "snowman"


async def test_template_cuboid_stamps_label() -> None:
    """Isometric cuboid template hit stamps label='cuboid'."""
    from quorum.domain.op import ClassifierContext

    ctx = ClassifierContext()
    tc = TemplateClassifier()
    op = await tc.classify("a 3d box", speaker_id="a", utterance_id="u1", context=ctx)
    assert op.op_type == OpType.CREATE
    assert op.label == "cuboid"


# ---------------------------------------------------------------------------
# R3: rules CREATE ops stamp label
# ---------------------------------------------------------------------------

async def test_rules_create_stamps_label() -> None:
    """A rules-path shape CREATE must stamp label = the matched word."""
    op = await _clf("a triangle")
    assert op.op_type == OpType.CREATE  # type: ignore[attr-defined]
    assert op.label == "triangle"  # type: ignore[attr-defined]


async def test_rules_create_rectangle_stamps_label() -> None:
    op = await _clf("draw a rectangle")
    assert op.op_type == OpType.CREATE  # type: ignore[attr-defined]
    assert op.label == "rectangle"  # type: ignore[attr-defined]
