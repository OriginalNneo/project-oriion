"""Deterministic isometric projection — pure 3-D solid -> 2-D GeometrySpec.

Given a sequence of axis-aligned 3-D ``Solid`` primitives (box / cylinder /
wedge / sphere / hemisphere), ``project_solids`` returns ONE flat isometric
GROUP of polygon/ellipse/path parts, globally z-sorted (painter's order, far
faces first) and centered+scaled into the 0..100 abstract box.

Design principle: "model proposes, code disposes."  An LLM supplies rough 3-D
placement; this module does all projection math deterministically.  It is the
runtime generalization of ``scripts/make_isometric.py``.

Projection convention (matches ``scripts/make_isometric._project`` exactly):
    World: x → right, y → UP, z → toward viewer-left.
    Screen (0..100, y grows DOWN):
        sx = (x - z) * COS30
        sy = (x + z) * SIN30 - y
    "Closer to the viewer" ⇔ larger (x + y + z).
    View direction toward the viewer ∝ (1, 1, 1).

Wedge orientation:
    Right-triangle cross-section in the x-y (vertical) plane, extruded along z
    by ``d`` units.  The triangle has vertices:
        bottom-back  (x,   y)
        bottom-front (x+w, y)
        top-back     (x,   y+h)
    The hypotenuse runs from (x+w, y) up to (x, y+h) — a ramp rising to the
    left.  The five faces are: front-triangle (z+d), back-triangle (z), bottom
    quad (y), vertical-back quad (x=x), slope quad (hypotenuse).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from quorum.domain.color import (
    format_hex,
    hsl_to_rgb,
    parse_hex,
    rgb_to_hsl,
)
from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind

# ---------------------------------------------------------------------------
# Projection constants
# ---------------------------------------------------------------------------

_COS30 = math.cos(math.pi / 6)  # 0.8660254…
_SIN30 = 0.5

# ---------------------------------------------------------------------------
# Shading lightness bands
# ---------------------------------------------------------------------------

_L_TOP = 0.80      # up-facing (world +y normal dominant) — light
_L_MID = 0.55      # front-facing (world +z normal dominant) — mid
_L_DARK = 0.40     # side-facing (world +x or mixed) — dark
_L_STROKE = 0.22   # dark outline for all faces
_SAT_MIN = 0.18    # clamp so near-grays still read as shaded

# Default base color matches make_isometric's neutral gray family.
_DEFAULT_COLOR = "#9ca3af"

# ---------------------------------------------------------------------------
# Fit margin (8..92 of the 0..100 box)
# ---------------------------------------------------------------------------

_FIT_LO = 8.0
_FIT_HI = 92.0


# ---------------------------------------------------------------------------
# Public data-class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Solid:
    """One axis-aligned 3-D primitive in a relative world space.

    ``shape``: ``"box"`` | ``"cylinder"`` | ``"wedge"`` | ``"sphere"`` |
    ``"hemisphere"``.
    ``(x, y, z)``: the MIN corner (smallest x, y, z) in world units.
    ``(w, d, h)``: size along world x (w), world z (d), world y (h).
    Only relative positions/sizes matter — ``project_solids`` fits the whole
    assembly into the 0..100 box afterward.
    ``color``: CSS hex color for shading, or ``None`` → gray default.
    ``name``: optional stable name propagated to part names (e.g. ``"base"``
    yields part names ``"base-top"``, ``"base-front"`` …).
    """

    shape: str
    x: float
    y: float
    z: float
    w: float
    d: float
    h: float
    color: str | None = None
    name: str | None = None


# ---------------------------------------------------------------------------
# Internal type aliases
# ---------------------------------------------------------------------------

_Vec3 = tuple[float, float, float]
_Vec2 = tuple[float, float]


# ---------------------------------------------------------------------------
# Projection helper
# ---------------------------------------------------------------------------


def _project(px: float, py: float, pz: float) -> _Vec2:
    """World (x right, y UP, z toward viewer-left) → screen (y down).

    Matches ``scripts/make_isometric._project`` exactly.
    """
    sx = (px - pz) * _COS30
    sy = (px + pz) * _SIN30 - py
    return sx, sy


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


def _base_hsl(color: str | None) -> tuple[float, float, float]:
    """Return (h, s, l) in [0, 1] for the given hex color, or the default gray.

    Saturation is clamped to >= _SAT_MIN so near-gray input still reads shaded.
    """
    src = color if color else _DEFAULT_COLOR
    rgb = parse_hex(src)
    if rgb is None:
        rgb = parse_hex(_DEFAULT_COLOR)
        assert rgb is not None  # fallback always parses
    h, s, li = rgb_to_hsl(*rgb)
    s = max(s, _SAT_MIN)
    return h, s, li


def _shade(hue: float, sat: float, lightness: float) -> str:
    r, g, b = hsl_to_rgb(hue, sat, lightness)
    return format_hex(r, g, b)


# ---------------------------------------------------------------------------
# Z-sort key
# ---------------------------------------------------------------------------


def _zsort_key(cx: float, cy: float, cz: float) -> float:
    """World-centroid dot (1,1,1).  Larger = closer to viewer → paints later."""
    return cx + cy + cz


# ---------------------------------------------------------------------------
# Face classification → lightness
# ---------------------------------------------------------------------------


def _face_lightness(nx: float, ny: float, nz: float) -> float:
    """Map a world outward normal to a lightness value.

    World +y is UP (toward the camera top) → _L_TOP.
    World +z is toward viewer-left → _L_MID.
    World +x (right) → _L_DARK.
    We use the dominant component to classify.
    """
    ax, ay, az = abs(nx), abs(ny), abs(nz)
    if ay >= ax and ay >= az and ny > 0:
        return _L_TOP     # top face
    if az >= ax and az >= ay and nz > 0:
        return _L_MID     # front-z face
    # everything else (x-dominant or mixed): dark
    return _L_DARK


# ---------------------------------------------------------------------------
# Internal representation of a single projected face
# ---------------------------------------------------------------------------


@dataclass
class _Face:
    pts_2d: list[_Vec2]
    fill: str
    stroke: str
    name: str
    zsort: float  # world centroid dot (1,1,1)


# ---------------------------------------------------------------------------
# Cull test
# ---------------------------------------------------------------------------


def _visible(nx: float, ny: float, nz: float) -> bool:
    """Keep a face if its outward world normal has a positive component toward
    the viewer (1, 1, 1) — i.e., dot > 1e-6."""
    return nx + ny + nz > 1e-6


# ---------------------------------------------------------------------------
# Box faces
# ---------------------------------------------------------------------------


def _box_faces(solid: Solid) -> list[_Face]:
    """Enumerate the three visible faces of an axis-aligned box.

    Only the +x (right), +y (top), +z (front) faces are ever visible from the
    isometric view direction (1,1,1).  The -x/-y/-z faces are culled.
    """
    x, y, z, w, d, h = solid.x, solid.y, solid.z, solid.w, solid.d, solid.h
    hue, sat, _ = _base_hsl(solid.color)
    stroke = _shade(hue, sat, _L_STROKE)
    prefix = solid.name if solid.name else "solid"

    faces_3d: list[tuple[list[_Vec3], float, float, float, str]] = [
        # (vertices, nx, ny, nz, role)
        (
            [(x, y + h, z + d), (x + w, y + h, z + d),
             (x + w, y + h, z),   (x, y + h, z)],
            0.0, 1.0, 0.0, "top",
        ),
        (
            [(x, y, z + d), (x + w, y, z + d),
             (x + w, y + h, z + d), (x, y + h, z + d)],
            0.0, 0.0, 1.0, "front",
        ),
        (
            [(x + w, y, z + d), (x + w, y, z),
             (x + w, y + h, z),   (x + w, y + h, z + d)],
            1.0, 0.0, 0.0, "right",
        ),
    ]

    result: list[_Face] = []
    for verts, nx, ny, nz, role in faces_3d:
        if not _visible(nx, ny, nz):
            continue
        li = _face_lightness(nx, ny, nz)
        fill = _shade(hue, sat, li)
        pts_2d = [_project(*v) for v in verts]
        cx = sum(v[0] for v in verts) / len(verts)
        cy = sum(v[1] for v in verts) / len(verts)
        cz = sum(v[2] for v in verts) / len(verts)
        result.append(_Face(
            pts_2d=pts_2d,
            fill=fill,
            stroke=stroke,
            name=f"{prefix}-{role}",
            zsort=_zsort_key(cx, cy, cz),
        ))
    return result


# ---------------------------------------------------------------------------
# Wedge faces
# ---------------------------------------------------------------------------

def _wedge_faces(solid: Solid) -> list[_Face]:
    """Enumerate the visible faces of an axis-aligned wedge (triangular prism).

    Wedge cross-section in the x-y plane (extruded along z by d):
        bottom-back  (x,   y, *)   bottom-front (x+w, y, *)   top-back (x, y+h, *)
    Hypotenuse ramp from (x+w, y) → (x, y+h) (rises to the left/back).

    Five faces:
        front-tri   — triangle at z = z+d   (normal ≈ (0, 0, +1))
        back-tri    — triangle at z = z     (normal ≈ (0, 0, -1))  → culled
        bottom-quad — y = y                 (normal = (0, -1, 0))  → culled
        vert-back   — x = x plane, rect     (normal = (-1, 0, 0))  → culled
        slope-quad  — hypotenuse face       (normal = (+h, +w, 0) / |…|)

    Only front-tri and slope-quad are visible from (1,1,1).
    The slope normal (unnormalised) = (h, w, 0): points in +x and +y → visible.
    """
    x, y, z = solid.x, solid.y, solid.z
    w, d, h = solid.w, solid.d, solid.h
    hue, sat, _ = _base_hsl(solid.color)
    stroke = _shade(hue, sat, _L_STROKE)
    prefix = solid.name if solid.name else "solid"

    result: list[_Face] = []

    # ---- front triangle: z-face at z = z+d ----
    nx, ny, nz = 0.0, 0.0, 1.0
    if _visible(nx, ny, nz):
        verts: list[_Vec3] = [
            (x,     y,     z + d),
            (x + w, y,     z + d),
            (x,     y + h, z + d),
        ]
        li = _face_lightness(nx, ny, nz)
        fill = _shade(hue, sat, li)
        pts_2d = [_project(*v) for v in verts]
        cx = sum(v[0] for v in verts) / 3
        cy = sum(v[1] for v in verts) / 3
        cz = sum(v[2] for v in verts) / 3
        result.append(_Face(pts_2d=pts_2d, fill=fill, stroke=stroke,
                            name=f"{prefix}-front", zsort=_zsort_key(cx, cy, cz)))

    # ---- slope quad: hypotenuse face ----
    # Outward normal of a face defined by two edge vectors in the x-y plane:
    # edge1 = (x+w,y,z+d)-(x,y+h,z+d) = (+w,-h,0)
    # edge2 = (x,y+h,z)-(x,y+h,z+d) = (0,0,-d)
    # normal = edge1 x edge2 in column-vector form:
    #   |i   j   k  |
    #   |w  -h   0  | = i((-h)(-d)-0*0) - j((w)(-d)-0*0) + k(0-0)
    #   |0   0  -d  |
    # = (hd, wd, 0) — normalise to direction (h, w, 0) (positive x and y)
    slope_nx = h
    slope_ny = w
    slope_nz = 0.0
    mag = math.hypot(slope_nx, slope_ny)
    if mag > 1e-9:
        slope_nx /= mag
        slope_ny /= mag
    if _visible(slope_nx, slope_ny, slope_nz):
        slope_verts: list[_Vec3] = [
            (x + w, y,     z + d),
            (x + w, y,     z),
            (x,     y + h, z),
            (x,     y + h, z + d),
        ]
        li = _face_lightness(slope_nx, slope_ny, slope_nz)
        fill = _shade(hue, sat, li)
        pts_2d = [_project(*v) for v in slope_verts]
        cx = sum(v[0] for v in slope_verts) / 4
        cy = sum(v[1] for v in slope_verts) / 4
        cz = sum(v[2] for v in slope_verts) / 4
        result.append(_Face(pts_2d=pts_2d, fill=fill, stroke=stroke,
                            name=f"{prefix}-slope", zsort=_zsort_key(cx, cy, cz)))

    return result


# ---------------------------------------------------------------------------
# Cylinder parts (body PATH + top ELLIPSE) — returned as raw dicts for fit
# ---------------------------------------------------------------------------


@dataclass
class _CylParts:
    """Raw (pre-fit) cylinder parts plus a z-sort key for insertion."""
    zsort: float
    # Pre-fit values in raw screen coords (will be transformed by _apply_fit)
    # Center of the top ellipse in raw screen space
    top_cx: float
    top_cy: float
    top_rx: float  # half-width (screen x)
    top_ry: float  # half-height (screen y)
    # Left/right x, top/bottom y of body in raw screen space
    body_lx: float  # left x
    body_rx: float  # right x
    body_top_y: float   # y of top (= top_cy)
    body_bot_y: float   # y of bottom center
    fill: str
    stroke: str
    name_prefix: str


def _cylinder_parts(solid: Solid) -> _CylParts | None:
    """Compute the raw cylinder geometry (body + top) in pre-fit screen space."""
    x, y, z = solid.x, solid.y, solid.z
    w, d, h = solid.w, solid.d, solid.h
    hue, sat, _ = _base_hsl(solid.color)
    stroke = _shade(hue, sat, _L_STROKE)
    fill_body = _shade(hue, sat, _L_MID)

    # In the isometric projection the cylinder axis is vertical (world y).
    # The top face center (world) = (x + w/2, y + h, z + d/2)
    # The bottom face center      = (x + w/2, y,     z + d/2)
    top_cx3, top_cy3, top_cz3 = x + w / 2, y + h, z + d / 2
    bot_cx3, bot_cy3, bot_cz3 = x + w / 2, y,     z + d / 2

    # Project the top and bottom centers
    top_sx, top_sy = _project(top_cx3, top_cy3, top_cz3)
    _bot_sx, bot_sy = _project(bot_cx3, bot_cy3, bot_cz3)

    # Ellipse radii in screen space for an isometric top. A horizontal circle of
    # radius r, parametrised (r*cos t, r*sin t) in the x-z plane, projects to
    #   sx = r*COS30*(cos t - sin t),  sy = r*SIN30*(cos t + sin t),
    # whose extrema are r·√2·COS30 and r·√2·SIN30 — the √2 must NOT be dropped or
    # the cap comes out ~29% too narrow. With r = (w/2 + d/2)/2 (mean radius),
    # 2r/√2 = (w/2 + d/2)/√2, so the screen semi-axes are:
    screen_rx = (w / 2 + d / 2) * _COS30 / math.sqrt(2)
    screen_ry = (w / 2 + d / 2) * _SIN30 / math.sqrt(2)

    prefix = solid.name if solid.name else "solid"
    zsort = _zsort_key(
        (top_cx3 + bot_cx3) / 2,
        (top_cy3 + bot_cy3) / 2,
        (top_cz3 + bot_cz3) / 2,
    )

    return _CylParts(
        zsort=zsort,
        top_cx=top_sx,
        top_cy=top_sy,
        top_rx=screen_rx,
        top_ry=screen_ry,
        body_lx=top_sx - screen_rx,
        body_rx=top_sx + screen_rx,
        body_top_y=top_sy,
        body_bot_y=bot_sy,
        fill=fill_body,
        stroke=stroke,
        name_prefix=prefix,
    )


# ---------------------------------------------------------------------------
# Sphere / hemisphere parts (body ELLIPSE or dome PATH + top-left highlight)
# ---------------------------------------------------------------------------

# The projection matrix P = [[cos30, 0, -cos30], [sin30, -1, sin30]] satisfies
# P·Pᵀ = 1.5·I, so a world sphere of radius r projects to a PERFECT circle of
# screen radius r·√1.5 — no ellipse squash to compute.
_SPHERE_SCREEN = math.sqrt(1.5)
# The volumetric highlight: a smaller _L_TOP ellipse offset toward the light
# (screen up-left), the same "light top" language the box/cylinder faces use.
_HL_OFFSET = 0.35  # highlight center offset, fraction of the body semi-axis
_HL_SIZE = 0.32    # highlight semi-axis, fraction of the body semi-axis


@dataclass
class _SphereParts:
    """Raw (pre-fit) sphere/hemisphere geometry plus a z-sort key.

    A full sphere renders as one _L_MID circle (``rx == ry_top``, ``base_ry``
    unused); a hemisphere as a dome PATH — a top half-ellipse (semi-axes
    ``rx`` x ``ry_top``) closed by the near half of its isometric base ellipse
    (semi-axes ``rx`` x ``base_ry``, the cylinder-cap foreshortening). Both get
    an _L_TOP highlight ellipse toward screen up-left.
    """

    zsort: float
    cx: float       # projected center (sphere) / base center (hemisphere), raw
    cy: float
    rx: float       # horizontal semi-axis in raw screen units
    ry_top: float   # vertical semi-axis of the body/dome above cy
    base_ry: float  # near-base half-ellipse semi-axis below cy (hemisphere)
    hemisphere: bool
    fill: str
    stroke: str
    highlight: str
    name_prefix: str


def _sphere_parts(solid: Solid) -> _SphereParts:
    """Compute raw full-sphere geometry: a circle in pre-fit screen space."""
    x, y, z = solid.x, solid.y, solid.z
    w, d, h = solid.w, solid.d, solid.h
    hue, sat, _ = _base_hsl(solid.color)

    # Sphere inscribed in the (w, d, h) box: mean half-extent as the radius.
    r = (w + d + h) / 6.0
    cx3, cy3, cz3 = x + w / 2, y + h / 2, z + d / 2
    sx, sy = _project(cx3, cy3, cz3)
    screen_r = r * _SPHERE_SCREEN

    return _SphereParts(
        zsort=_zsort_key(cx3, cy3, cz3),
        cx=sx,
        cy=sy,
        rx=screen_r,
        ry_top=screen_r,
        base_ry=0.0,
        hemisphere=False,
        fill=_shade(hue, sat, _L_MID),
        stroke=_shade(hue, sat, _L_STROKE),
        highlight=_shade(hue, sat, _L_TOP),
        name_prefix=solid.name if solid.name else "solid",
    )


def _hemisphere_parts(solid: Solid) -> _SphereParts:
    """Compute raw hemisphere geometry: a dome sitting flat-side-down at y."""
    x, y, z = solid.x, solid.y, solid.z
    w, d, h = solid.w, solid.d, solid.h
    hue, sat, _ = _base_hsl(solid.color)

    # Base circle mirrors the cylinder cap exactly (same mean radius and √2
    # foreshortening); the dome rises h world units, which project 1:1 to
    # screen y, so the top arc's vertical semi-axis is simply h.
    base_cx3, base_cy3, base_cz3 = x + w / 2, y, z + d / 2
    sx, sy = _project(base_cx3, base_cy3, base_cz3)
    screen_rx = (w / 2 + d / 2) * _COS30 / math.sqrt(2)
    screen_ry = (w / 2 + d / 2) * _SIN30 / math.sqrt(2)

    return _SphereParts(
        zsort=_zsort_key(x + w / 2, y + h / 2, z + d / 2),
        cx=sx,
        cy=sy,
        rx=screen_rx,
        ry_top=h,
        base_ry=screen_ry,
        hemisphere=True,
        fill=_shade(hue, sat, _L_MID),
        stroke=_shade(hue, sat, _L_STROKE),
        highlight=_shade(hue, sat, _L_TOP),
        name_prefix=solid.name if solid.name else "solid",
    )


# ---------------------------------------------------------------------------
# Fit helpers (ported from scripts/make_isometric._fit / _scale_path)
# ---------------------------------------------------------------------------


def _collect_bbox(
    faces: list[_Face],
    cyls: list[_CylParts],
    spheres: list[_SphereParts],
) -> tuple[float, float, float, float]:
    """Collect the bounding box of all projected geometry in raw screen coords."""
    xs: list[float] = []
    ys: list[float] = []
    for face in faces:
        for sx, sy in face.pts_2d:
            xs.append(sx)
            ys.append(sy)
    for cp in cyls:
        # top ellipse
        xs += [cp.top_cx - cp.top_rx, cp.top_cx + cp.top_rx]
        ys += [cp.top_cy - cp.top_ry, cp.top_cy + cp.top_ry]
        # body extremes
        xs += [cp.body_lx, cp.body_rx]
        ys += [cp.body_top_y, cp.body_bot_y + cp.top_ry]
    for sp in spheres:
        xs += [sp.cx - sp.rx, sp.cx + sp.rx]
        # a full sphere extends ry_top both ways; a hemisphere only base_ry down
        ys += [sp.cy - sp.ry_top, sp.cy + (sp.base_ry if sp.hemisphere else sp.ry_top)]
    if not xs:
        return 0.0, 1.0, 0.0, 1.0
    return min(xs), max(xs), min(ys), max(ys)


def _compute_fit(
    x0: float, x1: float, y0: float, y1: float
) -> tuple[float, float, float]:
    """Return (scale, ox, oy) to map raw coords into [_FIT_LO .. _FIT_HI]."""
    span = _FIT_HI - _FIT_LO  # 84.0
    scale = span / max(x1 - x0, y1 - y0, 1.0)
    ox = (_FIT_LO + _FIT_HI - (x1 - x0) * scale) / 2.0 - x0 * scale
    oy = (_FIT_LO + _FIT_HI - (y1 - y0) * scale) / 2.0 - y0 * scale
    return scale, ox, oy


def _fx(v: float, scale: float, ox: float) -> float:
    return min(100.0, max(0.0, v * scale + ox))


def _fy(v: float, scale: float, oy: float) -> float:
    return min(100.0, max(0.0, v * scale + oy))


# ---------------------------------------------------------------------------
# Build GeometrySpec parts from fitted faces and cylinders
# ---------------------------------------------------------------------------


def _face_to_spec(face: _Face, scale: float, ox: float, oy: float) -> GeometrySpec:
    """Convert a fitted _Face to a POLYGON GeometrySpec."""
    pts = [
        (_fx(sx, scale, ox), _fy(sy, scale, oy))
        for sx, sy in face.pts_2d
    ]
    return GeometrySpec(
        kind=ShapeKind.POLYGON,
        name=face.name,
        points=pts,
        fill=face.fill,
        stroke=face.stroke,
        fill_style=FillStyle.SOLID,
    )


def _cyl_to_specs(
    cp: _CylParts, scale: float, ox: float, oy: float
) -> list[GeometrySpec]:
    """Convert a _CylParts to [body PATH, top ELLIPSE] GeometrySpecs."""
    # Fitted values
    lx = _fx(cp.body_lx, scale, ox)
    rx = _fx(cp.body_rx, scale, ox)
    top_y = _fy(cp.body_top_y, scale, oy)
    bot_y = _fy(cp.body_bot_y, scale, oy)
    top_cx = _fx(cp.top_cx, scale, ox)
    top_cy = _fy(cp.top_cy, scale, oy)
    top_rx_fit = cp.top_rx * scale
    top_ry_fit = cp.top_ry * scale

    # Body: left edge down + bottom half-ellipse arc + right edge up + close
    # Body height in fitted space
    body_h = bot_y - top_y  # positive since bot_y > top_y (y grows down)
    body_w = rx - lx
    body_cx = (lx + rx) / 2.0

    # Clamp arc values to 0..100
    arc_rx = min(top_rx_fit, 50.0)
    arc_ry = min(top_ry_fit, 50.0)

    # Path: M lx top_y, L lx bot_y, A arc_rx arc_ry 0 0 0 rx bot_y, L rx top_y, Z
    d = (
        f"M {lx:.1f} {top_y:.1f} "
        f"L {lx:.1f} {bot_y:.1f} "
        f"A {arc_rx:.1f} {arc_ry:.1f} 0 0 0 {rx:.1f} {bot_y:.1f} "
        f"L {rx:.1f} {top_y:.1f} Z"
    )

    body_spec = GeometrySpec(
        kind=ShapeKind.PATH,
        name=f"{cp.name_prefix}-body",
        d=d,
        x=body_cx,
        y=(top_y + bot_y) / 2.0,
        width=max(body_w, 1.0),
        height=max(body_h + top_ry_fit, 1.0),
        fill=cp.fill,
        stroke=cp.stroke,
        fill_style=FillStyle.SOLID,
    )

    # Top ellipse — derive top fill from the body fill's hue
    body_rgb = parse_hex(cp.fill)
    if body_rgb is not None:
        bh, bs, _ = rgb_to_hsl(*body_rgb)
        top_fill = _shade(bh, max(bs, _SAT_MIN), _L_TOP)
    else:
        bh2, bs2, _ = _base_hsl(None)
        top_fill = _shade(bh2, bs2, _L_TOP)

    top_spec = GeometrySpec(
        kind=ShapeKind.ELLIPSE,
        name=f"{cp.name_prefix}-top",
        x=top_cx,
        y=top_cy,
        width=max(top_rx_fit * 2, 1.0),
        height=max(top_ry_fit * 2, 1.0),
        fill=top_fill,
        stroke=cp.stroke,
        fill_style=FillStyle.SOLID,
    )

    return [body_spec, top_spec]


def _sphere_to_specs(
    sp: _SphereParts, scale: float, ox: float, oy: float
) -> list[GeometrySpec]:
    """Convert a _SphereParts to [body ELLIPSE|dome PATH, highlight ELLIPSE]."""
    cx = _fx(sp.cx, scale, ox)
    cy = _fy(sp.cy, scale, oy)
    rx_fit = sp.rx * scale
    ry_top_fit = sp.ry_top * scale
    base_ry_fit = sp.base_ry * scale

    if sp.hemisphere:
        # Dome: top half-ellipse over the base, closed by the NEAR half of the
        # isometric base ellipse (both arcs clockwise; y grows down).
        lx = _fx(sp.cx - sp.rx, scale, ox)
        rx_pt = _fx(sp.cx + sp.rx, scale, ox)
        arc_rx = min((rx_pt - lx) / 2.0, 50.0)
        arc_ry_top = min(ry_top_fit, 50.0)
        arc_ry_base = min(base_ry_fit, 50.0)
        d = (
            f"M {lx:.1f} {cy:.1f} "
            f"A {arc_rx:.1f} {arc_ry_top:.1f} 0 0 1 {rx_pt:.1f} {cy:.1f} "
            f"A {arc_rx:.1f} {arc_ry_base:.1f} 0 0 1 {lx:.1f} {cy:.1f} Z"
        )
        body_spec = GeometrySpec(
            kind=ShapeKind.PATH,
            name=f"{sp.name_prefix}-dome",
            d=d,
            x=cx,
            y=(cy - ry_top_fit + cy + base_ry_fit) / 2.0,
            width=max(rx_fit * 2, 1.0),
            height=max(ry_top_fit + base_ry_fit, 1.0),
            fill=sp.fill,
            stroke=sp.stroke,
            fill_style=FillStyle.SOLID,
        )
    else:
        body_spec = GeometrySpec(
            kind=ShapeKind.ELLIPSE,
            name=f"{sp.name_prefix}-body",
            x=cx,
            y=cy,
            width=max(rx_fit * 2, 1.0),
            height=max(ry_top_fit * 2, 1.0),
            fill=sp.fill,
            stroke=sp.stroke,
            fill_style=FillStyle.SOLID,
        )

    # Highlight toward the light (screen up-left), inside the silhouette. On a
    # hemisphere it sits higher up the dome so it never crosses the base line.
    hl_dy = (0.55 if sp.hemisphere else _HL_OFFSET) * ry_top_fit
    highlight_spec = GeometrySpec(
        kind=ShapeKind.ELLIPSE,
        name=f"{sp.name_prefix}-highlight",
        x=_fx(sp.cx, scale, ox) - _HL_OFFSET * rx_fit,
        y=_fy(sp.cy, scale, oy) - hl_dy,
        width=max(rx_fit * 2 * _HL_SIZE, 1.0),
        height=max(ry_top_fit * 2 * _HL_SIZE, 1.0),
        fill=sp.highlight,
        # The highlight is a sheen ON the body, not an outlined feature — a
        # dark stroke here would read as an eyeball, so it strokes itself.
        stroke=sp.highlight,
        fill_style=FillStyle.SOLID,
    )

    return [body_spec, highlight_spec]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# Default soft cap on emitted parts. Callers with access to Settings pass
# `max_parts=settings.max_scene_parts` (env QUORUM_MAX_SCENE_PARTS) instead;
# GeometrySpec's hard model ceiling is PARTS_HARD_MAX (domain/geometry.py).
_DEFAULT_MAX_PARTS = 60


def project_solids(
    solids: Sequence[Solid], *, max_parts: int = _DEFAULT_MAX_PARTS
) -> GeometrySpec | None:
    """Project axis-aligned solids to ONE flat isometric GROUP.

    The group is globally z-sorted (painter's order, far faces first), with
    faces shaded by orientation, and the whole assembly centered+scaled into
    the 0..100 box.

    Parameters
    ----------
    solids:
        One or more ``Solid`` primitives to project.  Unknown ``shape`` values
        are silently skipped.  An empty sequence or all-unknown shapes → None.
    max_parts:
        Soft cap on emitted parts (default 60); an over-cap assembly keeps its
        NEAREST whole solids. Must not exceed GeometrySpec's hard ceiling.

    Returns
    -------
    GeometrySpec | None
        A flat GROUP with all projected faces as parts, or ``None`` if nothing
        was produced.
    """
    if not solids:
        return None

    all_faces: list[_Face] = []
    all_cyls: list[_CylParts] = []
    all_spheres: list[_SphereParts] = []

    for solid in solids:
        shape = solid.shape.lower()
        if shape == "box":
            all_faces.extend(_box_faces(solid))
        elif shape == "wedge":
            all_faces.extend(_wedge_faces(solid))
        elif shape == "cylinder":
            cp = _cylinder_parts(solid)
            if cp is not None:
                all_cyls.append(cp)
        elif shape == "sphere":
            all_spheres.append(_sphere_parts(solid))
        elif shape == "hemisphere":
            all_spheres.append(_hemisphere_parts(solid))
        # else: unknown shape → skip gracefully

    if not all_faces and not all_cyls and not all_spheres:
        return None

    # --- Global z-sort: ascending key = far first (painter's order) ----------
    all_faces.sort(key=lambda f: f.zsort)

    # Interleave cylinder/sphere parts at their z-sort position.
    # Build a combined sequence of (zsort, item), then sort and emit.
    combined: list[tuple[float, object]] = [
        (f.zsort, f) for f in all_faces
    ]
    for cp in all_cyls:
        combined.append((cp.zsort, cp))
    for sp in all_spheres:
        combined.append((sp.zsort, sp))
    combined.sort(key=lambda t: t[0])

    # --- Compute fit ----------------------------------------------------------
    x0, x1, y0, y1 = _collect_bbox(all_faces, all_cyls, all_spheres)
    scale, ox, oy = _compute_fit(x0, x1, y0, y1)

    # --- Build parts, one CHUNK per z-sorted item ----------------------------
    # `combined` is far→near; a face is one part, a cylinder is two (body+top),
    # a sphere/hemisphere is two (body/dome + highlight).
    chunks: list[list[GeometrySpec]] = []
    for _, item in combined:
        if isinstance(item, _Face):
            chunks.append([_face_to_spec(item, scale, ox, oy)])
        elif isinstance(item, _CylParts):
            chunks.append(_cyl_to_specs(item, scale, ox, oy))
        elif isinstance(item, _SphereParts):
            chunks.append(_sphere_to_specs(item, scale, ox, oy))

    # Soft parts cap (Settings.max_scene_parts at the pipeline seam). An
    # over-cap assembly (≈20+ solids at the default 60) is pathological, but if
    # it happens we must keep the NEAREST parts (painter's order draws near
    # LAST) and never split a cylinder's body/top or a sphere's body/highlight
    # pair — so drop whole far chunks from the FRONT, not a blind tail slice.
    while sum(len(c) for c in chunks) > max_parts and len(chunks) > 1:
        chunks.pop(0)

    parts: list[GeometrySpec] = [spec for chunk in chunks for spec in chunk]
    if not parts:
        return None

    return GeometrySpec(kind=ShapeKind.GROUP, parts=parts)
