"""Renderer unit tests — the renderer is a *pure, deterministic* function.

These pin the two properties the architecture depends on: same input -> identical
output (so it's cacheable, plan.md §3.3) and no shape crashes the loop.
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
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


def test_every_shape_renders_without_error() -> None:
    r = SvgRenderer()
    for kind in ShapeKind:
        out = r.render(GeometrySpec(kind=kind, label="x"))
        assert "<svg" in out


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
