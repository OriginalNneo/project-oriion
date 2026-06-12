"""Deterministic 2D->3D extrusion - oblique-cabinet prism (plan.md ss13-N4).

Given a ``GeometrySpec`` for a flat shape, ``extrude`` returns a GROUP whose
parts are:
  - The receding band quads (face-band-1 ... face-band-N), back-to-front, and
  - The front face (face-front) LAST (painter's algorithm -- occludes the band).

All three faces of the prism are painted in three lightness bands derived
from the shape's own hue, so a pink hexagon comes out as three pink faces.

Unsupported kinds (LINE, PATH, TEXT, NODE, EDGE, and GROUPs with more than
one part) return ``None`` -- these stay in LLM territory for v1.  Call sites
check for ``None`` before proceeding.

Convention
----------
- Offset direction:  (+k, -k) where k = depth * 0.7071  (45-deg up-right;
  y grows DOWN in SVG, so -k = up).
- Cabinet half-scale:  DEFAULT_DEPTH = 9.0 gives a visually natural depth
  at the standard 0..100 coordinate box without shrinking the front face.
- Silhouette derivation:
    POLYGON   -> its ``points`` verbatim.
    RECTANGLE -> 4 corners derived from (x, y, width, height).
    TRIANGLE  -> apex-up, base-down: (cx, cy-h/2), (cx-w/2, cy+h/2),
                (cx+w/2, cy+h/2)  -- matches the server-side renderer exactly.
    CIRCLE    -> 16-gon inscribed in the (x, y, w, h) bounding box.
    ELLIPSE   -> 16-gon inscribed in the (x, y, w, h) bounding box.
    GROUP(1 part) -> extrude the single part; label and name propagate.
- Fit:  any translated vertex outside the 0-100 box minus a 2-unit margin
  triggers a shrink of the silhouette about its centroid uniformly before
  extruding so every vertex including the offset copy stays inside [2, 98].
- Visible-face selection:  for each edge (p_i -> p_j), compute the outward
  normal and keep the edge if  n . (1, -1) > 0  (faces the up-right offset
  direction).  "Outward" is relative to the signed-area winding; for a
  y-down CCW polygon (negative signed area) the outward normal points inward
  with the usual 2-D convention, so we flip accordingly.
- Shading:
    base color   = fill if set AND parseable; else stroke if parseable;
                   else #9ca3af (neutral gray).
    sat clamp    >= 0.18 so near-gray input still reads shaded.
    top/up-facing bands  (n_y < 0 dominant)  -> L approx 0.78
    side/right-facing bands                  -> L approx 0.38
    front face                               -> L approx 0.55
    stroke of all faces = same hue at L approx 0.22 (dark outline).
- Paint order of band quads:  sort by edge-midpoint dot with the NEGATIVE
  offset direction (-1, +1), ascending -- so the far edges paint first and
  nearer edges paint over them.
"""

from __future__ import annotations

import math

from quorum.domain.color import (
    format_hex,
    hsl_to_rgb,
    parse_hex,
    rgb_to_hsl,
)
from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind

# ---------------------------------------------------------------------------
# Public constants / API
# ---------------------------------------------------------------------------

DEFAULT_DEPTH: float = 9.0

# ---------------------------------------------------------------------------
# Shading lightness bands
# ---------------------------------------------------------------------------

_L_TOP = 0.78      # top / upward-facing receding quads (n_y < 0 dominant)
_L_SIDE = 0.38     # side / rightward-facing receding quads
_L_FRONT = 0.55    # front face (mid-tone)
_L_STROKE = 0.22   # stroke outline for all faces
_SAT_MIN = 0.18    # ensure near-grey inputs still read as shaded

# Margin requirement: every vertex must lie in [_MARGIN, 100 - _MARGIN].
_BOX_MARGIN = 2.0

# Number of polygon approximation points for CIRCLE / ELLIPSE.
_CIRCLE_SEGMENTS = 16


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _signed_area(pts: list[tuple[float, float]]) -> float:
    """Trapezoid-form shoelace. Sign convention (y-down screen coords):
    NEGATIVE = clockwise on screen, POSITIVE = counter-clockwise.

    Caught live: this form has the OPPOSITE sign of the cross-product
    shoelace sum(x_i*y_j - x_j*y_i)/2 — mixing the two conventions flipped
    every outward normal and extruded the BACK edges (bands hid behind the
    front face). The side-pinning regression test guards this now.
    """
    n = len(pts)
    total = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        total += (x1 - x0) * (y1 + y0)
    return total / 2.0


def _centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return cx, cy


def _circle_polygon(
    cx: float, cy: float, rx: float, ry: float, n: int = _CIRCLE_SEGMENTS
) -> list[tuple[float, float]]:
    """Inscribe an n-gon in the ellipse with semi-axes (rx, ry)."""
    pts = []
    for i in range(n):
        angle = 2.0 * math.pi * i / n
        pts.append((cx + rx * math.cos(angle), cy - ry * math.sin(angle)))
    return pts


def _silhouette(spec: GeometrySpec) -> list[tuple[float, float]] | None:
    """Return the silhouette polygon for the given spec, or None if unsupported."""
    kind = spec.kind

    if kind is ShapeKind.POLYGON:
        assert spec.points is not None
        return list(spec.points)

    if kind is ShapeKind.RECTANGLE:
        cx, cy = spec.x, spec.y
        hw, hh = spec.width / 2.0, spec.height / 2.0
        # CW on screen (y grows down): TL -> TR -> BR -> BL
        return [
            (cx - hw, cy - hh),
            (cx + hw, cy - hh),
            (cx + hw, cy + hh),
            (cx - hw, cy + hh),
        ]

    if kind is ShapeKind.TRIANGLE:
        # Apex up, base down -- mirrors renderer.py exactly.
        cx, cy = spec.x, spec.y
        hw, hh = spec.width / 2.0, spec.height / 2.0
        return [
            (cx, cy - hh),
            (cx - hw, cy + hh),
            (cx + hw, cy + hh),
        ]

    if kind is ShapeKind.CIRCLE:
        cx, cy = spec.x, spec.y
        r = min(spec.width, spec.height) / 2.0
        return _circle_polygon(cx, cy, r, r, _CIRCLE_SEGMENTS)

    if kind is ShapeKind.ELLIPSE:
        cx, cy = spec.x, spec.y
        rx, ry = spec.width / 2.0, spec.height / 2.0
        return _circle_polygon(cx, cy, rx, ry, _CIRCLE_SEGMENTS)

    return None


def _fit_pts(
    pts: list[tuple[float, float]], off: tuple[float, float]
) -> list[tuple[float, float]]:
    """Shrink pts about their centroid so every vertex AND its offset copy
    lies within [_BOX_MARGIN, 100 - _BOX_MARGIN].  Returns the (possibly
    unchanged) point list.

    After applying a uniform scale s about (cx, cy), the scaled front vertex
    is at (cx + rx*s, cy + ry*s) and its offset copy at (cx+rx*s+ox, cy+ry*s+oy).
    We find the largest s in (0, 1] satisfying all constraints.

    For a given (rel, anchor, limit):
        anchor + rel*s + shift <= limit  when rel > 0  =>  s <= (limit - anchor - shift) / rel
        anchor + rel*s + shift >= lo     when rel < 0  =>  s <= (lo - anchor - shift) / rel
    We only apply a bound if it is positive (zero or negative means the shape
    can never fit at this centroid; we clamp to a minimum of 0.01 at the end).
    """
    ox, oy = off
    lo = _BOX_MARGIN
    hi = 100.0 - _BOX_MARGIN

    cx, cy = _centroid(pts)

    def _apply_bound(min_s: float, rel: float, anchor: float, shift: float) -> float:
        """Tighten min_s for constraint: anchor + rel*s + shift in [lo, hi]."""
        if rel > 1e-9:
            bound = (hi - anchor - shift) / rel
            if bound > 0.0:
                min_s = min(min_s, bound)
        elif rel < -1e-9:
            bound = (lo - anchor - shift) / rel
            if bound > 0.0:
                min_s = min(min_s, bound)
        return min_s

    min_s = 1.0
    for px, py in pts:
        rx, ry = px - cx, py - cy
        # Front vertex must stay in [lo, hi].
        min_s = _apply_bound(min_s, rx, cx, 0.0)
        min_s = _apply_bound(min_s, ry, cy, 0.0)
        # Offset copy must also stay in [lo, hi].
        min_s = _apply_bound(min_s, rx, cx, ox)
        min_s = _apply_bound(min_s, ry, cy, oy)

    scale = max(0.01, min_s)
    if scale >= 1.0:
        return pts
    return [(cx + (px - cx) * scale, cy + (py - cy) * scale) for px, py in pts]


def _base_color(spec: GeometrySpec) -> tuple[float, float, float]:
    """Return (h, s, lightness) in [0,1] for the spec's base color.

    Priority: fill (if set and parseable) > stroke (if parseable) > #9ca3af.
    Saturation is clamped to >= _SAT_MIN so near-grays still shade visibly.
    """
    _FALLBACK = "#9ca3af"
    candidates = []
    if spec.fill:
        candidates.append(spec.fill)
    candidates.append(spec.stroke)
    candidates.append(_FALLBACK)

    for c in candidates:
        rgb = parse_hex(c)
        if rgb is not None:
            hue, sat, li = rgb_to_hsl(*rgb)
            sat = max(sat, _SAT_MIN)
            return hue, sat, li

    # Should never reach here since _FALLBACK always parses.
    return 0.0, _SAT_MIN, 0.55


def _make_color(hue: float, sat: float, lightness: float) -> str:
    r, g, b = hsl_to_rgb(hue, sat, lightness)
    return format_hex(r, g, b)


def _normal_outward(
    px: float, py: float, qx: float, qy: float, signed_area: float
) -> tuple[float, float]:
    """Outward-pointing normal for edge p->q.

    The normal direction depends on the winding convention. Our trapezoid
    shoelace is NEGATIVE for a clockwise-on-screen polygon (y-down), and for
    CW the outward normal of edge p->q is (dy, -dx) normalized; for CCW
    (signed_area > 0) it is (-dy, dx).
    """
    dx, dy = qx - px, qy - py
    if signed_area < 0:  # clockwise on screen
        nx, ny = dy, -dx
    else:  # counter-clockwise
        nx, ny = -dy, dx
    length = math.hypot(nx, ny)
    if length < 1e-9:
        return 0.0, 0.0
    return nx / length, ny / length


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extrude(geom: GeometrySpec, *, depth: float = DEFAULT_DEPTH) -> GeometrySpec | None:
    """Extrude *geom* into an oblique-cabinet 3-D prism.

    Returns a GROUP GeometrySpec whose parts are the prism faces in painter
    order (receding band quads back-to-front, front face last), or ``None``
    when extrusion is not supported for this kind.

    **Unsupported (returns None):**  LINE, PATH, TEXT, NODE, EDGE, and GROUP
    with more than one part.  These remain in LLM territory for v1.

    Parameters
    ----------
    geom:
        The flat GeometrySpec to extrude.
    depth:
        Depth in abstract 0-100 units.  Default is ``DEFAULT_DEPTH`` (9.0),
        which gives a visually natural cabinet depth.
    """
    # --- Handle single-part GROUP by delegating to the inner part -----------
    inner_label = geom.label
    inner_name = geom.name
    if geom.kind is ShapeKind.GROUP:
        if len(geom.parts) != 1:
            return None  # multi-part group -- LLM territory in v1
        inner = geom.parts[0]
        result = extrude(inner, depth=depth)
        if result is None:
            return None
        # Propagate label / name from the wrapping group.
        updates: dict[str, object] = {}
        if inner_label is not None:
            updates["label"] = inner_label
        if inner_name is not None:
            updates["name"] = inner_name
        return result.model_copy(update=updates) if updates else result

    # --- Unsupported primitive kinds ----------------------------------------
    _UNSUPPORTED = {
        ShapeKind.LINE,
        ShapeKind.PATH,
        ShapeKind.TEXT,
        ShapeKind.NODE,
        ShapeKind.EDGE,
    }
    if geom.kind in _UNSUPPORTED:
        return None

    # --- Derive silhouette ---------------------------------------------------
    sil = _silhouette(geom)
    if sil is None:
        return None

    # --- Offset vector -------------------------------------------------------
    k = depth * 0.7071
    off = (k, -k)

    # --- Fit the silhouette so all vertices stay in [2, 98] ------------------
    sil = _fit_pts(sil, off)
    n_pts = len(sil)

    # --- Determine winding / signed area ------------------------------------
    sa = _signed_area(sil)

    # --- Base color for shading ----------------------------------------------
    hue, sat, _l_base = _base_color(geom)

    fill_top = _make_color(hue, sat, _L_TOP)
    fill_side = _make_color(hue, sat, _L_SIDE)
    fill_front = _make_color(hue, sat, _L_FRONT)
    stroke_color = _make_color(hue, sat, _L_STROKE)

    # --- Offset direction unit vector (for sorting / face classification) ---
    off_len = math.hypot(off[0], off[1])
    off_ux = off[0] / off_len if off_len > 1e-9 else 0.0
    off_uy = off[1] / off_len if off_len > 1e-9 else 0.0

    # --- Select visible edges and sort back-to-front -------------------------
    # An edge is visible if its outward normal has a positive component in the
    # offset direction, i.e., n . offset_unit > 0.
    visible_edges: list[tuple[int, float, float]] = []
    # (edge_index, ny, mid_dot) where mid_dot = midpoint . offset_unit
    for i in range(n_pts):
        j = (i + 1) % n_pts
        px, py = sil[i]
        qx, qy = sil[j]
        nx, ny = _normal_outward(px, py, qx, qy, sa)
        dot_normal = nx * off_ux + ny * off_uy
        if dot_normal > 1e-6:
            # Mid-point for painter-order sort: project onto offset direction.
            mx, my = (px + qx) / 2.0, (py + qy) / 2.0
            # Sort by how much midpoint is aligned with offset -- far faces first.
            mid_dot = mx * off_ux + my * off_uy
            visible_edges.append((i, ny, mid_dot))

    # Sort: edges whose midpoints are LEAST aligned with the offset direction
    # are the farthest away and paint first.
    visible_edges.sort(key=lambda e: e[2])

    # --- Build part polygons ------------------------------------------------
    parts: list[GeometrySpec] = []

    for band_idx, (edge_i, ny, _mid_dot) in enumerate(visible_edges, start=1):
        edge_j = (edge_i + 1) % n_pts
        pi = sil[edge_i]
        pj = sil[edge_j]
        # Quad: pi -> pj -> pj+off -> pi+off  (paint order: far-side first)
        quad_pts = [
            pi,
            pj,
            (pj[0] + off[0], pj[1] + off[1]),
            (pi[0] + off[0], pi[1] + off[1]),
        ]
        # Classify band face: if the normal's y component is negative
        # (pointing "up" in y-down space) -> top-facing -> lighter.
        if ny < -0.1:
            face_fill = fill_top
        else:
            face_fill = fill_side

        parts.append(
            GeometrySpec(
                kind=ShapeKind.POLYGON,
                name=f"face-band-{band_idx}",
                points=quad_pts,
                fill=face_fill,
                stroke=stroke_color,
                fill_style=FillStyle.SOLID,
            )
        )

    # --- Front face (last -- on top in painter's algorithm) ------------------
    parts.append(
        GeometrySpec(
            kind=ShapeKind.POLYGON,
            name="face-front",
            points=sil,
            fill=fill_front,
            stroke=stroke_color,
            fill_style=FillStyle.SOLID,
        )
    )

    # --- Wrap in a GROUP ----------------------------------------------------
    return GeometrySpec(
        kind=ShapeKind.GROUP,
        label=geom.label,
        name=geom.name,
        parts=parts,
    )
