"""Deterministic geometric-relation snapping for LLM-emitted scenes.

LLMs supply *intent* and rough placement; they cannot be trusted with
arithmetic (a live "line tangential to the circle" came back 7 units off).
When the utterance names an exact relation, the numbers are OUR job:

* **tangent** — every straight two-point line in the emitted group is
  translated along its own normal so its distance from the circle's center
  equals the radius exactly. Direction, length, and which side of the circle
  it sits on are preserved — only the perpendicular offset is corrected.
* **inside** — parts the utterance adds INTO the scene ("add a red sphere
  inside") are translated (shrunk if oversized) so their box lies fully
  within the box of the parts that were already there. A live "add a red
  sphere inside" left the sphere floating next to the box.

Pure functions over :class:`GeometrySpec`; no I/O, trivially testable.
Other relations (perpendicular/parallel/concentric) remain prompt-guided
until a live failure motivates snapping them too — keep this surgical.
"""

from __future__ import annotations

import re

from quorum.domain.geometry import GeometrySpec, ShapeKind

_TANGENT_RE = re.compile(r"\b(?:tangent\w*|tangential)\b")
_INSIDE_RE = re.compile(r"\b(?:inside|into|within|in (?:it|the (?:middle|center)))\b")
_TWO_POINT_PATH_RE = re.compile(
    r"^M\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*"
    r"L\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*Z?$"
)


def snap_relations(
    text: str,
    geom: GeometrySpec | None,
    *,
    focus_geometry: GeometrySpec | None = None,
) -> GeometrySpec | None:
    """Enforce exact relations the utterance asks for. Returns the (possibly
    rebuilt) spec; anything it can't confidently fix passes through unchanged."""
    lowered = text.lower()
    geom = _snap_all_tangents(lowered, geom)
    geom = _snap_all_inside(lowered, geom, focus_geometry)
    return geom


def _snap_all_tangents(
    lowered: str, geom: GeometrySpec | None
) -> GeometrySpec | None:
    if geom is None or geom.kind is not ShapeKind.GROUP or not _TANGENT_RE.search(
        lowered
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


def _snap_all_inside(
    lowered: str,
    geom: GeometrySpec | None,
    focus_geometry: GeometrySpec | None,
) -> GeometrySpec | None:
    """Force parts added "inside" the scene to actually lie within it.

    New parts = names absent from the focused scene (the prompt demands new
    parts go LAST, so with no focus we treat the final part as the addition).
    Host box = union box of the old parts. Each new part outside the host is
    shrunk (only if oversized, to 80% of the host's smaller span) and centered
    in the host — containment IS the meaning; exact size/spot are incidental.
    """
    if geom is None or geom.kind is not ShapeKind.GROUP or len(geom.parts) < 2:
        return geom
    if not _INSIDE_RE.search(lowered):
        return geom
    if focus_geometry is not None:
        old_names = {
            p.name
            for p in (
                focus_geometry.parts
                if focus_geometry.kind is ShapeKind.GROUP
                else [focus_geometry]
            )
            if p.name
        }
        is_new = [bool(p.name) and p.name not in old_names for p in geom.parts]
        if not any(is_new) or all(is_new):
            is_new = [False] * (len(geom.parts) - 1) + [True]
    else:
        is_new = [False] * (len(geom.parts) - 1) + [True]
    host_boxes = [part_bbox(p) for p, new in zip(geom.parts, is_new, strict=True) if not new]
    if not host_boxes:
        return geom
    hx1 = min(b[0] for b in host_boxes)
    hy1 = min(b[1] for b in host_boxes)
    hx2 = max(b[2] for b in host_boxes)
    hy2 = max(b[3] for b in host_boxes)
    changed = False
    parts: list[GeometrySpec] = []
    for part, new in zip(geom.parts, is_new, strict=True):
        snapped = _contain(part, hx1, hy1, hx2, hy2) if new else part
        changed = changed or snapped is not part
        parts.append(snapped)
    return geom.model_copy(update={"parts": parts}) if changed else geom


def part_bbox(part: GeometrySpec) -> tuple[float, float, float, float]:
    """Return the axis-aligned bounding box of *part* as (x1, y1, x2, y2).

    Public so :mod:`quorum.domain.compose` and other pure-function modules can
    compute bounding boxes without duplicating the polygon-aware logic.
    """
    if part.points:
        xs = [pt[0] for pt in part.points]
        ys = [pt[1] for pt in part.points]
        return min(xs), min(ys), max(xs), max(ys)
    hw, hh = part.width / 2, part.height / 2
    return part.x - hw, part.y - hh, part.x + hw, part.y + hh


# Backwards-compatible alias — internal callers migrate to `part_bbox` but
# external code that already imported the private name continues to work.
_part_bbox = part_bbox


def _contain(
    part: GeometrySpec, hx1: float, hy1: float, hx2: float, hy2: float
) -> GeometrySpec:
    """Center `part` in the host box, shrinking it first if it can't fit.

    Rect/circle/ellipse/triangle move via x/y (+width/height when shrunk);
    polygons move via their points. Paths pass through untouched — rewriting
    curve data is the validator's domain, not a placement snap's.
    """
    x1, y1, x2, y2 = part_bbox(part)
    if hx1 <= x1 and hy1 <= y1 and x2 <= hx2 and y2 <= hy2:
        return part  # already inside
    if part.kind is ShapeKind.PATH or part.kind is ShapeKind.GROUP:
        return part
    pw, ph = x2 - x1, y2 - y1
    hw, hh = hx2 - hx1, hy2 - hy1
    if hw <= 0 or hh <= 0:
        return part
    scale = min(1.0, 0.8 * hw / pw if pw > 0 else 1.0, 0.8 * hh / ph if ph > 0 else 1.0)
    cx, cy = (hx1 + hx2) / 2, (hy1 + hy2) / 2
    if part.points:
        px, py = (x1 + x2) / 2, (y1 + y2) / 2
        points = [
            [round(cx + (pt[0] - px) * scale, 1), round(cy + (pt[1] - py) * scale, 1)]
            for pt in part.points
        ]
        return part.model_copy(
            update={
                "points": points,
                "x": round(cx, 1),
                "y": round(cy, 1),
                "width": round(max(pw * scale, 1.0), 1),
                "height": round(max(ph * scale, 1.0), 1),
            }
        )
    return part.model_copy(
        update={
            "x": round(cx, 1),
            "y": round(cy, 1),
            "width": round(max(part.width * scale, 1.0), 1),
            "height": round(max(part.height * scale, 1.0), 1),
        }
    )


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
