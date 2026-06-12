"""Named geometry tier — exact polygon/path generators for common shapes.

Pure functions: no I/O, no side effects. Every generated GeometrySpec is
centred at (x, y) within the given (width, height) extent and validated by
the GeometrySpec model before being returned. All polygon points stay within
the 0..100 abstract box.

Usage::

    from quorum.domain.shapes import named_shape, NAMED_SHAPES

    spec = named_shape("rhombus")          # default placement
    spec = named_shape("hexagon", x=30, y=40, width=30, height=30)

The word list (including aliases) covers plan.md §12 R4:
  rhombus / diamond, parallelogram, trapezoid / trapezium, pentagon, hexagon,
  heptagon, octagon, star (5-pt), arrow, cross / plus, semicircle, kite,
  heart, crescent.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING

from quorum.domain.geometry import GeometrySpec, ShapeKind

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def _poly(
    cx: float,
    cy: float,
    hw: float,
    hh: float,
    pts_norm: list[tuple[float, float]],
) -> GeometrySpec:
    """Build a POLYGON GeometrySpec from normalised points in [-1,1] space.

    ``pts_norm`` coordinates are in the [-1,1] symmetric unit box; they are
    mapped to the abstract 0..100 space via the supplied centre + half-extents.
    """
    points = [(cx + px * hw, cy + py * hh) for px, py in pts_norm]
    # Clamp to the 0..100 box to satisfy the model validator.
    points = [(min(100.0, max(0.0, x)), min(100.0, max(0.0, y))) for x, y in points]
    return GeometrySpec(
        kind=ShapeKind.POLYGON,
        x=cx,
        y=cy,
        width=hw * 2,
        height=hh * 2,
        points=points,
    )


def _regular_polygon(
    n: int,
    cx: float,
    cy: float,
    hw: float,
    hh: float,
    start_angle_deg: float = 90.0,
) -> GeometrySpec:
    """Regular n-gon, vertex at start_angle_deg from the positive x-axis."""
    start = math.radians(start_angle_deg)
    angles = [start - 2 * math.pi * k / n for k in range(n)]
    pts_norm = [(math.cos(a), -math.sin(a)) for a in angles]
    return _poly(cx, cy, hw, hh, pts_norm)


# ---------------------------------------------------------------------------
# Individual generators
# ---------------------------------------------------------------------------


def _rhombus(x: float, y: float, w: float, h: float) -> GeometrySpec:
    hw, hh = w / 2, h / 2
    return _poly(x, y, hw, hh, [(0.0, -1.0), (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0)])


def _parallelogram(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """A parallelogram leaning right: top edge shifted 20% of width to the right."""
    hw, hh = w / 2, h / 2
    # shear offset = 20 % of half-width in norm units
    s = 0.25
    pts_norm: list[tuple[float, float]] = [
        (-1.0 + s, -1.0),   # top-left
        (1.0 + s, -1.0),    # top-right
        (1.0 - s, 1.0),     # bottom-right
        (-1.0 - s, 1.0),    # bottom-left
    ]
    # clamp to normalised [-1,1] so extreme sizes don't break the 0..100 box
    pts_norm = [(min(1.0, max(-1.0, px)), min(1.0, max(-1.0, py))) for px, py in pts_norm]
    return _poly(x, y, hw, hh, pts_norm)


def _trapezoid(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """Isosceles trapezoid: top edge is 60 % of bottom edge width."""
    hw, hh = w / 2, h / 2
    top = 0.6
    pts_norm: list[tuple[float, float]] = [
        (-top, -1.0),
        (top, -1.0),
        (1.0, 1.0),
        (-1.0, 1.0),
    ]
    return _poly(x, y, hw, hh, pts_norm)


def _pentagon(x: float, y: float, w: float, h: float) -> GeometrySpec:
    hw, hh = w / 2, h / 2
    return _regular_polygon(5, x, y, hw, hh, start_angle_deg=90.0)


def _hexagon(x: float, y: float, w: float, h: float) -> GeometrySpec:
    hw, hh = w / 2, h / 2
    return _regular_polygon(6, x, y, hw, hh, start_angle_deg=90.0)


def _heptagon(x: float, y: float, w: float, h: float) -> GeometrySpec:
    hw, hh = w / 2, h / 2
    return _regular_polygon(7, x, y, hw, hh, start_angle_deg=90.0)


def _octagon(x: float, y: float, w: float, h: float) -> GeometrySpec:
    hw, hh = w / 2, h / 2
    return _regular_polygon(8, x, y, hw, hh, start_angle_deg=90.0)


def _star(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """5-pointed star: inner radius ≈ 40 % of outer."""
    hw, hh = w / 2, h / 2
    outer = 1.0
    inner = 0.4
    pts_norm: list[tuple[float, float]] = []
    for k in range(5):
        # outer point
        ao = math.radians(90 - 72 * k)
        pts_norm.append((outer * math.cos(ao), -outer * math.sin(ao)))
        # inner valley
        ai = math.radians(90 - 72 * k - 36)
        pts_norm.append((inner * math.cos(ai), -inner * math.sin(ai)))
    return _poly(x, y, hw, hh, pts_norm)


def _arrow(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """Rightward-pointing arrow."""
    hw, hh = w / 2, h / 2
    # shaft height = 40 % of total height; head width = 40 % of total width
    sh = 0.4  # shaft half-height
    hd = 0.4  # head depth (from right edge toward left)
    pts_norm = [
        (-1, -sh),   # shaft top-left
        (1 - hd, -sh),  # shaft top-right (before head)
        (1 - hd, -1),   # head top
        (1, 0),         # arrow tip
        (1 - hd, 1),    # head bottom
        (1 - hd, sh),   # shaft bottom-right
        (-1, sh),    # shaft bottom-left
    ]
    return _poly(x, y, hw, hh, pts_norm)


def _cross(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """Plus/cross shape with arm thickness ≈ 30 % of extent."""
    hw, hh = w / 2, h / 2
    t = 0.3  # half-thickness of each arm
    pts_norm = [
        (-t, -1),
        (t, -1),
        (t, -t),
        (1, -t),
        (1, t),
        (t, t),
        (t, 1),
        (-t, 1),
        (-t, t),
        (-1, t),
        (-1, -t),
        (-t, -t),
    ]
    return _poly(x, y, hw, hh, pts_norm)


def _semicircle(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """Upper semicircle (flat edge at the bottom) as a PATH."""
    # We use the PATH kind so the arc is rendered smoothly by both renderers.
    rx = w / 2
    ry = h  # full height = radius in y direction (semicircle occupies full h)
    # Centre so the flat base is at y + h/2 and apex is at y - h/2.
    # In the 0..100 abstract box:
    #   left  = x - rx
    #   right = x + rx
    #   base_y = y + h/2      (clamped)
    lx = min(100.0, max(0.0, x - rx))
    rx_right = min(100.0, max(0.0, x + rx))
    base_y = min(100.0, max(0.0, y + h / 2))

    # SVG arc: M lx,base_y  A rx,ry 0 1 1 rx_right,base_y  Z
    # large-arc-flag = 1, sweep-flag = 1 → upper arc
    d = (
        f"M {lx:.4g} {base_y:.4g} "
        f"A {rx:.4g} {ry:.4g} 0 1 1 {rx_right:.4g} {base_y:.4g} Z"
    )
    return GeometrySpec(kind=ShapeKind.PATH, x=x, y=y, width=w, height=h, d=d)


def _kite(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """Kite: narrow at top, widest at 30 % down, narrow at bottom."""
    hw, hh = w / 2, h / 2
    # widest point is at -0.4 in normalised y (above centre)
    wp = -0.4
    pts_norm: list[tuple[float, float]] = [
        (0.0, -1.0),        # top apex
        (1.0, wp),          # right widest point
        (0.0, 1.0),         # bottom apex
        (-1.0, wp),         # left widest point
    ]
    return _poly(x, y, hw, hh, pts_norm)


def _heart(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """Heart shape via cubic bezier PATH."""
    # Classic heart: two lobes at top, point at bottom.
    # Coordinates are in the abstract 0..100 box, centred at (x, y).
    hw, hh = w / 2, h / 2
    # Key landmarks:
    top_y = y - hh         # top of lobes
    mid_y = y - hh * 0.2   # where the two lobes meet at the centre top
    wide_y = y + hh * 0.2  # widest lateral point
    tip_y = y + hh         # bottom tip
    cx_ = x                # horizontal centre
    lobe_xo = hw * 0.5     # x-offset of each lobe centre from mid
    lobe_xa = hw            # maximum x reach

    # We'll use a symmetric path:
    # M cx_,mid_y  (start at the dip between the two lobes)
    # C left-top → left-outer → bottom  (left lobe + left side)
    # C right-outer → right-top → back  (right side + right lobe)
    # Z

    # Clamp all coords to 0..100
    def _c(v: float) -> float:
        return min(100.0, max(0.0, v))

    # Left lobe control points
    lcp1x, lcp1y = _c(cx_ - lobe_xo * 0.6), _c(top_y)
    lcp2x, lcp2y = _c(cx_ - lobe_xa * 1.05), _c(wide_y)
    # Midpoint of left arc end = leftmost point of bottom curve
    lendx, lendy = _c(cx_), _c(tip_y)

    # Right lobe (mirror)
    rcp1x, rcp1y = _c(cx_ + lobe_xo * 0.6), _c(top_y)
    rcp2x, rcp2y = _c(cx_ + lobe_xa * 1.05), _c(wide_y)

    startx, starty = _c(cx_), _c(mid_y)

    # Build the path using absolute cubic bezier commands:
    # M start
    # C c1 c2 end  — left lobe
    # C c3 c4 start  — right lobe (back to start)
    # Z
    d = (
        f"M {startx:.4g} {starty:.4g} "
        f"C {lcp1x:.4g} {lcp1y:.4g} {lcp2x:.4g} {lcp2y:.4g} {lendx:.4g} {lendy:.4g} "
        f"C {rcp2x:.4g} {rcp2y:.4g} {rcp1x:.4g} {rcp1y:.4g} {startx:.4g} {starty:.4g} Z"
    )
    return GeometrySpec(kind=ShapeKind.PATH, x=x, y=y, width=w, height=h, d=d)


def _crescent(x: float, y: float, w: float, h: float) -> GeometrySpec:
    """Crescent moon: large left-facing arc minus a smaller inner arc."""
    # We build this as a PATH with two arcs:
    # outer arc (full circle outline from top to bottom going left)
    # inner arc (smaller circle, going the other direction = cutting out the middle)
    rx_o = w / 2
    ry_o = h / 2
    # inner arc is shifted right by ~35% of width, slightly smaller
    shift = w * 0.3
    rx_i = rx_o * 0.85
    ry_i = ry_o * 0.85

    top_y = y - ry_o
    bot_y = y + ry_o
    # inner arc: offset to the right so it doesn't completely overlap
    inner_top_y = y - ry_i
    inner_bot_y = y + ry_i
    inner_left_x = x - rx_o + shift

    def _c(v: float) -> float:
        return min(100.0, max(0.0, v))

    # outer arc: start at top-right of outer circle, sweep counterclockwise
    outer_sx, outer_sy = _c(x + rx_o), _c(top_y)
    outer_ex, outer_ey = _c(x + rx_o), _c(bot_y)

    # inner arc: from bottom of inner circle back to top (reverse direction)
    inner_ex, inner_ey = _c(inner_left_x), _c(inner_top_y)
    inner_start_x, inner_start_y = _c(inner_left_x), _c(inner_bot_y)

    d = (
        f"M {outer_sx:.4g} {outer_sy:.4g} "
        f"A {_c(rx_o):.4g} {_c(ry_o):.4g} 0 1 0 {outer_ex:.4g} {outer_ey:.4g} "
        f"L {inner_start_x:.4g} {inner_start_y:.4g} "
        f"A {_c(rx_i):.4g} {_c(ry_i):.4g} 0 1 1 {inner_ex:.4g} {inner_ey:.4g} Z"
    )
    return GeometrySpec(kind=ShapeKind.PATH, x=x, y=y, width=w, height=h, d=d)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Mapping: canonical spoken word → generator function
# (signature: x, y, width, height → GeometrySpec)
_Generator = Callable[[float, float, float, float], GeometrySpec]

NAMED_SHAPES: dict[str, _Generator] = {
    "rhombus": _rhombus,
    "diamond": _rhombus,          # alias
    "parallelogram": _parallelogram,
    "trapezoid": _trapezoid,
    "trapezium": _trapezoid,      # alias (British English)
    "pentagon": _pentagon,
    "hexagon": _hexagon,
    "heptagon": _heptagon,
    "octagon": _octagon,
    "star": _star,
    "arrow": _arrow,
    "cross": _cross,
    "plus": _cross,               # alias
    "semicircle": _semicircle,
    "kite": _kite,
    "heart": _heart,
    "crescent": _crescent,
}


def named_shape(
    word: str,
    *,
    x: float = 50.0,
    y: float = 52.0,
    width: float = 46.0,
    height: float = 36.0,
) -> GeometrySpec | None:
    """Return an exact GeometrySpec for *word*, or None if unrecognised.

    Parameters
    ----------
    word:
        A canonical spoken word (or alias) from NAMED_SHAPES.
    x, y:
        Centre of the shape in the 0..100 abstract box.
    width, height:
        Extent of the bounding box.  The shape is inscribed within this box
        and all vertices are within the 0..100 global space.
    """
    gen = NAMED_SHAPES.get(word.lower())
    if gen is None:
        return None
    return gen(x, y, width, height)
