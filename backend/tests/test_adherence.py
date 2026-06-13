"""Unit-test suite for quorum.eval.adherence (plan.md §11 D4).

Covers every public symbol and every documented edge case:
  - AdherenceScore.applicable()
  - score() validity / rendered_ok guards
  - count dimension: exact match, partial credit, off-by-one, zero, multi-role,
    counts={} → None, case-insensitive substring matching
  - color dimension: named color present/absent, colored_in=True/False,
    unknown color skipped, default stroke must NOT count as "blue",
    real blue fill MUST count as "blue", achromatic targets (black/gray)
  - coherence: single part, all-touching, fully-disjoint, partial case
  - relations: inside (true/false), above/below (y grows down), beside,
    unresolvable role → skipped, all-unresolved → dimension None
  - solids3d: payload_kind="solids" → 1.0, geometry shading signature, flat → 0.0
  - overall / sparsity penalty
  - empty Expectation → overall 1.0
  - check_coherence=False → coherence None
"""

from __future__ import annotations

from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind
from quorum.domain.isometric import Solid, project_solids
from quorum.eval.adherence import (
    NAMED_COLORS,
    AdherenceScore,
    Expectation,
    Relation,
    score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rect(
    name: str | None = None,
    x: float = 50.0,
    y: float = 50.0,
    w: float = 20.0,
    h: float = 20.0,
    fill: str | None = None,
    stroke: str = "#1f2937",
    fill_style: FillStyle | None = None,
) -> GeometrySpec:
    return GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        name=name,
        x=x,
        y=y,
        width=w,
        height=h,
        fill=fill,
        stroke=stroke,
        fill_style=fill_style,
    )


def _group(*parts: GeometrySpec) -> GeometrySpec:
    return GeometrySpec(kind=ShapeKind.GROUP, parts=list(parts))


def _poly(
    name: str | None = None,
    pts: list[tuple[float, float]] | None = None,
    fill: str | None = None,
    fill_style: FillStyle | None = None,
) -> GeometrySpec:
    if pts is None:
        pts = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]
    return GeometrySpec(
        kind=ShapeKind.POLYGON,
        name=name,
        points=pts,
        fill=fill,
        fill_style=fill_style,
    )


# ===========================================================================
# AdherenceScore.applicable()
# ===========================================================================


def test_applicable_returns_only_non_none() -> None:
    s = AdherenceScore(
        valid=True,
        count=0.8,
        color=None,
        coherence=1.0,
        relations=None,
        solids3d=None,
        overall=0.9,
        notes=(),
    )
    ap = s.applicable()
    assert set(ap.keys()) == {"count", "coherence"}
    assert ap["count"] == 0.8
    assert ap["coherence"] == 1.0


def test_applicable_empty_when_all_none() -> None:
    s = AdherenceScore(
        valid=False,
        count=None,
        color=None,
        coherence=None,
        relations=None,
        solids3d=None,
        overall=0.0,
        notes=(),
    )
    assert s.applicable() == {}


def test_applicable_all_dims_present() -> None:
    s = AdherenceScore(
        valid=True,
        count=1.0,
        color=0.5,
        coherence=1.0,
        relations=0.0,
        solids3d=1.0,
        overall=0.7,
        notes=(),
    )
    assert set(s.applicable().keys()) == {"count", "color", "coherence", "relations", "solids3d"}


# ===========================================================================
# Validity guards
# ===========================================================================


def test_score_none_geom_is_invalid() -> None:
    result = score(None, Expectation())
    assert result.valid is False
    assert result.overall == 0.0
    assert result.count is None
    assert result.color is None
    assert result.coherence is None
    assert result.relations is None
    assert result.solids3d is None


def test_score_rendered_ok_false_is_invalid() -> None:
    geom = _rect()
    result = score(geom, Expectation(), rendered_ok=False)
    assert result.valid is False
    assert result.overall == 0.0
    assert result.applicable() == {}


def test_score_valid_geom_rendered_ok() -> None:
    result = score(_rect(), Expectation())
    assert result.valid is True


# ===========================================================================
# Empty Expectation → overall 1.0
# ===========================================================================


def test_empty_expectation_overall_1() -> None:
    """No annotations → only coherence applies (single part → 1.0)."""
    result = score(_rect(), Expectation())
    assert result.valid is True
    assert result.overall == 1.0
    assert result.count is None
    assert result.color is None
    assert result.relations is None
    assert result.solids3d is None


def test_empty_expectation_group_all_touching_overall_1() -> None:
    # Two touching parts, no annotations
    a = _rect(x=20.0, y=50.0, w=20.0, h=20.0)
    b = _rect(x=40.0, y=50.0, w=20.0, h=20.0)
    result = score(_group(a, b), Expectation())
    assert result.overall == 1.0


# ===========================================================================
# count dimension
# ===========================================================================


def test_count_exact_match() -> None:
    parts = [_rect(name="thruster-1"), _rect(name="thruster-2")]
    geom = _group(*parts)
    result = score(geom, Expectation(counts={"thruster": 2}))
    assert result.count == 1.0


def test_count_off_by_one_above() -> None:
    # Expected 5, have 4 → score = 1 - 1/5 = 0.8
    parts = [_rect(name=f"thruster-{i}") for i in range(4)]
    geom = _group(*parts)
    result = score(geom, Expectation(counts={"thruster": 5}))
    assert result.count is not None
    assert abs(result.count - 0.8) < 1e-9


def test_count_off_by_one_below() -> None:
    # Expected 5, have 6 → score = 1 - 1/5 = 0.8
    parts = [_rect(name=f"thruster-{i}") for i in range(6)]
    geom = _group(*parts)
    result = score(geom, Expectation(counts={"thruster": 5}))
    assert result.count is not None
    assert abs(result.count - 0.8) < 1e-9


def test_count_2_of_5_partial_credit() -> None:
    # formula: max(0, 1 - |actual-expected| / expected) = 1 - |2-5|/5 = 0.4
    parts = [_rect(name=f"thruster-{i}") for i in range(2)]
    geom = _group(*parts)
    result = score(geom, Expectation(counts={"thruster": 5}))
    assert result.count is not None
    assert abs(result.count - 0.4) < 1e-9


def test_count_1_of_2_gives_0_5() -> None:
    # 1 actual, 2 expected → 1 - 1/2 = 0.5
    geom = _group(_rect(name="window-1"))
    result = score(geom, Expectation(counts={"window": 2}))
    assert result.count is not None
    assert abs(result.count - 0.5) < 1e-9


def test_count_zero_matches() -> None:
    # No parts match → score 0.0
    geom = _group(_rect(name="body"), _rect(name="nose"))
    result = score(geom, Expectation(counts={"thruster": 2}))
    assert result.count is not None
    assert result.count == 0.0


def test_count_empty_counts_is_none() -> None:
    geom = _rect()
    result = score(geom, Expectation(counts={}))
    assert result.count is None


def test_count_case_insensitive_match() -> None:
    # "thruster-1" matches role "Thruster"
    geom = _group(_rect(name="thruster-1"), _rect(name="THRUSTER-2"))
    result = score(geom, Expectation(counts={"Thruster": 2}))
    assert result.count == 1.0


def test_count_substring_match() -> None:
    # "forward-thruster" contains "thruster"
    geom = _group(_rect(name="forward-thruster"), _rect(name="rear-thruster"))
    result = score(geom, Expectation(counts={"thruster": 2}))
    assert result.count == 1.0


def test_count_multi_role_averaged() -> None:
    # 2 thrusters (expected 2 → 1.0) + 1 window (expected 2 → 0.5) → mean = 0.75
    parts = [
        _rect(name="thruster-1"),
        _rect(name="thruster-2"),
        _rect(name="window-1"),
    ]
    geom = _group(*parts)
    result = score(geom, Expectation(counts={"thruster": 2, "window": 2}))
    assert result.count is not None
    assert abs(result.count - 0.75) < 1e-9


def test_count_does_not_count_parts_with_none_name() -> None:
    # parts without names are not matched
    geom = _group(_rect(name=None), _rect(name=None))
    result = score(geom, Expectation(counts={"thruster": 2}))
    assert result.count is not None
    assert result.count == 0.0


def test_count_single_part_geom() -> None:
    geom = _rect(name="hull")
    result = score(geom, Expectation(counts={"hull": 1}))
    assert result.count == 1.0


# ===========================================================================
# color dimension
# ===========================================================================


def test_color_blue_fill_matches() -> None:
    # A real saturated blue fill must match "blue"
    geom = _group(_rect(name="body", fill="#2563eb", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(colors=("blue",)))
    assert result.color == 1.0


def test_color_default_stroke_must_not_count_as_blue() -> None:
    # "#1f2937" is a dark desaturated blue — the lightness floor must exclude it
    geom = _group(_rect(name="body", stroke="#1f2937"))
    result = score(geom, Expectation(colors=("blue",)))
    assert result.color is not None
    assert result.color == 0.0


def test_color_red_fill_matches() -> None:
    geom = _group(_rect(name="body", fill="#dc2626", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(colors=("red",)))
    assert result.color == 1.0


def test_color_absent_named_color_is_0() -> None:
    # blue requested, but part only has red
    geom = _group(_rect(name="body", fill="#dc2626", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(colors=("blue",)))
    assert result.color is not None
    assert result.color == 0.0


def test_color_unknown_color_name_skipped() -> None:
    # "mauve" is not in NAMED_COLORS — note is emitted but it's skipped entirely
    # If all colors are unknown, color dimension is None
    geom = _group(_rect(name="body", fill="#2563eb", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(colors=("mauve",)))
    # unknown color alone → no reqs → color dimension is None
    assert result.color is None


def test_color_mix_known_and_unknown_skips_unknown() -> None:
    # "blue" is known (present), "mauve" is unknown (skipped)
    geom = _group(_rect(name="body", fill="#2563eb", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(colors=("blue", "mauve")))
    # only "blue" contributes → 1.0
    assert result.color is not None
    assert result.color == 1.0


def test_color_multiple_required_both_present() -> None:
    parts = [
        _rect(name="nose", fill="#dc2626", fill_style=FillStyle.SOLID),
        _rect(name="body", fill="#2563eb", fill_style=FillStyle.SOLID),
    ]
    geom = _group(*parts)
    result = score(geom, Expectation(colors=("red", "blue")))
    assert result.color is not None
    assert abs(result.color - 1.0) < 1e-9


def test_color_multiple_required_one_absent() -> None:
    parts = [
        _rect(name="nose", fill="#dc2626", fill_style=FillStyle.SOLID),
        _rect(name="body"),  # no fill
    ]
    geom = _group(*parts)
    result = score(geom, Expectation(colors=("red", "blue")))
    assert result.color is not None
    assert abs(result.color - 0.5) < 1e-9


def test_color_colored_in_true_with_fill_is_1() -> None:
    geom = _group(_rect(name="body", fill="#dc2626", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(colored_in=True))
    assert result.color is not None
    assert result.color == 1.0


def test_color_colored_in_true_no_fill_is_0() -> None:
    geom = _group(_rect(name="body"))
    result = score(geom, Expectation(colored_in=True))
    assert result.color is not None
    assert result.color == 0.0


def test_color_colored_in_fill_style_none_counts_as_no_fill() -> None:
    # fill_style=NONE means explicitly no fill — should score 0 for colored_in
    geom = _group(_rect(name="body", fill="#dc2626", fill_style=FillStyle.NONE))
    result = score(geom, Expectation(colored_in=True))
    assert result.color is not None
    assert result.color == 0.0


def test_color_colored_in_hachure_fill_counts() -> None:
    # HACHURE is a fill (not NONE) — should score 1.0 for colored_in
    geom = _group(_rect(name="body", fill="#dc2626", fill_style=FillStyle.HACHURE))
    result = score(geom, Expectation(colored_in=True))
    assert result.color is not None
    assert result.color == 1.0


def test_color_no_color_specs_is_none() -> None:
    geom = _rect()
    result = score(geom, Expectation(colors=(), colored_in=False))
    assert result.color is None


def test_color_black_matches_true_black_fill() -> None:
    # NAMED_COLORS["black"] is now a truly achromatic "#111111", so the achromatic
    # branch fires and a real black fill matches (the harness-review fix). A near-
    # black like the default stroke #1f2937 reads as dark blue and must NOT match.
    black_fill = _group(_rect(name="outline", fill="#000000", fill_style=FillStyle.SOLID))
    assert score(black_fill, Expectation(colors=("black",))).color == 1.0
    bluish = _group(_rect(name="outline", fill="#1f2937", fill_style=FillStyle.SOLID))
    assert score(bluish, Expectation(colors=("black",))).color == 0.0


def test_color_gray_achromatic_match() -> None:
    # mid-gray matching "gray"
    geom = _group(_rect(name="body", fill="#6b7280", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(colors=("gray",)))
    assert result.color is not None
    assert result.color == 1.0


def test_named_colors_dict_has_known_colors() -> None:
    for name in ("blue", "red", "green", "black", "white", "gray", "grey"):
        assert name in NAMED_COLORS, f"NAMED_COLORS missing {name!r}"


def test_named_colors_blue_is_saturated() -> None:
    from quorum.domain.color import parse_hex, rgb_to_hsl

    rgb = parse_hex(NAMED_COLORS["blue"])
    assert rgb is not None
    _, s, li = rgb_to_hsl(*rgb)
    assert s >= 0.5, "NAMED_COLORS['blue'] should be saturated"
    assert li >= 0.3, "NAMED_COLORS['blue'] should be mid-toned"


# ===========================================================================
# coherence dimension
# ===========================================================================


def test_coherence_single_part_is_1() -> None:
    result = score(_rect(), Expectation())
    assert result.coherence == 1.0


def test_coherence_single_part_in_group_is_1() -> None:
    geom = _group(_rect(x=50.0, y=50.0))
    result = score(geom, Expectation())
    assert result.coherence == 1.0


def test_coherence_all_touching_is_1() -> None:
    # Two rectangles sharing an edge
    a = _rect(x=25.0, y=50.0, w=20.0, h=20.0)
    b = _rect(x=45.0, y=50.0, w=20.0, h=20.0)
    geom = _group(a, b)
    result = score(geom, Expectation())
    assert result.coherence is not None
    assert abs(result.coherence - 1.0) < 1e-9


def test_coherence_fully_disjoint_is_0() -> None:
    # Two rects far apart, no overlap
    a = _rect(x=10.0, y=10.0, w=6.0, h=6.0)
    b = _rect(x=90.0, y=90.0, w=6.0, h=6.0)
    geom = _group(a, b)
    result = score(geom, Expectation())
    assert result.coherence is not None
    assert result.coherence == 0.0


def test_coherence_three_parts_partial() -> None:
    # 3 parts: a and b touch, c is isolated
    a = _rect(x=20.0, y=50.0, w=10.0, h=10.0)
    b = _rect(x=30.0, y=50.0, w=10.0, h=10.0)  # shares edge with a
    c = _rect(x=85.0, y=85.0, w=6.0, h=6.0)    # isolated
    geom = _group(a, b, c)
    result = score(geom, Expectation())
    assert result.coherence is not None
    # 2 components among 3 parts → (3-2)/(3-1) = 0.5
    assert 0.0 < result.coherence < 1.0


def test_coherence_three_parts_all_connected() -> None:
    # Three parts all in a chain: a-b-c
    a = _rect(x=20.0, y=50.0, w=10.0, h=10.0)
    b = _rect(x=30.0, y=50.0, w=10.0, h=10.0)
    c = _rect(x=40.0, y=50.0, w=10.0, h=10.0)
    geom = _group(a, b, c)
    result = score(geom, Expectation())
    assert result.coherence is not None
    assert abs(result.coherence - 1.0) < 1e-9


def test_coherence_check_coherence_false_gives_none() -> None:
    geom = _group(_rect(x=10.0), _rect(x=90.0))
    result = score(geom, Expectation(check_coherence=False))
    assert result.coherence is None


def test_coherence_overlapping_parts_count_as_touching() -> None:
    # Completely overlapping rects → one component → 1.0
    a = _rect(x=50.0, y=50.0, w=20.0, h=20.0)
    b = _rect(x=50.0, y=50.0, w=15.0, h=15.0)
    geom = _group(a, b)
    result = score(geom, Expectation())
    assert result.coherence is not None
    assert result.coherence == 1.0


def test_coherence_within_eps_touch() -> None:
    # Parts within 1 unit of touching (eps=1.0) should count as touching
    # a right edge at x=35, b left edge at x=36 → gap=1 → within eps → touch
    a = _rect(x=25.0, y=50.0, w=20.0, h=10.0)   # bbox: 15..35
    b = _rect(x=46.0, y=50.0, w=20.0, h=10.0)   # bbox: 36..56 — gap = 1
    geom = _group(a, b)
    result = score(geom, Expectation())
    assert result.coherence is not None
    assert result.coherence == 1.0


# ===========================================================================
# relations dimension
# ===========================================================================


def test_relation_inside_true() -> None:
    # inner bbox completely inside outer bbox
    inner = _rect(name="dot", x=50.0, y=50.0, w=4.0, h=4.0)
    outer = _rect(name="frame", x=50.0, y=50.0, w=40.0, h=40.0)
    geom = _group(inner, outer)
    rel = Relation(kind="inside", inner="dot", outer="frame")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations == 1.0


def test_relation_inside_false() -> None:
    # inner clearly outside outer
    inner = _rect(name="dot", x=10.0, y=10.0, w=4.0, h=4.0)
    outer = _rect(name="frame", x=80.0, y=80.0, w=20.0, h=20.0)
    geom = _group(inner, outer)
    rel = Relation(kind="inside", inner="dot", outer="frame")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations == 0.0


def test_relation_above_true() -> None:
    # y grows DOWN: "above" = smaller y-center with x-overlap
    top = _rect(name="sky", x=50.0, y=20.0, w=30.0, h=10.0)  # y-center=20
    bottom = _rect(name="ground", x=50.0, y=70.0, w=30.0, h=10.0)  # y-center=70
    geom = _group(top, bottom)
    rel = Relation(kind="above", inner="sky", outer="ground")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations == 1.0


def test_relation_above_false_when_below() -> None:
    # sky is actually below ground in y (larger y)
    top = _rect(name="sky", x=50.0, y=80.0, w=30.0, h=10.0)
    bottom = _rect(name="ground", x=50.0, y=20.0, w=30.0, h=10.0)
    geom = _group(top, bottom)
    rel = Relation(kind="above", inner="sky", outer="ground")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations == 0.0


def test_relation_below_true() -> None:
    top = _rect(name="header", x=50.0, y=20.0, w=30.0, h=10.0)
    bottom = _rect(name="footer", x=50.0, y=80.0, w=30.0, h=10.0)
    geom = _group(top, bottom)
    rel = Relation(kind="below", inner="footer", outer="header")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations == 1.0


def test_relation_beside_true() -> None:
    # side by side: x ranges don't overlap, y ranges do
    left = _rect(name="left-panel", x=20.0, y=50.0, w=20.0, h=20.0)
    right = _rect(name="right-panel", x=60.0, y=50.0, w=20.0, h=20.0)
    geom = _group(left, right)
    rel = Relation(kind="beside", inner="left-panel", outer="right-panel")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations == 1.0


def test_relation_beside_false_when_overlapping_x() -> None:
    # Parts share x range → not beside
    a = _rect(name="alpha", x=50.0, y=20.0, w=30.0, h=10.0)
    b = _rect(name="beta", x=50.0, y=70.0, w=30.0, h=10.0)
    geom = _group(a, b)
    rel = Relation(kind="beside", inner="alpha", outer="beta")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations == 0.0


def test_relation_unresolvable_inner_is_skipped() -> None:
    # "dot" doesn't match any part name
    outer = _rect(name="frame", x=50.0, y=50.0, w=40.0, h=40.0)
    geom = _group(outer)
    rel = Relation(kind="inside", inner="dot", outer="frame")
    result = score(geom, Expectation(relations=(rel,)))
    # skipped → None (no scorable relations)
    assert result.relations is None


def test_relation_unresolvable_outer_is_skipped() -> None:
    inner = _rect(name="dot", x=50.0, y=50.0, w=4.0, h=4.0)
    geom = _group(inner)
    rel = Relation(kind="inside", inner="dot", outer="frame")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations is None


def test_relation_ambiguous_role_zero_parts_skipped() -> None:
    # Zero parts match "dot" → skipped
    outer = _rect(name="frame", x=50.0, y=50.0, w=40.0, h=40.0)
    geom = _group(outer)
    rel = Relation(kind="inside", inner="dot", outer="frame")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations is None


def test_relation_ambiguous_role_multiple_matches_skipped() -> None:
    # Two parts named "dot-1" and "dot-2" both match "dot" → ambiguous → skipped
    d1 = _rect(name="dot-1", x=50.0, y=50.0, w=4.0, h=4.0)
    d2 = _rect(name="dot-2", x=50.0, y=55.0, w=4.0, h=4.0)
    outer = _rect(name="frame", x=50.0, y=50.0, w=40.0, h=40.0)
    geom = _group(d1, d2, outer)
    rel = Relation(kind="inside", inner="dot", outer="frame")
    result = score(geom, Expectation(relations=(rel,)))
    assert result.relations is None


def test_relation_all_unresolved_dimension_is_none() -> None:
    geom = _group(_rect(name="body"))
    rels = (
        Relation(kind="inside", inner="ghost1", outer="ghost2"),
        Relation(kind="above", inner="spirit", outer="phantom"),
    )
    result = score(geom, Expectation(relations=rels))
    assert result.relations is None


def test_relation_mixed_resolved_and_unresolved() -> None:
    # One scorable relation (holds), one unresolvable → score = 1.0
    inner = _rect(name="dot", x=50.0, y=50.0, w=4.0, h=4.0)
    outer = _rect(name="frame", x=50.0, y=50.0, w=40.0, h=40.0)
    geom = _group(inner, outer)
    rels = (
        Relation(kind="inside", inner="dot", outer="frame"),
        Relation(kind="above", inner="ghost", outer="frame"),  # ghost unresolvable
    )
    result = score(geom, Expectation(relations=rels))
    assert result.relations is not None
    assert result.relations == 1.0


def test_relations_empty_tuple_is_none() -> None:
    result = score(_rect(), Expectation(relations=()))
    assert result.relations is None


# ===========================================================================
# solids3d dimension
# ===========================================================================


def test_solids3d_not_applicable_when_expect_3d_false() -> None:
    geom = _rect()
    result = score(geom, Expectation(expect_3d=False))
    assert result.solids3d is None


def test_solids3d_payload_kind_solids_is_1() -> None:
    geom = _rect()
    result = score(geom, Expectation(expect_3d=True), payload_kind="solids")
    assert result.solids3d == 1.0


def test_solids3d_payload_kind_other_falls_to_geometry() -> None:
    # payload_kind="patch" (not "solids") — no shading → 0.0
    geom = _group(_rect(x=50.0, y=50.0, fill="#2563eb", fill_style=FillStyle.SOLID))
    result = score(geom, Expectation(expect_3d=True), payload_kind="patch")
    # single color fill: no lightness span → 0.0
    assert result.solids3d is not None
    assert result.solids3d == 0.0


def test_solids3d_real_projected_group_is_1() -> None:
    """A real project_solids() output has the shading signature → 1.0."""
    solids = [Solid(shape="box", x=10.0, y=0.0, z=10.0, w=40.0, d=40.0, h=30.0,
                    color="#6b7280")]
    geom = project_solids(solids)
    assert geom is not None
    result = score(geom, Expectation(expect_3d=True))
    assert result.solids3d == 1.0


def test_solids3d_flat_single_rect_is_0() -> None:
    # A lone flat rectangle answers a 3D prompt → 0.0
    geom = _rect(fill="#6b7280", fill_style=FillStyle.SOLID)
    result = score(geom, Expectation(expect_3d=True))
    assert result.solids3d == 0.0


def test_solids3d_two_faces_insufficient_lightness_span_is_0() -> None:
    # Two solid-filled parts whose fills are nearly the same lightness → 0.0
    a = _poly(fill="#9ca3af", fill_style=FillStyle.SOLID,
               pts=[(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)])
    b = _poly(fill="#9ca3af", fill_style=FillStyle.SOLID,
               pts=[(30.0, 10.0), (50.0, 10.0), (50.0, 30.0), (30.0, 30.0)])
    geom = _group(a, b)
    result = score(geom, Expectation(expect_3d=True))
    assert result.solids3d == 0.0


def test_solids3d_two_faces_sufficient_lightness_span_is_1() -> None:
    # One very light fill (L≈0.9) and one dark fill (L≈0.25) → span ≥ 0.18 → 1.0
    light_fill = "#e5e7eb"  # L ≈ 0.92
    dark_fill = "#374151"   # L ≈ 0.23
    a = _poly(fill=light_fill, fill_style=FillStyle.SOLID,
               pts=[(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)])
    b = _poly(fill=dark_fill, fill_style=FillStyle.SOLID,
               pts=[(30.0, 10.0), (50.0, 10.0), (50.0, 30.0), (30.0, 30.0)])
    geom = _group(a, b)
    result = score(geom, Expectation(expect_3d=True))
    assert result.solids3d == 1.0


def test_solids3d_hachure_fills_ignored_by_shading_check() -> None:
    # HACHURE fills don't count as SOLID → no lits → 0.0
    a = _poly(fill="#e5e7eb", fill_style=FillStyle.HACHURE,
               pts=[(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)])
    b = _poly(fill="#374151", fill_style=FillStyle.HACHURE,
               pts=[(30.0, 10.0), (50.0, 10.0), (50.0, 30.0), (30.0, 30.0)])
    geom = _group(a, b)
    result = score(geom, Expectation(expect_3d=True))
    assert result.solids3d == 0.0


# ===========================================================================
# overall / sparsity penalty
# ===========================================================================


def test_overall_single_dim_equals_that_dim() -> None:
    # Only count applies → overall = count
    parts = [_rect(name="thruster-1"), _rect(name="thruster-2")]
    geom = _group(*parts)
    result = score(geom, Expectation(counts={"thruster": 2}, check_coherence=False))
    assert result.count is not None
    assert abs(result.overall - result.count) < 1e-9


def test_overall_mean_of_applicable_dims() -> None:
    # count=1.0, coherence=1.0 → overall=1.0
    # Make parts touch: eye-left bbox 30..50, eye-right bbox 50..70 (shared edge)
    geom = _group(_rect(name="eye-left", x=40.0, y=50.0, w=20.0, h=10.0),
                  _rect(name="eye-right", x=60.0, y=50.0, w=20.0, h=10.0))
    result = score(geom, Expectation(counts={"eye": 2}))
    assert result.count == 1.0
    assert result.coherence == 1.0
    assert result.overall == 1.0


def test_sparsity_penalty_scales_down() -> None:
    # min_parts=5, have 2 parts → factor=2/5=0.4 → overall * 0.4
    geom = _group(_rect(name="part-1"), _rect(name="part-2"))
    result = score(geom, Expectation(min_parts=5))
    # Without penalty overall=1.0 (coherence 1.0 for touching)
    # With penalty overall *= 2/5
    assert result.overall is not None
    assert result.overall < 1.0
    assert abs(result.overall - 1.0 * (2 / 5)) < 0.1  # coherence may be <1 if not touching


def test_sparsity_penalty_exact() -> None:
    # Guaranteed coherence=1.0 (touching parts), no other dims
    a = _rect(x=25.0, y=50.0, w=20.0, h=20.0)
    b = _rect(x=45.0, y=50.0, w=20.0, h=20.0)
    geom = _group(a, b)
    result = score(geom, Expectation(min_parts=5))
    # coherence = 1.0, factor = 2/5 = 0.4
    assert result.overall is not None
    assert abs(result.overall - 0.4) < 1e-9


def test_sparsity_no_penalty_when_min_parts_1() -> None:
    # Default min_parts=1 → no penalty applied even with 1 part
    geom = _rect()
    result = score(geom, Expectation(min_parts=1))
    assert result.overall == 1.0


def test_sparsity_no_penalty_when_parts_meet_threshold() -> None:
    # 3 parts, min_parts=3 → len(parts)/min_parts=1.0 → no effective penalty
    # Parts must touch so coherence=1.0: chain with shared edges
    # part-0 bbox: 10..30, part-1 bbox: 30..50, part-2 bbox: 50..70
    parts = [_rect(name=f"x-{i}", x=float(20 + 20 * i), y=50.0, w=20.0, h=10.0)
             for i in range(3)]
    geom = _group(*parts)
    result = score(geom, Expectation(min_parts=3))
    # Penalty only applies when len(parts) < min_parts; 3 < 3 is False → no penalty
    assert result.coherence == 1.0
    assert result.overall == 1.0


# ===========================================================================
# notes sanity checks
# ===========================================================================


def test_notes_contain_invalid_message_for_none_geom() -> None:
    result = score(None, Expectation())
    assert any("invalid" in n.lower() for n in result.notes)


def test_notes_contain_count_info() -> None:
    geom = _group(_rect(name="thruster-1"))
    result = score(geom, Expectation(counts={"thruster": 1}))
    assert any("count" in n for n in result.notes)


def test_notes_contain_coherence_info() -> None:
    geom = _group(_rect(x=10.0), _rect(x=90.0))
    result = score(geom, Expectation())
    assert any("coherence" in n for n in result.notes)


def test_notes_contain_solids3d_info() -> None:
    result = score(_rect(), Expectation(expect_3d=True), payload_kind="solids")
    assert any("solids3d" in n for n in result.notes)


def test_notes_mention_skipped_for_unknown_color() -> None:
    geom = _rect(fill="#2563eb", fill_style=FillStyle.SOLID)
    result = score(geom, Expectation(colors=("mauve",)))
    assert any("skipped" in n.lower() for n in result.notes)


# ===========================================================================
# Integration / combined expectations
# ===========================================================================


def test_full_expectation_all_pass() -> None:
    """A scene that satisfies count + color + coherence + relation → overall=1.0."""
    # body bbox: y 35..65 (x=50, y=50, h=30)
    # antenna bbox: y 33..43 (x=50, y=38, h=10) — overlaps with body top edge
    # so antenna.y_center=38 < body.y_center=50 → "above" holds (y grows down)
    # antenna.x bbox: 48..52 overlaps with body.x bbox 30..70 → columns overlap ✓
    body = _rect(name="body", x=50.0, y=50.0, w=40.0, h=30.0,
                 fill="#2563eb", fill_style=FillStyle.SOLID)
    antenna = _rect(name="antenna", x=50.0, y=38.0, w=4.0, h=10.0)
    geom = _group(body, antenna)
    expect = Expectation(
        counts={"body": 1, "antenna": 1},
        colors=("blue",),
        relations=(Relation(kind="above", inner="antenna", outer="body"),),
        min_parts=2,
    )
    result = score(geom, expect)
    assert result.valid is True
    assert result.count == 1.0
    assert result.color == 1.0
    assert result.relations == 1.0
    assert result.coherence == 1.0
    assert result.overall == 1.0


def test_full_expectation_one_fail_lowers_overall() -> None:
    """count passes but color absent → overall < 1.0."""
    body = _rect(name="body", x=50.0, y=50.0, w=40.0, h=30.0)
    geom = _group(body)
    expect = Expectation(
        counts={"body": 1},
        colors=("blue",),
        check_coherence=False,
    )
    result = score(geom, expect)
    assert result.count == 1.0
    assert result.color == 0.0
    assert result.overall < 1.0


def test_score_is_pure_same_input_same_output() -> None:
    """Same geom+expect must always produce byte-identical results."""
    geom = _group(_rect(name="part-a"), _rect(name="part-b"))
    expect = Expectation(counts={"part": 2}, colors=("blue",))
    r1 = score(geom, expect)
    r2 = score(geom, expect)
    assert r1 == r2


# ---------------------------------------------------------------------------
# Regression tests for the adversarial-review findings (harness gaming vectors)
# ---------------------------------------------------------------------------


def test_coherence_ignores_full_canvas_background() -> None:
    # A near-full-canvas background must NOT bridge an exploded foreground into
    # one fake component: three disjoint corner parts stay incoherent (0.0).
    gamed = _group(
        _rect(name="bg", x=50, y=50, w=100, h=100, fill="#ffffff", fill_style=FillStyle.SOLID),
        _rect(name="a", x=10, y=10, w=6, h=6),
        _rect(name="b", x=90, y=90, w=6, h=6),
        _rect(name="c", x=90, y=10, w=6, h=6),
    )
    assert score(gamed, Expectation()).coherence == 0.0


def test_count_skipped_on_solids_payload() -> None:
    # Projected solids decompose "piston-1" into "piston-1-body" + "piston-1-top",
    # so role-substring counting over-counts; the solids path skips count entirely.
    proj = project_solids([Solid("cylinder", 20, 0, 20, 12, 12, 20, "#9ca3af", "piston-1")])
    assert proj is not None
    assert score(proj, Expectation(counts={"piston": 1}), payload_kind="solids").count is None
    # Same geometry WITHOUT the solids hint over-counts (the bug being guarded).
    nohint = score(proj, Expectation(counts={"piston": 1}))
    assert nohint.count is not None and nohint.count < 1.0


def test_solids3d_ignores_near_white_background() -> None:
    # A flat 3D-prompt answer pairing a white background with one dark fill must
    # NOT pass the shading signature as fake "3D" — white is excluded as a face.
    flat = _group(
        _rect(name="bg", x=50, y=50, w=80, h=80, fill="#ffffff", fill_style=FillStyle.SOLID),
        _rect(name="body", x=50, y=50, w=30, h=30, fill="#374151", fill_style=FillStyle.SOLID),
    )
    assert score(flat, Expectation(expect_3d=True)).solids3d == 0.0
