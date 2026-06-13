"""Unit tests for quorum.domain.compose.place_relative.

All tests are pure (synchronous, no I/O, no fixtures beyond direct construction)
and cover every supported relation plus the fit-to-box contract.
"""

from __future__ import annotations

import pytest

from quorum.domain.compose import place_relative
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.pipeline.relations import part_bbox

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rect(x: float, y: float, w: float, h: float, **kw: float) -> GeometrySpec:
    return GeometrySpec(kind=ShapeKind.RECTANGLE, x=x, y=y, width=w, height=h, **kw)


def _circle(x: float, y: float, w: float, h: float, **kw: float) -> GeometrySpec:
    return GeometrySpec(kind=ShapeKind.CIRCLE, x=x, y=y, width=w, height=h, **kw)


def _all_coords_in_box(spec: GeometrySpec) -> bool:
    """Return True when every coordinate in every part lies in [0, 100]."""
    for part in spec.parts:
        x1, y1, x2, y2 = part_bbox(part)
        if not (0.0 <= x1 <= 100.0 and 0.0 <= y1 <= 100.0):
            return False
        if not (0.0 <= x2 <= 100.0 and 0.0 <= y2 <= 100.0):
            return False
        # Also check center coords (for non-polygon kinds).
        if not (0.0 <= part.x <= 100.0 and 0.0 <= part.y <= 100.0):
            return False
    return True


def _center_y_of_part(spec: GeometrySpec, idx: int) -> float:
    b = part_bbox(spec.parts[idx])
    return (b[1] + b[3]) / 2.0


def _center_x_of_part(spec: GeometrySpec, idx: int) -> float:
    b = part_bbox(spec.parts[idx])
    return (b[0] + b[2]) / 2.0


# ---------------------------------------------------------------------------
# Basic sanity: returns a flat GROUP
# ---------------------------------------------------------------------------


def test_returns_flat_group() -> None:
    target = _rect(50, 50, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "above")
    assert result.kind is ShapeKind.GROUP
    assert all(p.kind is not ShapeKind.GROUP for p in result.parts)


def test_combined_has_target_plus_new_part() -> None:
    target = _rect(50, 50, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "above")
    assert len(result.parts) == 2


# ---------------------------------------------------------------------------
# Relation: above
# ---------------------------------------------------------------------------


def test_place_above_new_part_center_y_less_than_target() -> None:
    """After fitting, the placed part's centre should be above the target."""
    target = _rect(50, 55, 40, 30)   # y-center 55, spans y ≈ 40..70
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "above")
    # In the result, new_part is last (index 1); target is first (index 0).
    new_cy = _center_y_of_part(result, 1)
    tgt_cy = _center_y_of_part(result, 0)
    assert new_cy < tgt_cy, f"new_cy={new_cy} should be above tgt_cy={tgt_cy}"


def test_place_above_all_parts_in_box() -> None:
    target = _rect(50, 55, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "above")
    assert _all_coords_in_box(result)


def test_place_above_new_part_not_overlapping_target() -> None:
    """The bottom edge of the new part must be above the top edge of the target."""
    target = _rect(50, 55, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "above")
    new_b = part_bbox(result.parts[1])
    tgt_b = part_bbox(result.parts[0])
    # After fitting/scaling, bottom of new_part <= top of target (with small tolerance).
    assert new_b[3] <= tgt_b[1] + 1.0, (
        f"new_part bottom {new_b[3]:.2f} overlaps target top {tgt_b[1]:.2f}"
    )


# ---------------------------------------------------------------------------
# Relation: below
# ---------------------------------------------------------------------------


def test_place_below_new_part_center_y_greater_than_target() -> None:
    target = _rect(50, 45, 40, 30)   # y-center 45, spans y ≈ 30..60
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "below")
    new_cy = _center_y_of_part(result, 1)
    tgt_cy = _center_y_of_part(result, 0)
    assert new_cy > tgt_cy, f"new_cy={new_cy} should be below tgt_cy={tgt_cy}"


def test_place_below_all_parts_in_box() -> None:
    target = _rect(50, 45, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "below")
    assert _all_coords_in_box(result)


# ---------------------------------------------------------------------------
# Relation: left
# ---------------------------------------------------------------------------


def test_place_left_new_part_center_x_less_than_target() -> None:
    target = _rect(55, 50, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "left")
    new_cx = _center_x_of_part(result, 1)
    tgt_cx = _center_x_of_part(result, 0)
    assert new_cx < tgt_cx, f"new_cx={new_cx} should be left of tgt_cx={tgt_cx}"


def test_place_left_all_parts_in_box() -> None:
    target = _rect(55, 50, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "left")
    assert _all_coords_in_box(result)


# ---------------------------------------------------------------------------
# Relation: right
# ---------------------------------------------------------------------------


def test_place_right_new_part_center_x_greater_than_target() -> None:
    target = _rect(45, 50, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "right")
    new_cx = _center_x_of_part(result, 1)
    tgt_cx = _center_x_of_part(result, 0)
    assert new_cx > tgt_cx, f"new_cx={new_cx} should be right of tgt_cx={tgt_cx}"


def test_place_right_all_parts_in_box() -> None:
    target = _rect(45, 50, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "right")
    assert _all_coords_in_box(result)


# ---------------------------------------------------------------------------
# Relation: on_top  (overlap, new_part painted last / highest z)
# ---------------------------------------------------------------------------


def test_place_on_top_new_part_is_last_in_parts() -> None:
    target = _rect(50, 52, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "on_top")
    assert result.parts[-1].kind is ShapeKind.CIRCLE


def test_place_on_top_parts_overlap() -> None:
    """on_top means center-aligned and overlapping — the bboxes must intersect."""
    target = _rect(50, 52, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "on_top")
    tgt_b = part_bbox(result.parts[0])
    new_b = part_bbox(result.parts[1])
    # Check horizontal and vertical overlap.
    horiz_overlap = tgt_b[0] < new_b[2] and new_b[0] < tgt_b[2]
    vert_overlap = tgt_b[1] < new_b[3] and new_b[1] < tgt_b[3]
    assert horiz_overlap and vert_overlap, "on_top parts must visually overlap"


def test_place_on_top_all_parts_in_box() -> None:
    target = _rect(50, 52, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "on_top")
    assert _all_coords_in_box(result)


# ---------------------------------------------------------------------------
# Relation: behind  (overlap, new_part painted first / lowest z)
# ---------------------------------------------------------------------------


def test_place_behind_new_part_is_first_in_parts() -> None:
    """'behind' → new_part must come FIRST so it is painted before the target."""
    target = _rect(50, 52, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "behind")
    assert result.parts[0].kind is ShapeKind.CIRCLE


def test_place_behind_all_parts_in_box() -> None:
    target = _rect(50, 52, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "behind")
    assert _all_coords_in_box(result)


# ---------------------------------------------------------------------------
# Relation: inside
# ---------------------------------------------------------------------------


def test_place_inside_new_part_within_host_bbox() -> None:
    """After fitting, the new part must lie within the target's bounding box."""
    target = _rect(50, 52, 46, 36)  # big target; spans x≈27..73, y≈34..70
    new_part = _circle(50, 50, 10, 10)
    result = place_relative(target, new_part, "inside")
    # New part is last.
    tgt_b = part_bbox(result.parts[0])
    new_b = part_bbox(result.parts[1])
    # After fit_to_box both shrink/move, so use generous tolerance.
    assert new_b[0] >= tgt_b[0] - 1.0
    assert new_b[1] >= tgt_b[1] - 1.0
    assert new_b[2] <= tgt_b[2] + 1.0
    assert new_b[3] <= tgt_b[3] + 1.0


def test_place_inside_all_parts_in_box() -> None:
    target = _rect(50, 52, 46, 36)
    new_part = _circle(50, 50, 10, 10)
    result = place_relative(target, new_part, "inside")
    assert _all_coords_in_box(result)


# ---------------------------------------------------------------------------
# fit_to_box: combined group always fits within 0..100
# ---------------------------------------------------------------------------


def test_fit_to_box_all_relations_in_box() -> None:
    """For every supported relation, all parts must lie strictly within [0, 100]."""
    target = _rect(50, 50, 40, 30)
    new_part = _circle(50, 50, 20, 20)
    for rel in ("above", "below", "left", "right", "on_top", "behind", "inside"):
        result = place_relative(target, new_part, rel)
        assert _all_coords_in_box(result), f"coords out of box for relation={rel!r}"


def test_fit_to_box_large_new_part_still_fits() -> None:
    """A new_part much larger than the target must still produce valid coords."""
    target = _rect(50, 50, 10, 10)  # small target
    new_part = _rect(50, 50, 80, 80)  # huge new part
    result = place_relative(target, new_part, "above")
    assert _all_coords_in_box(result)
    assert len(result.parts) == 2


def test_fit_to_box_preserves_above_arrangement() -> None:
    """After fit_to_box, the placed part's center must remain above the target's."""
    target = _rect(50, 60, 40, 20)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "above")
    new_cy = _center_y_of_part(result, 1)
    tgt_cy = _center_y_of_part(result, 0)
    assert new_cy < tgt_cy


def test_fit_to_box_preserves_right_arrangement() -> None:
    target = _rect(40, 50, 30, 20)
    new_part = _circle(50, 50, 20, 20)
    result = place_relative(target, new_part, "right")
    new_cx = _center_x_of_part(result, 1)
    tgt_cx = _center_x_of_part(result, 0)
    assert new_cx > tgt_cx


# ---------------------------------------------------------------------------
# Group target: parts are flattened
# ---------------------------------------------------------------------------


def test_group_target_flattened() -> None:
    """A GROUP target's parts must be flattened into the result (no nesting)."""
    target = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            _rect(40, 50, 20, 15),
            _circle(60, 50, 15, 15),
            _rect(50, 65, 18, 10),
        ],
    )
    new_part = _circle(50, 50, 12, 12)
    result = place_relative(target, new_part, "above")
    # 3 target parts + 1 new = 4 total, no nesting.
    assert len(result.parts) == 4
    assert all(p.kind is not ShapeKind.GROUP for p in result.parts)


def test_group_target_arrangement_preserved() -> None:
    """Target parts' relative horizontal order must survive the compose."""
    left_part = _rect(30, 50, 20, 20)
    right_part = _rect(70, 50, 20, 20)
    target = GeometrySpec(kind=ShapeKind.GROUP, parts=[left_part, right_part])
    new_part = _circle(50, 50, 10, 10)
    result = place_relative(target, new_part, "above")
    # Parts 0 and 1 in result are the original left/right parts.
    cx0 = _center_x_of_part(result, 0)
    cx1 = _center_x_of_part(result, 1)
    assert cx0 < cx1, "left part must still be left of right part after compose"


# ---------------------------------------------------------------------------
# Parts-at-limit guard
# ---------------------------------------------------------------------------


def test_parts_at_limit_raises_value_error() -> None:
    """A target with 60 parts must raise ValueError."""
    many_parts = [_rect(50, 50, 5, 5) for _ in range(60)]
    target = GeometrySpec(kind=ShapeKind.GROUP, parts=many_parts)
    new_part = _circle(50, 50, 10, 10)
    with pytest.raises(ValueError, match="60-part limit"):
        place_relative(target, new_part, "above")


def test_parts_just_below_limit_succeeds() -> None:
    """A target with 59 parts must succeed (result has 60 parts, exactly at limit)."""
    many_parts = [_rect(50, 50, 5, 5) for _ in range(59)]
    target = GeometrySpec(kind=ShapeKind.GROUP, parts=many_parts)
    new_part = _circle(50, 50, 10, 10)
    result = place_relative(target, new_part, "above")
    assert len(result.parts) == 60


# ---------------------------------------------------------------------------
# Unknown relation falls back to "above"
# ---------------------------------------------------------------------------


def test_unknown_relation_falls_back_to_above() -> None:
    target = _rect(50, 60, 40, 20)
    new_part = _circle(50, 50, 20, 20)
    result_above = place_relative(target, new_part, "above")
    result_unknown = place_relative(target, new_part, "diagonal_kinda")
    # Same spatial arrangement.
    new_cy_a = _center_y_of_part(result_above, 1)
    new_cy_u = _center_y_of_part(result_unknown, 1)
    tgt_cy_u = _center_y_of_part(result_unknown, 0)
    assert new_cy_u < tgt_cy_u
    assert abs(new_cy_a - new_cy_u) < 1.0


# ---------------------------------------------------------------------------
# Polygon new_part
# ---------------------------------------------------------------------------


def test_polygon_new_part_translates_correctly() -> None:
    """POLYGON new_part must have its points translated, not just x/y."""
    target = _rect(50, 60, 40, 20)
    poly = GeometrySpec(
        kind=ShapeKind.POLYGON,
        x=50, y=50, width=20, height=20,
        points=[(40.0, 40.0), (60.0, 40.0), (50.0, 60.0)],
    )
    result = place_relative(target, poly, "above")
    poly_part = result.parts[-1]
    assert poly_part.points is not None
    xs = [p[0] for p in poly_part.points]
    ys = [p[1] for p in poly_part.points]
    # All polygon point coords in box.
    assert all(0.0 <= v <= 100.0 for v in xs + ys)
    # After fitting, placed poly center y must be above target center y.
    new_cy = _center_y_of_part(result, len(result.parts) - 1)
    tgt_cy = _center_y_of_part(result, 0)
    assert new_cy < tgt_cy


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_place_relative_is_deterministic() -> None:
    """Calling place_relative twice with the same inputs must return equal results."""
    target = _rect(50, 52, 46, 36)
    new_part = _circle(50, 50, 20, 20)
    r1 = place_relative(target, new_part, "above")
    r2 = place_relative(target, new_part, "above")
    assert r1 == r2


# ---------------------------------------------------------------------------
# part_bbox now public (relations.py rename smoke test)
# ---------------------------------------------------------------------------


def test_part_bbox_public() -> None:
    """part_bbox must be importable from relations (no leading underscore)."""
    from quorum.pipeline.relations import part_bbox as pb

    rect = _rect(50, 50, 40, 30)
    x1, y1, x2, y2 = pb(rect)
    assert x1 == 30.0
    assert y1 == 35.0
    assert x2 == 70.0
    assert y2 == 65.0
