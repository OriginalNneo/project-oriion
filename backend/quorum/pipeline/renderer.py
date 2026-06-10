"""SVG renderer — a pure, deterministic geometry-spec -> SVG function.

Why a server-side renderer at all, when the client uses rough.js? Because the
node carries an ``svg`` so any client (a display that doesn't render locally, a
future export, a test) gets a picture, and because a *deterministic reference*
render is what the latency benchmark and unit tests measure (RULES.md §3/§6).

This module imports nothing from other stages. It is side-effect-free apart from
an LRU cache keyed on the spec (caching deterministic renders is explicitly
called for — RULES.md §6). The "sketchy" low-fi aesthetic (plan.md §7) is the
client's rough.js job; this server-side render is the clean, deterministic
reference that the latency benchmark and unit tests measure. Same spec -> byte-
identical SVG, always.
"""

from __future__ import annotations

from functools import lru_cache

from quorum.domain.geometry import GeometrySpec, ShapeKind

# The SVG viewport. Abstract 0..100 geometry maps into a margin-inset box so
# strokes near the edge aren't clipped.
_VIEW = 400.0
_MARGIN = 24.0
_SPAN = _VIEW - 2 * _MARGIN


def _sx(x: float) -> float:
    """Map abstract x (0..100) to SVG pixels."""
    return _MARGIN + (x / 100.0) * _SPAN


def _sy(y: float) -> float:
    return _MARGIN + (y / 100.0) * _SPAN


def _fmt(v: float) -> str:
    return f"{v:.2f}"


def _round_rect_path(x: float, y: float, w: float, h: float, r: float) -> str:
    """SVG path for a rectangle with (optionally rounded) corners."""
    r = max(0.0, min(r, w / 2, h / 2))
    if r <= 0.01:
        return f"M{_fmt(x)},{_fmt(y)} h{_fmt(w)} v{_fmt(h)} h{_fmt(-w)} Z"
    return (
        f"M{_fmt(x + r)},{_fmt(y)} "
        f"h{_fmt(w - 2 * r)} a{_fmt(r)},{_fmt(r)} 0 0 1 {_fmt(r)},{_fmt(r)} "
        f"v{_fmt(h - 2 * r)} a{_fmt(r)},{_fmt(r)} 0 0 1 {_fmt(-r)},{_fmt(r)} "
        f"h{_fmt(-(w - 2 * r))} a{_fmt(r)},{_fmt(r)} 0 0 1 {_fmt(-r)},{_fmt(-r)} "
        f"v{_fmt(-(h - 2 * r))} a{_fmt(r)},{_fmt(r)} 0 0 1 {_fmt(r)},{_fmt(-r)} Z"
    )


def _shape_body(spec: GeometrySpec) -> str:
    """Render just the shape element(s) for ``spec`` (no <svg> wrapper)."""
    cx, cy = _sx(spec.x), _sy(spec.y)
    w = spec.width / 100.0 * _SPAN
    h = spec.height / 100.0 * _SPAN
    fill = spec.fill or "none"
    stroke = spec.stroke
    sw = 2.4  # stroke width, px

    common = (
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )

    if spec.kind in (ShapeKind.RECTANGLE, ShapeKind.NODE):
        x0, y0 = cx - w / 2, cy - h / 2
        r = spec.corner_radius / 100.0 * _SPAN
        path = _round_rect_path(x0, y0, w, h, r)
        body = f'<path d="{path}" {common}/>'
        if spec.kind is ShapeKind.NODE and spec.label:
            body += _label(cx, cy, spec.label, stroke)
        return body

    if spec.kind == ShapeKind.CIRCLE:
        rad = min(w, h) / 2
        return f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(rad)}" {common}/>'

    if spec.kind == ShapeKind.ELLIPSE:
        return (
            f'<ellipse cx="{_fmt(cx)}" cy="{_fmt(cy)}" '
            f'rx="{_fmt(w / 2)}" ry="{_fmt(h / 2)}" {common}/>'
        )

    if spec.kind == ShapeKind.TRIANGLE:
        # Apex up, base down; corner_radius unused (sharp fillet handled later).
        p1 = (cx, cy - h / 2)
        p2 = (cx - w / 2, cy + h / 2)
        p3 = (cx + w / 2, cy + h / 2)
        pts = " ".join(f"{_fmt(px)},{_fmt(py)}" for px, py in (p1, p2, p3))
        return f'<polygon points="{pts}" {common}/>'

    if spec.kind in (ShapeKind.LINE, ShapeKind.EDGE):
        x0, y0 = cx - w / 2, cy
        x1, y1 = cx + w / 2, cy
        return f'<line x1="{_fmt(x0)}" y1="{_fmt(y0)}" x2="{_fmt(x1)}" y2="{_fmt(y1)}" {common}/>'

    # Unknown kind: render nothing rather than crash the loop.
    return f"<!-- unsupported shape: {spec.kind} -->"


def _label(cx: float, cy: float, text: str, color: str) -> str:
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<text x="{_fmt(cx)}" y="{_fmt(cy + 4)}" text-anchor="middle" '
        f'font-family="ui-sans-serif, system-ui" font-size="16" fill="{color}">{safe}</text>'
    )


@lru_cache(maxsize=512)
def _render_cached(cache_key: str) -> str:
    spec = GeometrySpec.model_validate_json(cache_key)
    body = _shape_body(spec)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_fmt(_VIEW)} {_fmt(_VIEW)}" '
        f'width="100%" height="100%" role="img">{body}</svg>'
    )


class SvgRenderer:
    """Default :class:`~quorum.pipeline.interfaces.Renderer` implementation."""

    def render(self, spec: GeometrySpec) -> str:
        # Cache on the canonical JSON of the spec — identical geometry, one render.
        return _render_cached(spec.cache_key())

    @staticmethod
    def cache_clear() -> None:
        _render_cached.cache_clear()


_DEFAULT = SvgRenderer()


def get_renderer() -> SvgRenderer:
    """Return the process renderer. (No env switch yet — one impl in Phase 0.)"""
    return _DEFAULT
