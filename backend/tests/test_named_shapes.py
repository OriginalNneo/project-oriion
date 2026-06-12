"""R4 named-geometry tier tests.

Pins that every named shape:
  - returns a valid, renderable GeometrySpec;
  - is reachable by both primary word and alias;
  - integrates with the RulesClassifier (CREATE op, label set, conf 0.85);
  - modifier folding (e.g. "a red hexagon") works correctly.

Named shapes must NOT push unrelated utterances over the hazy threshold
(they are registered in _KNOWN_WORDS).
"""

from __future__ import annotations

import pytest

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, NodeRef, OpType
from quorum.domain.shapes import NAMED_SHAPES, named_shape
from quorum.pipeline.classify import RulesClassifier
from quorum.pipeline.renderer import SvgRenderer

_CLF = RulesClassifier()
_CTX = ClassifierContext()
_RENDERER = SvgRenderer()


# ---------------------------------------------------------------------------
# domain/shapes.py unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word", list(NAMED_SHAPES))
def test_named_shape_returns_valid_spec(word: str) -> None:
    spec = named_shape(word)
    assert spec is not None, f"named_shape({word!r}) returned None"
    assert isinstance(spec, GeometrySpec)


@pytest.mark.parametrize("word", list(NAMED_SHAPES))
def test_named_shape_renders(word: str) -> None:
    spec = named_shape(word)
    assert spec is not None
    svg = _RENDERER.render(spec)
    assert svg.startswith("<svg"), f"word={word!r} did not render to SVG"


@pytest.mark.parametrize("word", list(NAMED_SHAPES))
def test_named_shape_points_in_box(word: str) -> None:
    spec = named_shape(word)
    assert spec is not None
    if spec.points is not None:
        for px, py in spec.points:
            assert 0.0 <= px <= 100.0, f"{word}: x={px} out of box"
            assert 0.0 <= py <= 100.0, f"{word}: y={py} out of box"


def test_diamond_is_alias_for_rhombus() -> None:
    r = named_shape("rhombus")
    d = named_shape("diamond")
    assert r is not None and d is not None
    assert r.kind == d.kind == ShapeKind.POLYGON


def test_trapezium_is_alias_for_trapezoid() -> None:
    a = named_shape("trapezoid")
    b = named_shape("trapezium")
    assert a is not None and b is not None
    assert a.kind == b.kind


def test_plus_is_alias_for_cross() -> None:
    a = named_shape("cross")
    b = named_shape("plus")
    assert a is not None and b is not None
    assert a.kind == b.kind


def test_semicircle_is_path() -> None:
    spec = named_shape("semicircle")
    assert spec is not None
    assert spec.kind == ShapeKind.PATH
    assert spec.d is not None


def test_heart_is_path() -> None:
    spec = named_shape("heart")
    assert spec is not None
    assert spec.kind == ShapeKind.PATH


def test_crescent_is_path() -> None:
    spec = named_shape("crescent")
    assert spec is not None
    assert spec.kind == ShapeKind.PATH


def test_star_has_ten_points() -> None:
    spec = named_shape("star")
    assert spec is not None
    assert spec.points is not None
    assert len(spec.points) == 10  # 5 outer + 5 inner


def test_unknown_word_returns_none() -> None:
    assert named_shape("foobar") is None
    assert named_shape("rectangle") is None  # ShapeKind shapes are NOT in NAMED_SHAPES


# ---------------------------------------------------------------------------
# classifier integration tests (R4)
# ---------------------------------------------------------------------------

async def _clf(
    text: str,
    focus: str | None = None,
    candidates: list[NodeRef] | None = None,
) -> object:
    ctx = ClassifierContext(focus_node_id=focus, candidates=candidates or [])
    return await _CLF.classify(text, speaker_id="alice", utterance_id="u1", context=ctx)


async def test_rhombus_creates_polygon() -> None:
    op = await _clf("a rhombus")
    assert op.op_type == OpType.CREATE  # type: ignore[attr-defined]
    assert op.confidence >= 0.85  # type: ignore[attr-defined]
    assert op.label == "rhombus"  # type: ignore[attr-defined]
    assert op.geometry is not None  # type: ignore[attr-defined]
    assert op.geometry.kind == ShapeKind.POLYGON  # type: ignore[attr-defined]
    assert op.source_stage == "rules"  # type: ignore[attr-defined]


async def test_red_hexagon_folds_color() -> None:
    op = await _clf("a red hexagon")
    assert op.op_type == OpType.CREATE  # type: ignore[attr-defined]
    assert any(m.startswith("color:") for m in op.modifiers)  # type: ignore[attr-defined]
    assert op.label == "hexagon"  # type: ignore[attr-defined]
    assert op.geometry is not None  # type: ignore[attr-defined]
    # color modifier should have been applied to geometry stroke
    assert op.geometry.stroke == "#dc2626"  # type: ignore[attr-defined]


async def test_named_shape_confidence_is_085() -> None:
    op = await _clf("draw a star")
    assert op.op_type == OpType.CREATE  # type: ignore[attr-defined]
    assert op.confidence == 0.85  # type: ignore[attr-defined]


async def test_named_shape_does_not_inflate_unrelated_hazy() -> None:
    """A named-shape word appearing in the known-words set must NOT push an
    unrelated utterance over the hazy threshold.

    "a hexagon and some arrows" — "hexagon" and "arrow" are known words (R4),
    "some" is a stopword, so the unexplained count stays low and the scene
    branch fires instead of going hazy.
    """
    op = await _clf("a hexagon and some arrows")
    # Should produce a CREATE (not hazy NOOP) and confidence >= 0.55
    assert op.op_type in (OpType.CREATE,)  # type: ignore[attr-defined]
    # at the very least it shouldn't be stuck at 0.5 hazy because of named words
    # (either the scene branch or named-shape branch fires at >= 0.75)
    assert op.confidence >= 0.75  # type: ignore[attr-defined]


async def test_named_shape_all_words_create() -> None:
    """Spot-check a selection of named shapes to ensure each produces a CREATE."""
    words = ["diamond", "parallelogram", "trapezoid", "pentagon", "octagon",
             "arrow", "cross", "semicircle", "kite", "heart", "crescent", "heptagon"]
    for word in words:
        op = await _clf(f"a {word}")
        assert op.op_type == OpType.CREATE, f"word={word!r} did not CREATE: {op}"  # type: ignore[attr-defined]
        assert op.label == word, f"word={word!r}: expected label {word!r}, got {op.label}"  # type: ignore[attr-defined]


async def test_named_shape_all_render() -> None:
    """Every named-shape CREATE must produce a geometry that renders to SVG."""
    renderer = SvgRenderer()
    for word in NAMED_SHAPES:
        op = await _clf(f"a {word}")
        assert op.geometry is not None, f"word={word!r}: geometry is None"  # type: ignore[attr-defined]
        svg = renderer.render(op.geometry)  # type: ignore[attr-defined]
        assert svg.startswith("<svg"), f"word={word!r}: renderer failed"
