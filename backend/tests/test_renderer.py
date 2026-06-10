"""Renderer unit tests — the renderer is a *pure, deterministic* function.

These pin the two properties the architecture depends on: same input -> identical
output (so it's cacheable, plan.md §3.3) and no shape crashes the loop.
"""

from __future__ import annotations

from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind
from quorum.pipeline.renderer import SvgRenderer, get_renderer


def test_render_is_deterministic() -> None:
    r = SvgRenderer()
    spec = GeometrySpec(kind=ShapeKind.RECTANGLE, corner_radius=12)
    assert r.render(spec) == r.render(spec)


def test_render_produces_valid_svg_wrapper() -> None:
    r = get_renderer()
    out = r.render(GeometrySpec(kind=ShapeKind.CIRCLE))
    assert out.startswith("<svg")
    assert out.rstrip().endswith("</svg>")
    assert "viewBox" in out


def test_fillet_changes_output() -> None:
    r = SvgRenderer()
    sharp = r.render(GeometrySpec(kind=ShapeKind.RECTANGLE, corner_radius=0))
    round_ = r.render(GeometrySpec(kind=ShapeKind.RECTANGLE, corner_radius=14))
    assert sharp != round_
    # rounded rect uses arc commands; sharp uses straight h/v only
    assert " a" in round_ and " a" not in sharp


# Minimal valid payload per kind — the v2 kinds require kind-specific fields
# (validated in domain/geometry.py), so the all-kinds loop must supply them.
_PER_KIND: dict[ShapeKind, dict[str, object]] = {
    ShapeKind.POLYGON: {"points": [(10, 10), (90, 10), (50, 80)]},
    ShapeKind.PATH: {"d": "M 10 10 L 90 90"},
}


def test_every_shape_renders_without_error() -> None:
    r = SvgRenderer()
    for kind in ShapeKind:
        out = r.render(GeometrySpec(kind=kind, label="x", **_PER_KIND.get(kind, {})))
        assert "<svg" in out


def test_polygon_renders_mapped_points() -> None:
    r = SvgRenderer()
    out = r.render(GeometrySpec(kind=ShapeKind.POLYGON, points=[(10, 10), (90, 10), (50, 80)]))
    assert "<polygon" in out and "points=" in out


def test_path_renders_and_maps_into_viewport() -> None:
    r = SvgRenderer()
    out = r.render(GeometrySpec(kind=ShapeKind.PATH, d="M 0 0 L 100 100"))
    assert "<path" in out
    # 0..100 abstract coords must be mapped into the margin-inset viewport, so
    # the raw "0 0" / "100 100" must not survive verbatim.
    assert "M 0 0" not in out


def test_text_renders_label_with_font_size() -> None:
    r = SvgRenderer()
    out = r.render(GeometrySpec(kind=ShapeKind.TEXT, label="9:41", font_size=4))
    assert "<text" in out and "9:41" in out
    assert 'font-size="15.00"' in out  # 4 units * 3.75 px/unit


def test_fill_style_none_forces_no_fill() -> None:
    r = SvgRenderer()
    out = r.render(GeometrySpec(kind=ShapeKind.CIRCLE, fill="#eee", fill_style=FillStyle.NONE))
    assert 'fill="none"' in out and 'fill="#eee"' not in out


def test_group_renders_all_parts() -> None:
    r = SvgRenderer()
    scene = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(kind=ShapeKind.CIRCLE, x=50, y=66, width=34, height=34),
            GeometrySpec(kind=ShapeKind.RECTANGLE, x=50, y=32, width=24, height=24),
        ],
    )
    out = r.render(scene)
    assert "<circle" in out and "<path" in out  # both primitives in ONE svg
    assert r.render(scene) == out  # still deterministic/cacheable


def test_label_is_escaped() -> None:
    r = SvgRenderer()
    out = r.render(GeometrySpec(kind=ShapeKind.NODE, label="<a & b>"))
    assert "<a & b>" not in out
    assert "&lt;a &amp; b&gt;" in out


def test_cache_returns_identical_string_object_semantics() -> None:
    # Two distinct-but-equal specs hit the same cached render.
    r = SvgRenderer()
    a = r.render(GeometrySpec(kind=ShapeKind.TRIANGLE))
    b = r.render(GeometrySpec(kind=ShapeKind.TRIANGLE))
    assert a == b
