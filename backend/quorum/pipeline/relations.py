"""Deterministic geometric-relation snapping for LLM-emitted scenes.

LLMs supply *intent* and rough placement; they cannot be trusted with
arithmetic (a live "line tangential to the circle" came back 7 units off).
When the utterance names an exact relation, the numbers are OUR job:

* **tangent** — every straight two-point line in the emitted group is
  translated along its own normal so its distance from the circle's center
  equals the radius exactly. Direction, length, and which side of the circle
  it sits on are preserved — only the perpendicular offset is corrected.

Pure functions over :class:`GeometrySpec`; no I/O, trivially testable.
Other relations (perpendicular/parallel/concentric) remain prompt-guided
until a live failure motivates snapping them too — keep this surgical.
"""

from __future__ import annotations

import re

from quorum.domain.geometry import GeometrySpec, ShapeKind

_TANGENT_RE = re.compile(r"\b(?:tangent\w*|tangential)\b")
_TWO_POINT_PATH_RE = re.compile(
    r"^M\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*"
    r"L\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*Z?$"
)


def snap_relations(text: str, geom: GeometrySpec | None) -> GeometrySpec | None:
    """Enforce exact relations the utterance asks for. Returns the (possibly
    rebuilt) spec; anything it can't confidently fix passes through unchanged."""
    if geom is None or geom.kind is not ShapeKind.GROUP or not _TANGENT_RE.search(
        text.lower()
    ):
        return geom
    circles = [p for p in geom.parts if p.kind in (ShapeKind.CIRCLE, ShapeKind.ELLIPSE)]
    if not circles:
        return geom
    circle = circles[-1]  # the most recently mentioned/added circle
    changed = False
    parts: list[GeometrySpec] = []
    for part in geom.parts:
        snapped = _snap_tangent(part, circle)
        changed = changed or snapped is not part
        parts.append(snapped)
    return geom.model_copy(update={"parts": parts}) if changed else geom


def _snap_tangent(part: GeometrySpec, circle: GeometrySpec) -> GeometrySpec:
    """Translate a straight 2-point path to exact tangency with `circle`."""
    if part.kind is not ShapeKind.PATH or not part.d:
        return part
    m = _TWO_POINT_PATH_RE.match(part.d.strip())
    if m is None:
        return part
    x1, y1, x2, y2 = (float(g) for g in m.groups())
    cx, cy, r = circle.x, circle.y, circle.width / 2
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-6 or r < 1e-6:
        return part
    # unit normal; signed distance from the line to the circle center
    nx, ny = -dy / length, dx / length
    s = nx * (cx - x1) + ny * (cy - y1)
    side = 1.0 if s >= 0 else -1.0
    shift = s - side * r  # move so the signed distance becomes side*r exactly
    if abs(shift) < 1e-3:
        return part  # already tangent
    x1, y1, x2, y2 = x1 + shift * nx, y1 + shift * ny, x2 + shift * nx, y2 + shift * ny
    if not all(0.0 <= v <= 100.0 for v in (x1, y1, x2, y2)):
        # sliding the endpoints along the line direction keeps tangency intact;
        # if even that can't fit, shorten the segment around the touch point —
        # tangency IS the meaning, the length is incidental. Only if the box
        # leaves no visible chord do we drop the correction.
        slid = _slide_into_box(x1, y1, x2, y2) or _shorten_into_box(
            x1, y1, x2, y2, cx, cy
        )
        if slid is None:
            return part
        x1, y1, x2, y2 = slid
    d = f"M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}"
    return part.model_copy(
        update={
            "d": d,
            "x": round((x1 + x2) / 2, 1),
            "y": round((y1 + y2) / 2, 1),
            "width": round(max(abs(x2 - x1), 1.0), 1),
            "height": round(max(abs(y2 - y1), 1.0), 1),
        }
    )


def _slide_into_box(
    x1: float, y1: float, x2: float, y2: float
) -> tuple[float, float, float, float] | None:
    """Translate the segment along its own direction so it fits 0..100.

    Sliding along the line keeps tangency intact (the perpendicular offset is
    untouched). Solve the feasible interval for the slide amount ``t`` from
    every endpoint-coordinate constraint ``0 <= v + t*u <= 100``; pick the
    feasible ``t`` closest to zero. Empty interval -> can't fit -> None.
    """
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    lo, hi = float("-inf"), float("inf")
    for v, u in ((x1, ux), (x2, ux), (y1, uy), (y2, uy)):
        if abs(u) < 1e-9:
            if not (0.0 <= v <= 100.0):
                return None
            continue
        t0, t1 = (0.0 - v) / u, (100.0 - v) / u
        if t0 > t1:
            t0, t1 = t1, t0
        lo, hi = max(lo, t0), min(hi, t1)
    if lo > hi:
        return None
    t = min(max(0.0, lo), hi)
    return (x1 + t * ux, y1 + t * uy, x2 + t * ux, y2 + t * uy)


_MIN_VISIBLE_LEN = 5.0


def _shorten_into_box(
    x1: float, y1: float, x2: float, y2: float, cx: float, cy: float
) -> tuple[float, float, float, float] | None:
    """Shorten the (already tangent) segment to the chord the box allows.

    Parametrize points on the segment's infinite line as ``p(t) = p1 + t*u``;
    intersect every coordinate constraint ``0 <= p(t) <= 100`` to get the
    feasible chord ``[lo, hi]``. Keep the original length when it fits,
    otherwise the whole chord, centered as close to the tangency touch point
    (the projection of the circle center) as the chord permits — a tangent
    that doesn't reach its touch point reads as a floating line.
    """
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    lo, hi = float("-inf"), float("inf")
    for v, u in ((x1, ux), (y1, uy)):
        if abs(u) < 1e-9:
            if not (0.0 <= v <= 100.0):
                return None
            continue
        t0, t1 = (0.0 - v) / u, (100.0 - v) / u
        if t0 > t1:
            t0, t1 = t1, t0
        lo, hi = max(lo, t0), min(hi, t1)
    if hi - lo < _MIN_VISIBLE_LEN:
        return None
    keep = min(length, hi - lo)
    t_touch = ux * (cx - x1) + uy * (cy - y1)
    mid = min(max(t_touch, lo + keep / 2), hi - keep / 2)
    a, b = mid - keep / 2, mid + keep / 2
    return (x1 + a * ux, y1 + a * uy, x1 + b * ux, y1 + b * uy)
