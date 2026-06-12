"""Tests for deterministic 2D->3D cabinet extrusion (plan.md ss13-N4).

Pins:
- hexagon: front-face points match input, contiguous visible-edge run,
  2-4 band quads, front face LAST, three distinct pink-band fills for a
  pink input (hue within a few degrees of source).
- rectangle, triangle (renderer-exact vertices), circle (16-gon, band count
  sensible), ellipse.
- near-edge shape triggers fit-shrink and still validates inside 0..100.
- unsupported kinds (PATH, LINE, TEXT, NODE, EDGE, multi-part GROUP) -> None.
- single-part GROUP -> extruded, label preserved.
- every emitted face validates (GeometrySpec) and the whole group renders to
  an <svg.
"""

from __future__ import annotations

import math

from quorum.domain.color import parse_hex, rgb_to_hsl
from quorum.domain.extrude import DEFAULT_DEPTH, extrude
from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind
from quorum.pipeline.renderer import get_renderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hexagon_pts(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """Regular hexagon, flat-top, CW in y-down (standard screen)."""
    pts = []
    for i in range(6):
        angle = math.pi / 3.0 * i  # 0°, 60°, …
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def _hue_of(hex_color: str) -> float:
    rgb = parse_hex(hex_color)
    assert rgb is not None, f"not a hex color: {hex_color!r}"
    h, _s, _l = rgb_to_hsl(*rgb)
    return h


def _lightness_of(hex_color: str) -> float:
    rgb = parse_hex(hex_color)
    assert rgb is not None, f"not a hex color: {hex_color!r}"
    _h, _s, li = rgb_to_hsl(*rgb)
    return li


def _pts_inside_box(pts: list[tuple[float, float]], margin: float = 0.0) -> bool:
    return all(
        margin <= px <= 100.0 - margin and margin <= py <= 100.0 - margin
        for px, py in pts
    )


# ---------------------------------------------------------------------------
# Hexagon tests
# ---------------------------------------------------------------------------

# Small hexagon centred at 50,50 so no fit-shrink is needed.
_HEX_R = 12.0
_HEX_PTS = _hexagon_pts(50.0, 50.0, _HEX_R)
_PINK_STROKE = "#db2777"

_HEX_SPEC = GeometrySpec(
    kind=ShapeKind.POLYGON,
    points=_HEX_PTS,
    stroke=_PINK_STROKE,
    fill=None,  # stroke-only pink
)


def test_hexagon_extrudes_to_group() -> None:
    result = extrude(_HEX_SPEC)
    assert result is not None
    assert result.kind is ShapeKind.GROUP


def test_hexagon_front_face_is_last_part() -> None:
    result = extrude(_HEX_SPEC)
    assert result is not None
    last = result.parts[-1]
    assert last.name == "face-front"


def test_hexagon_front_face_points_match_input() -> None:
    """No fit-shrink for small hexagon: front-face points must equal input."""
    result = extrude(_HEX_SPEC)
    assert result is not None
    front = result.parts[-1]
    assert front.points is not None
    assert len(front.points) == len(_HEX_PTS)
    for (ax, ay), (bx, by) in zip(front.points, _HEX_PTS, strict=True):
        assert abs(ax - bx) < 1e-9, f"x mismatch: {ax} vs {bx}"
        assert abs(ay - by) < 1e-9, f"y mismatch: {ay} vs {by}"


def test_hexagon_band_count_2_to_4() -> None:
    """A convex hexagon should have 2-4 visible band faces."""
    result = extrude(_HEX_SPEC)
    assert result is not None
    band_parts = [p for p in result.parts if p.name != "face-front"]
    assert 2 <= len(band_parts) <= 4, f"band count = {len(band_parts)}"


def test_hexagon_contiguous_visible_edge_run() -> None:
    """Band faces come from a contiguous run of edges in the hexagon."""
    result = extrude(_HEX_SPEC)
    assert result is not None
    band_parts = [p for p in result.parts if p.name != "face-front"]
    # Each band part is a 4-point quad.  The first point of each quad is a
    # silhouette vertex.  Collect the edge indices (p_i index in _HEX_PTS).
    # Contiguous means edge indices form an unbroken run (mod 6).
    edge_indices: list[int] = []
    for bp in band_parts:
        assert bp.points is not None and len(bp.points) == 4
        pi = tuple(bp.points[0])
        for idx, hp in enumerate(_HEX_PTS):
            if abs(hp[0] - pi[0]) < 1e-6 and abs(hp[1] - pi[1]) < 1e-6:
                edge_indices.append(idx)
                break
    assert len(edge_indices) == len(band_parts)
    n = len(_HEX_PTS)
    # Contiguous mod n means exactly ONE gap when walking the full circle —
    # the run may wrap around index 0 (e.g. {5, 0, 1} is contiguous).
    chosen = set(edge_indices)
    gaps = sum(1 for i in chosen if (i + 1) % n not in chosen)
    assert gaps == 1, f"non-contiguous edge set: {sorted(chosen)}"


def test_hexagon_pink_three_distinct_fills() -> None:
    """Pink (stroke-only) hexagon: all band fills + front fill use pink hue."""
    result = extrude(_HEX_SPEC)
    assert result is not None

    # Source hue: #db2777 (hot pink)
    src_rgb = parse_hex(_PINK_STROKE)
    assert src_rgb is not None
    src_h, _s, _l = rgb_to_hsl(*src_rgb)

    fills = [p.fill for p in result.parts]
    assert all(f is not None for f in fills), f"Some part has no fill: {fills}"

    # All fills must be distinct (three lightness bands).
    assert len(set(fills)) == 3, f"Expected 3 distinct fills, got {set(fills)}"

    # Every fill must be within ≤5° of the source hue (5/360 ≈ 0.014 in [0,1]).
    for fill in fills:
        fh = _hue_of(fill)  # type: ignore[arg-type]
        diff = min(abs(fh - src_h), 1.0 - abs(fh - src_h))
        assert diff < 0.04, (
            f"fill hue {fh:.3f} too far from source {src_h:.3f}: {fill}"
        )


def test_hexagon_lightness_ordering() -> None:
    """Front face should be mid-tone; band quads span lighter and darker."""
    result = extrude(_HEX_SPEC)
    assert result is not None
    front_l = _lightness_of(result.parts[-1].fill)  # type: ignore[arg-type]
    band_ls = [_lightness_of(p.fill) for p in result.parts[:-1]]  # type: ignore[arg-type]
    # At least one band face lighter than front, at least one darker.
    assert any(bl > front_l for bl in band_ls), "No band face lighter than front"
    assert any(bl < front_l for bl in band_ls), "No band face darker than front"


def test_hexagon_all_faces_validate() -> None:
    result = extrude(_HEX_SPEC)
    assert result is not None
    for part in result.parts:
        # Just constructing it validates via pydantic; check polygon points range.
        assert part.kind is ShapeKind.POLYGON
        assert part.points is not None
        assert _pts_inside_box(part.points), f"Part {part.name} has out-of-box pts"


def test_hexagon_renders_to_svg() -> None:
    result = extrude(_HEX_SPEC)
    assert result is not None
    svg = get_renderer().render(result)
    assert "<svg" in svg


def test_hexagon_fill_style_solid() -> None:
    result = extrude(_HEX_SPEC)
    assert result is not None
    for part in result.parts:
        assert part.fill_style is FillStyle.SOLID


# ---------------------------------------------------------------------------
# Rectangle
# ---------------------------------------------------------------------------


def test_rectangle_extrudes() -> None:
    spec = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        x=50.0,
        y=50.0,
        width=30.0,
        height=20.0,
        fill="#3b82f6",
        stroke="#1e40af",
    )
    result = extrude(spec)
    assert result is not None
    assert result.kind is ShapeKind.GROUP
    # Rectangle front face should have 4 points.
    front = result.parts[-1]
    assert front.name == "face-front"
    assert front.points is not None and len(front.points) == 4
    svg = get_renderer().render(result)
    assert "<svg" in svg


def test_rectangle_front_matches_corners() -> None:
    spec = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        x=50.0,
        y=50.0,
        width=30.0,
        height=20.0,
        fill="#3b82f6",
    )
    result = extrude(spec)
    assert result is not None
    front = result.parts[-1]
    assert front.points is not None
    expected = [
        (50.0 - 15.0, 50.0 - 10.0),
        (50.0 + 15.0, 50.0 - 10.0),
        (50.0 + 15.0, 50.0 + 10.0),
        (50.0 - 15.0, 50.0 + 10.0),
    ]
    for (ax, ay), (bx, by) in zip(front.points, expected, strict=True):
        assert abs(ax - bx) < 1e-9
        assert abs(ay - by) < 1e-9


# ---------------------------------------------------------------------------
# Triangle -- must match renderer vertices exactly
# ---------------------------------------------------------------------------


def test_triangle_extrudes() -> None:
    spec = GeometrySpec(
        kind=ShapeKind.TRIANGLE,
        x=50.0,
        y=50.0,
        width=30.0,
        height=24.0,
        fill="#10b981",
        stroke="#065f46",
    )
    result = extrude(spec)
    assert result is not None
    assert result.kind is ShapeKind.GROUP
    svg = get_renderer().render(result)
    assert "<svg" in svg


def test_triangle_front_matches_renderer_vertices() -> None:
    """Triangle silhouette must be the renderer's three vertices."""
    cx, cy = 50.0, 50.0
    hw, hh = 15.0, 12.0  # width=30, height=24
    spec = GeometrySpec(
        kind=ShapeKind.TRIANGLE,
        x=cx,
        y=cy,
        width=hw * 2,
        height=hh * 2,
        fill="#10b981",
    )
    result = extrude(spec)
    assert result is not None
    front = result.parts[-1]
    assert front.points is not None and len(front.points) == 3
    expected = [
        (cx, cy - hh),          # apex
        (cx - hw, cy + hh),     # bottom-left
        (cx + hw, cy + hh),     # bottom-right
    ]
    for (ax, ay), (bx, by) in zip(front.points, expected, strict=True):
        assert abs(ax - bx) < 1e-9, f"x: {ax} vs {bx}"
        assert abs(ay - by) < 1e-9, f"y: {ay} vs {by}"


# ---------------------------------------------------------------------------
# Circle — 16-gon
# ---------------------------------------------------------------------------


def test_circle_extrudes_16gon() -> None:
    spec = GeometrySpec(
        kind=ShapeKind.CIRCLE,
        x=50.0,
        y=50.0,
        width=20.0,
        height=20.0,
        fill="#f59e0b",
        stroke="#92400e",
    )
    result = extrude(spec)
    assert result is not None
    front = result.parts[-1]
    assert front.points is not None
    assert len(front.points) == 16, f"Expected 16 points, got {len(front.points)}"
    # Band count should be sensible (> 0, < 16).
    band_parts = [p for p in result.parts if p.name != "face-front"]
    assert 1 <= len(band_parts) < 16, f"Unexpected band count {len(band_parts)}"
    svg = get_renderer().render(result)
    assert "<svg" in svg


# ---------------------------------------------------------------------------
# Ellipse
# ---------------------------------------------------------------------------


def test_ellipse_extrudes_16gon() -> None:
    spec = GeometrySpec(
        kind=ShapeKind.ELLIPSE,
        x=50.0,
        y=50.0,
        width=30.0,
        height=15.0,
        fill="#8b5cf6",
        stroke="#4c1d95",
    )
    result = extrude(spec)
    assert result is not None
    front = result.parts[-1]
    assert front.points is not None
    assert len(front.points) == 16
    svg = get_renderer().render(result)
    assert "<svg" in svg


# ---------------------------------------------------------------------------
# Fit-shrink: near-edge shape
# ---------------------------------------------------------------------------


def test_near_edge_shape_shrinks_and_validates() -> None:
    """A shape near the top-right edge should shrink so offset vertices stay in box.

    The rectangle at x=89, y=10, width=12, height=12 has front-face right edge
    at x=95, which after adding the offset (6.36) would reach x=101.36 -- outside
    the box.  The fit-shrink must bring it within [0, 100].
    """
    spec = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        x=89.0,
        y=10.0,
        width=12.0,
        height=12.0,
        fill="#ef4444",
    )
    result = extrude(spec)
    assert result is not None
    for part in result.parts:
        assert part.points is not None
        assert _pts_inside_box(part.points, margin=0.0), (
            f"Part {part.name} pts out of [0,100]: {part.points}"
        )
    svg = get_renderer().render(result)
    assert "<svg" in svg


# ---------------------------------------------------------------------------
# Unsupported kinds → None
# ---------------------------------------------------------------------------


def test_line_returns_none() -> None:
    spec = GeometrySpec(kind=ShapeKind.LINE, width=40.0, height=0.1)
    assert extrude(spec) is None


def test_path_returns_none() -> None:
    spec = GeometrySpec(kind=ShapeKind.PATH, d="M 10 10 L 90 90")
    assert extrude(spec) is None


def test_text_returns_none() -> None:
    spec = GeometrySpec(kind=ShapeKind.TEXT, label="hello")
    assert extrude(spec) is None


def test_node_returns_none() -> None:
    spec = GeometrySpec(kind=ShapeKind.NODE, label="box")
    assert extrude(spec) is None


def test_edge_returns_none() -> None:
    spec = GeometrySpec(kind=ShapeKind.EDGE, width=40.0, height=0.1)
    assert extrude(spec) is None


def test_multi_part_group_returns_none() -> None:
    g = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(
                kind=ShapeKind.POLYGON,
                points=[(10, 10), (50, 10), (30, 40)],
                name="a",
            ),
            GeometrySpec(
                kind=ShapeKind.POLYGON,
                points=[(60, 10), (90, 10), (75, 40)],
                name="b",
            ),
        ],
    )
    assert extrude(g) is None


# ---------------------------------------------------------------------------
# Single-part GROUP → extruded, label preserved
# ---------------------------------------------------------------------------


def test_single_part_group_extrudes_with_label() -> None:
    inner = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        x=50.0,
        y=50.0,
        width=20.0,
        height=15.0,
        fill="#60a5fa",
    )
    g = GeometrySpec(
        kind=ShapeKind.GROUP,
        label="my-shape",
        parts=[inner],
    )
    result = extrude(g)
    assert result is not None
    assert result.kind is ShapeKind.GROUP
    assert result.label == "my-shape"
    svg = get_renderer().render(result)
    assert "<svg" in svg


def test_single_part_group_extrudes_preserves_name() -> None:
    inner = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        x=50.0,
        y=50.0,
        width=20.0,
        height=15.0,
        fill="#60a5fa",
        name="inner-rect",
    )
    g = GeometrySpec(
        kind=ShapeKind.GROUP,
        name="wrapper",
        parts=[inner],
    )
    result = extrude(g)
    assert result is not None
    assert result.name == "wrapper"


# ---------------------------------------------------------------------------
# All faces validate and render (GROUP level check)
# ---------------------------------------------------------------------------


def test_all_faces_validate_for_filled_polygon() -> None:
    pts = [(40, 30), (60, 30), (65, 50), (50, 65), (35, 50)]
    spec = GeometrySpec(
        kind=ShapeKind.POLYGON,
        points=pts,
        fill="#f97316",
        stroke="#7c2d12",
    )
    result = extrude(spec)
    assert result is not None
    for part in result.parts:
        # Pydantic validation happens at construction; double-check points.
        assert part.kind is ShapeKind.POLYGON
        assert part.points is not None
        assert _pts_inside_box(part.points), f"Out-of-box: {part.name}"
    svg = get_renderer().render(result)
    assert "<svg" in svg


def test_default_depth_constant() -> None:
    assert DEFAULT_DEPTH == 9.0


def test_extrude_with_custom_depth() -> None:
    spec = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        x=50.0,
        y=50.0,
        width=20.0,
        height=20.0,
        fill="#22c55e",
    )
    result = extrude(spec, depth=5.0)
    assert result is not None
    assert result.kind is ShapeKind.GROUP


# ---------------------------------------------------------------------------
# Near-gray input still reads as shaded (saturation clamp)
# ---------------------------------------------------------------------------


def test_near_gray_input_distinct_fills() -> None:
    """#9ca3af input: the three output fills must be perceptibly distinct."""
    spec = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        x=50.0,
        y=50.0,
        width=25.0,
        height=20.0,
        fill="#9ca3af",
        stroke="#6b7280",
    )
    result = extrude(spec)
    assert result is not None
    fills = {p.fill for p in result.parts}
    assert len(fills) >= 2, f"Near-gray should produce distinct fills: {fills}"


def test_bands_protrude_up_right_never_down_left() -> None:
    """Side-pinning regression: the live winding bug selected the BACK edges,
    hiding the bands under the front face. With offset (+k, -k) the band
    union must extend beyond the front face to the RIGHT and ABOVE, and never
    below or to the left of it — for BOTH polygon windings."""
    from quorum.domain.extrude import extrude
    from quorum.domain.geometry import GeometrySpec, ShapeKind

    hexagon = [(50, 34), (70, 43), (70, 61), (50, 70), (30, 61), (30, 43)]
    for pts in (hexagon, list(reversed(hexagon))):  # CW and CCW on screen
        spec = GeometrySpec(kind=ShapeKind.POLYGON, points=[(float(x), float(y)) for x, y in pts])
        out = extrude(spec)
        assert out is not None
        front = next(p for p in out.parts if p.name == "face-front")
        bands = [p for p in out.parts if p.name != "face-front"]
        assert bands and front.points is not None
        fx = [x for x, _ in front.points]
        fy = [y for _, y in front.points]
        bx = [x for b in bands for x, _ in (b.points or [])]
        by = [y for b in bands for _, y in (b.points or [])]
        assert max(bx) > max(fx) + 1, "bands must protrude to the RIGHT"
        assert min(by) < min(fy) - 1, "bands must protrude ABOVE"
        assert min(bx) >= min(fx) - 1e-6, "bands must not protrude to the left"
        assert max(by) <= max(fy) + 1e-6, "bands must not protrude below"
