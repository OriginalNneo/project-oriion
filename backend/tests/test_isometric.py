"""Tests for deterministic isometric projection (plan.md D3).

Covers:
- Single box: exactly 3 visible faces, distinct shades (light > mid > dark),
  all points in 0..100, renders to <svg.
- Hidden faces (3 back faces of a box) are absent.
- Two-box assembly: z-sort order (nearer box faces come later in parts list).
- Colored solid: red box yields three red-ish faces with correct lightness order.
- Wedge: coherent visible faces, all in 0..100, renders.
- Cylinder: body PATH + top ELLIPSE, path validates, renders.
- Empty input → None; unknown shape → ignored/None.
- Fit guarantee: coordinates in [0, 100] even for far-placed/large solids.
- Determinism: same input → identical output (called twice).
"""

from __future__ import annotations

from quorum.domain import pathdata
from quorum.domain.color import parse_hex, rgb_to_hsl
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.isometric import Solid, project_solids
from quorum.pipeline.renderer import get_renderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lightness(hex_color: str) -> float:
    rgb = parse_hex(hex_color)
    assert rgb is not None, f"not a hex color: {hex_color!r}"
    _, _, li = rgb_to_hsl(*rgb)
    return li


def _hue(hex_color: str) -> float:
    rgb = parse_hex(hex_color)
    assert rgb is not None
    h, _, _ = rgb_to_hsl(*rgb)
    return h


def _all_pts_in_box(parts: list[GeometrySpec]) -> bool:
    """Return True if all polygon points are in [0, 100]."""
    for part in parts:
        if part.kind is ShapeKind.POLYGON:
            assert part.points is not None
            for px, py in part.points:
                if not (0.0 <= px <= 100.0 and 0.0 <= py <= 100.0):
                    return False
    return True


def _render_svg(spec: GeometrySpec) -> str:
    return get_renderer().render(spec)


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_input_returns_none() -> None:
    assert project_solids([]) is None


# ---------------------------------------------------------------------------
# Unknown shape
# ---------------------------------------------------------------------------


def test_unknown_shape_alone_returns_none() -> None:
    s = Solid(shape="teapot", x=0, y=0, z=0, w=10, d=10, h=10)
    assert project_solids([s]) is None


def test_unknown_shape_skipped_with_valid() -> None:
    """Unknown shape is ignored; the valid solid still projects."""
    s_bad = Solid(shape="pyramid", x=0, y=0, z=0, w=10, d=10, h=10)
    s_good = Solid(shape="box", x=0, y=0, z=0, w=10, d=10, h=10)
    result = project_solids([s_bad, s_good])
    assert result is not None
    assert result.kind is ShapeKind.GROUP


# ---------------------------------------------------------------------------
# Box: face count and culling
# ---------------------------------------------------------------------------


def test_single_box_produces_group() -> None:
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    assert result.kind is ShapeKind.GROUP


def test_single_box_exactly_3_faces() -> None:
    """A box has exactly 3 visible faces from direction (1,1,1): top/front/right."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    assert len(result.parts) == 3, (
        f"Expected 3 faces, got {len(result.parts)}: "
        f"{[p.name for p in result.parts]}"
    )


def test_single_box_hidden_faces_absent() -> None:
    """The 3 back faces (-x, -y, -z normals) must not be in the output."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36, name="mybox")
    result = project_solids([s])
    assert result is not None
    names = [p.name for p in result.parts]
    # back faces have -x / -y / -z normals — they are never in the output
    assert all(
        role not in (n or "") for n in names
        for role in ("-left", "-bottom", "-back")
    ), f"Unexpected back faces in output: {names}"


def test_single_box_face_names() -> None:
    """Part names should include 'top', 'front', 'right' roles."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36, name="cube")
    result = project_solids([s])
    assert result is not None
    names = [p.name or "" for p in result.parts]
    assert any("top" in n for n in names), f"No top face: {names}"
    assert any("front" in n for n in names), f"No front face: {names}"
    assert any("right" in n for n in names), f"No right face: {names}"


# ---------------------------------------------------------------------------
# Box: shading
# ---------------------------------------------------------------------------


def test_single_box_three_distinct_shades() -> None:
    """Top/front/right faces must have three distinct fill colors."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    fills = [p.fill for p in result.parts]
    assert len(set(fills)) == 3, f"Expected 3 distinct fills, got: {set(fills)}"


def test_single_box_lightness_ordering() -> None:
    """Top face (light) > front face (mid) > right face (dark) in lightness."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36, name="cube")
    result = project_solids([s])
    assert result is not None
    parts_by_role: dict[str, float] = {}
    for p in result.parts:
        assert p.fill is not None
        name = p.name or ""
        if "top" in name:
            parts_by_role["top"] = _lightness(p.fill)
        elif "front" in name:
            parts_by_role["front"] = _lightness(p.fill)
        elif "right" in name:
            parts_by_role["right"] = _lightness(p.fill)
    assert "top" in parts_by_role and "front" in parts_by_role and "right" in parts_by_role
    assert parts_by_role["top"] > parts_by_role["front"], "Top must be lighter than front"
    assert parts_by_role["front"] > parts_by_role["right"], "Front must be lighter than right"


# ---------------------------------------------------------------------------
# Box: coordinate bounds
# ---------------------------------------------------------------------------


def test_single_box_all_pts_in_0_100() -> None:
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    assert _all_pts_in_box(result.parts), "Some polygon points outside [0,100]"


def test_single_box_renders_to_svg() -> None:
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    svg = _render_svg(result)
    assert svg.startswith("<svg"), f"Not an SVG: {svg[:40]}"


# ---------------------------------------------------------------------------
# Box: colored solid
# ---------------------------------------------------------------------------


def test_colored_box_red_hue_preserved() -> None:
    """Red box → all three faces stay near red hue."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36, color="#dc2626")
    result = project_solids([s])
    assert result is not None
    src_h = _hue("#dc2626")
    for part in result.parts:
        assert part.fill is not None
        fh = _hue(part.fill)
        diff = min(abs(fh - src_h), 1.0 - abs(fh - src_h))
        assert diff < 0.06, f"Hue diverged: {part.fill} (h={fh:.3f} vs src={src_h:.3f})"


def test_colored_box_lightness_order_preserved() -> None:
    """Colored box: top > front > right lightness ordering survives tinting."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36, color="#2563eb", name="b")
    result = project_solids([s])
    assert result is not None
    by_role: dict[str, float] = {}
    for p in result.parts:
        assert p.fill is not None
        name = p.name or ""
        if "top" in name:
            by_role["top"] = _lightness(p.fill)
        elif "front" in name:
            by_role["front"] = _lightness(p.fill)
        elif "right" in name:
            by_role["right"] = _lightness(p.fill)
    assert by_role["top"] > by_role["front"] > by_role["right"]


# ---------------------------------------------------------------------------
# Two-box z-sort
# ---------------------------------------------------------------------------


def test_two_box_zsort_nearer_faces_come_later() -> None:
    """Nearer box (higher x+y+z centroid) must have its faces AFTER far box."""
    # Box A: at origin (far from viewer)
    far = Solid(shape="box", x=0, y=0, z=0, w=10, d=10, h=10, name="far")
    # Box B: offset further toward viewer (higher x, y, z)
    near = Solid(shape="box", x=15, y=0, z=15, w=10, d=10, h=10, name="near")
    result = project_solids([far, near])
    assert result is not None

    # Find the first and last index of each solid's parts
    far_indices = [i for i, p in enumerate(result.parts) if (p.name or "").startswith("far")]
    near_indices = [i for i, p in enumerate(result.parts) if (p.name or "").startswith("near")]

    assert far_indices, "Far box produced no parts"
    assert near_indices, "Near box produced no parts"
    # All far-box parts should come before all near-box parts
    assert max(far_indices) < min(near_indices), (
        f"Far box parts ({far_indices}) not all before near box ({near_indices})"
    )


# ---------------------------------------------------------------------------
# Wedge
# ---------------------------------------------------------------------------


def test_wedge_produces_group() -> None:
    s = Solid(shape="wedge", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    assert result.kind is ShapeKind.GROUP


def test_wedge_at_least_one_face() -> None:
    s = Solid(shape="wedge", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    assert len(result.parts) >= 1


def test_wedge_all_pts_in_0_100() -> None:
    s = Solid(shape="wedge", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    assert _all_pts_in_box(result.parts), "Wedge polygon points outside [0,100]"


def test_wedge_renders_to_svg() -> None:
    s = Solid(shape="wedge", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    svg = _render_svg(result)
    assert svg.startswith("<svg")


def test_wedge_polygon_faces_each_have_3_or_4_points() -> None:
    s = Solid(shape="wedge", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    for part in result.parts:
        if part.kind is ShapeKind.POLYGON:
            assert part.points is not None
            assert 3 <= len(part.points) <= 4, (
                f"Wedge face {part.name} has {len(part.points)} points"
            )


# ---------------------------------------------------------------------------
# Cylinder
# ---------------------------------------------------------------------------


def test_cylinder_produces_group() -> None:
    s = Solid(shape="cylinder", x=0, y=0, z=0, w=20, d=20, h=42)
    result = project_solids([s])
    assert result is not None
    assert result.kind is ShapeKind.GROUP


def test_cylinder_has_body_and_top() -> None:
    """Cylinder must produce at least one PATH (body) and one ELLIPSE (top)."""
    s = Solid(shape="cylinder", x=0, y=0, z=0, w=20, d=20, h=42, name="cyl")
    result = project_solids([s])
    assert result is not None
    kinds = [p.kind for p in result.parts]
    assert ShapeKind.PATH in kinds, f"No PATH part for cylinder: {kinds}"
    assert ShapeKind.ELLIPSE in kinds, f"No ELLIPSE part for cylinder: {kinds}"


def test_cylinder_body_path_validates() -> None:
    """The body PATH's `d` must parse cleanly via pathdata.parse."""
    s = Solid(shape="cylinder", x=0, y=0, z=0, w=20, d=20, h=42, name="cyl")
    result = project_solids([s])
    assert result is not None
    for part in result.parts:
        if part.kind is ShapeKind.PATH:
            assert part.d is not None
            # Should not raise
            cmds = pathdata.parse(part.d)
            assert len(cmds) > 0


def test_cylinder_renders_to_svg() -> None:
    s = Solid(shape="cylinder", x=0, y=0, z=0, w=20, d=20, h=42)
    result = project_solids([s])
    assert result is not None
    svg = _render_svg(result)
    assert svg.startswith("<svg")


def test_cylinder_top_ellipse_in_box() -> None:
    """ELLIPSE x, y, width, height must be within the 0..100 box constraints."""
    s = Solid(shape="cylinder", x=0, y=0, z=0, w=20, d=20, h=42)
    result = project_solids([s])
    assert result is not None
    for part in result.parts:
        if part.kind is ShapeKind.ELLIPSE:
            # Center must be in [0,100]; width/height > 0 and <= 100
            assert 0 <= part.x <= 100, f"Ellipse x={part.x} out of range"
            assert 0 <= part.y <= 100, f"Ellipse y={part.y} out of range"
            assert 0 < part.width <= 100, f"Ellipse width={part.width} invalid"
            assert 0 < part.height <= 100, f"Ellipse height={part.height} invalid"


# ---------------------------------------------------------------------------
# Fit guarantee for far-placed / large solids
# ---------------------------------------------------------------------------


def test_fit_far_placed_solid_in_box() -> None:
    """Solid at large world coords still produces coords in [0,100]."""
    s = Solid(shape="box", x=1000, y=500, z=800, w=50, d=50, h=50)
    result = project_solids([s])
    assert result is not None
    assert _all_pts_in_box(result.parts)


def test_fit_very_large_solid_in_box() -> None:
    """Very large solid still fits in [0,100]."""
    s = Solid(shape="box", x=0, y=0, z=0, w=1000, d=1000, h=1000)
    result = project_solids([s])
    assert result is not None
    assert _all_pts_in_box(result.parts)


def test_fit_negative_coords_solid_in_box() -> None:
    """Solid at negative world coords still fits."""
    s = Solid(shape="box", x=-100, y=-50, z=-200, w=30, d=30, h=30)
    result = project_solids([s])
    assert result is not None
    assert _all_pts_in_box(result.parts)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_single_box() -> None:
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36, color="#10b981", name="det")
    r1 = project_solids([s])
    r2 = project_solids([s])
    assert r1 is not None and r2 is not None
    assert r1 == r2, "project_solids is not deterministic for single box"


def test_determinism_multi_solid() -> None:
    solids = [
        Solid(shape="box", x=0, y=0, z=0, w=20, d=20, h=20, name="a"),
        Solid(shape="box", x=25, y=0, z=25, w=15, d=15, h=15, name="b"),
        Solid(shape="cylinder", x=10, y=0, z=10, w=10, d=10, h=30, name="c"),
    ]
    r1 = project_solids(solids)
    r2 = project_solids(solids)
    assert r1 is not None and r2 is not None
    assert r1 == r2, "project_solids is not deterministic for multi-solid assembly"


# ---------------------------------------------------------------------------
# Fill style SOLID on all polygon faces
# ---------------------------------------------------------------------------


def test_box_fill_style_solid() -> None:
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36)
    result = project_solids([s])
    assert result is not None
    from quorum.domain.geometry import FillStyle
    for part in result.parts:
        if part.kind is ShapeKind.POLYGON:
            assert part.fill_style is FillStyle.SOLID, (
                f"Part {part.name} has fill_style={part.fill_style}"
            )


# ---------------------------------------------------------------------------
# Near-gray default color
# ---------------------------------------------------------------------------


def test_default_color_produces_shaded_faces() -> None:
    """Solid with color=None must still produce three distinct-lightness faces."""
    s = Solid(shape="box", x=0, y=0, z=0, w=36, d=36, h=36, color=None)
    result = project_solids([s])
    assert result is not None
    fills = [p.fill for p in result.parts if p.kind is ShapeKind.POLYGON]
    assert len(set(fills)) == 3, f"Expected 3 distinct gray shades, got: {set(fills)}"


# ---------------------------------------------------------------------------
# Mixed-shape assembly
# ---------------------------------------------------------------------------


def test_mixed_assembly_renders() -> None:
    """Box + cylinder + wedge assembly should render without error."""
    solids = [
        Solid(shape="box", x=0, y=0, z=0, w=30, d=30, h=20, name="base"),
        Solid(shape="cylinder", x=10, y=20, z=10, w=10, d=10, h=20, name="col"),
        Solid(shape="wedge", x=0, y=0, z=35, w=20, d=20, h=20, name="ramp"),
    ]
    result = project_solids(solids)
    assert result is not None
    svg = _render_svg(result)
    assert svg.startswith("<svg")


def test_mixed_assembly_all_pts_in_box() -> None:
    solids = [
        Solid(shape="box", x=0, y=0, z=0, w=30, d=30, h=20, name="base"),
        Solid(shape="wedge", x=35, y=0, z=0, w=20, d=20, h=15, name="wedge"),
    ]
    result = project_solids(solids)
    assert result is not None
    assert _all_pts_in_box(result.parts)


# ---------------------------------------------------------------------------
# 60-part cap (GeometrySpec.parts max_length): keep the NEAREST whole items.
# ---------------------------------------------------------------------------
def test_part_cap_keeps_nearest_whole_boxes() -> None:
    """An assembly > 60 faces is truncated to <= 60 by dropping the FARTHEST
    whole chunks (painter's order draws near last), so the nearest solid
    survives and the farthest is dropped."""
    solids = [
        Solid(shape="box", x=i * 4.0, y=0, z=i * 4.0, w=6, d=6, h=6, name=f"box-{i}")
        for i in range(25)  # 25 boxes * 3 visible faces = 75 > 60
    ]
    result = project_solids(solids)
    assert result is not None
    assert len(result.parts) <= 60
    names = {p.name for p in result.parts}
    assert any(n and n.startswith("box-24-") for n in names)  # nearest kept
    assert not any(n and n.startswith("box-0-") for n in names)  # farthest dropped


def test_part_cap_never_splits_a_cylinder_pair() -> None:
    """Truncation drops whole chunks, so every surviving cylinder keeps BOTH
    its body PATH and top ELLIPSE — #paths == #ellipses, no orphans."""
    solids = [
        Solid(shape="cylinder", x=i * 3.0, y=0, z=i * 3.0, w=5, d=5, h=8, name=f"c-{i}")
        for i in range(35)  # 35 cylinders * 2 parts = 70 > 60
    ]
    result = project_solids(solids)
    assert result is not None
    assert len(result.parts) <= 60
    n_paths = sum(1 for p in result.parts if p.kind is ShapeKind.PATH)
    n_ellipses = sum(1 for p in result.parts if p.kind is ShapeKind.ELLIPSE)
    assert n_paths == n_ellipses  # no half-cylinder
