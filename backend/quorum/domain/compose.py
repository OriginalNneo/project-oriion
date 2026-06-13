"""Deterministic spatial composition of a new shape onto an existing scene.

``place_relative`` is the single public entry-point for the §15 compose branch.
It places a *new_part* (already modifier-applied, pre-baked geometry) relative
to a *target* scene per a *relation* string, combines them into one flat GROUP,
and fits the combined group into the 0..100 box.

Pure functions only — no I/O, no side effects.  All coordinates live in the
abstract 0..100 unit box that every :class:`GeometrySpec` uses.

Supported relations
-------------------
``"above"``   — new_part centered horizontally above target, small gap between.
``"below"``   — new_part centered horizontally below target.
``"left"``    — new_part centered vertically to the left of target.
``"right"``   — new_part centered vertically to the right of target.
``"on_top"``  — new_part overlapping target, centered, painted LAST (highest z).
``"behind"``  — new_part overlapping target, centered, painted FIRST (lowest z).
``"inside"``  — new_part contained within the target's bounding box, using the
               existing ``_contain`` semantics from :mod:`quorum.pipeline.relations`.

Any other string is treated as ``"above"`` (safe fallback).

Design constraints
------------------
- The returned spec is **flat**: ``kind=GROUP, parts=[...]``, no nested GROUPs.
- ``modifiers`` are NOT re-applied — the caller (classify.py branch 5b) must
  have already called ``apply_modifiers`` before passing *new_part* here.
- The combined group is always fitted to the ``[5, 95]`` usable range inside
  the 0..100 box (i.e. ≤ 90 units on each axis, centred at 50, 50).  The fit
  is a uniform scale ≤ 1.0 (never enlarges) followed by a translate.
- For PATH parts, only ``x`` and ``y`` (and ``width``/``height``) are moved;
  the ``d`` string is left intact.  This is a known approximation — complex
  path data is rare in rules-generated shapes and the visual error is small.

Raises
------
ValueError
    If ``target`` (after flattening) already has ≥ 60 parts (the hard geometry
    limit).  The caller should catch this and fall through to a plain CREATE.
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.pipeline.relations import _contain, part_bbox

# Gap in abstract units inserted between adjacent (non-overlapping) shapes.
_GAP: float = 3.0

# The usable half-range: parts are fitted inside [50-_HALF, 50+_HALF] on each
# axis, giving a 90-unit span centred at (50, 50).
_HALF: float = 45.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def place_relative(
    target: GeometrySpec,
    new_part: GeometrySpec,
    relation: str,
) -> GeometrySpec:
    """Place *new_part* relative to *target* and return a combined flat GROUP.

    Parameters
    ----------
    target:
        The existing node's geometry.  May be a plain primitive or a GROUP.
        GROUPs are flattened: their ``parts`` list is used directly.
    new_part:
        The newly generated shape.  Modifiers must already have been applied
        by the caller via ``apply_modifiers``; they will NOT be applied again.
    relation:
        One of ``"above"``, ``"below"``, ``"left"``, ``"right"``, ``"on_top"``,
        ``"behind"``, ``"inside"``.  Any other value falls back to ``"above"``.

    Returns
    -------
    GeometrySpec
        A flat GROUP with all parts in absolute 0..100 coordinates, fitted to
        the ``[5, 95]`` usable range.  ``modifiers`` is NOT present in the
        returned spec — the caller must emit ``modifiers=[]`` in the DesignOp.

    Raises
    ------
    ValueError
        When the flattened target already contains ≥ 60 parts (hard limit).
    """
    # 1. Flatten target into a list of primitives.
    target_parts: list[GeometrySpec] = (
        list(target.parts) if target.kind is ShapeKind.GROUP else [target]
    )

    # 2. Guard: respect the parts max_length=60 constraint.
    if len(target_parts) >= 60:
        raise ValueError(
            f"target has {len(target_parts)} parts — at or above the 60-part limit; "
            "cannot compose, fall through to CREATE"
        )

    # 3. Compute the host bounding box (union of all target parts).
    host_boxes = [part_bbox(p) for p in target_parts]
    hx1 = min(b[0] for b in host_boxes)
    hy1 = min(b[1] for b in host_boxes)
    hx2 = max(b[2] for b in host_boxes)
    hy2 = max(b[3] for b in host_boxes)
    host_cx = (hx1 + hx2) / 2.0
    host_cy = (hy1 + hy2) / 2.0

    # 4. Compute the new_part bounding box.
    nb = part_bbox(new_part)
    new_cx = (nb[0] + nb[2]) / 2.0
    new_cy = (nb[1] + nb[3]) / 2.0

    # 5. Place new_part per relation.
    norm = relation.strip().lower()

    if norm == "inside":
        # Reuse the existing containment semantics: shrink + center inside host.
        placed = _contain(new_part, hx1, hy1, hx2, hy2)
        combined_parts = [*target_parts, placed]
    else:
        # Compute (dx, dy) to translate new_part by.
        dx, dy = _placement_offset(norm, hx1, hy1, hx2, hy2, host_cx, host_cy, nb, new_cx, new_cy)
        placed = _translate_part(new_part, dx, dy)

        # Z-order: "behind" means painted first (prepend); all others append.
        if norm == "behind":
            combined_parts = [placed, *target_parts]
        else:
            combined_parts = [*target_parts, placed]

    # 6. Fit the combined group into [5, 95] (90-unit usable range).
    fitted_parts = _fit_to_box(combined_parts)

    return GeometrySpec(
        kind=ShapeKind.GROUP,
        x=50.0,
        y=50.0,
        width=90.0,
        height=90.0,
        parts=fitted_parts,
    )


# ---------------------------------------------------------------------------
# Placement helpers
# ---------------------------------------------------------------------------


def _placement_offset(
    relation: str,
    hx1: float,
    hy1: float,
    hx2: float,
    hy2: float,
    host_cx: float,
    host_cy: float,
    nb: tuple[float, float, float, float],
    new_cx: float,
    new_cy: float,
) -> tuple[float, float]:
    """Return the (dx, dy) translation to apply to new_part for *relation*."""
    if relation == "above":
        # Center horizontally; bottom edge of new_part = top edge of host - GAP.
        dx = host_cx - new_cx
        dy = hy1 - _GAP - nb[3]
    elif relation == "below":
        # Center horizontally; top edge of new_part = bottom edge of host + GAP.
        dx = host_cx - new_cx
        dy = hy2 + _GAP - nb[1]
    elif relation == "left":
        # Center vertically; right edge of new_part = left edge of host - GAP.
        dx = hx1 - _GAP - nb[2]
        dy = host_cy - new_cy
    elif relation == "right":
        # Center vertically; left edge of new_part = right edge of host + GAP.
        dx = hx2 + _GAP - nb[0]
        dy = host_cy - new_cy
    elif relation == "on_top":
        # Overlap: bottom of new_part aligned to top of host, centered, no gap.
        dx = host_cx - new_cx
        dy = hy1 - nb[1]
    elif relation == "behind":
        # Overlap: centered on host (painted first → visually behind).
        dx = host_cx - new_cx
        dy = host_cy - new_cy
    else:
        # Default / unknown relation → treat as "above".
        dx = host_cx - new_cx
        dy = hy1 - _GAP - nb[3]
    return dx, dy


def _translate_part(part: GeometrySpec, dx: float, dy: float) -> GeometrySpec:
    """Return a copy of *part* translated by (dx, dy).

    Handles all concrete ShapeKind variants:
    - Most kinds: translate via ``x`` and ``y``.
    - POLYGON: translate every point in ``points``.
    - PATH: translate ``x`` and ``y`` only; ``d`` string is left intact
      (known approximation — see module docstring).

    Coordinates are clamped to [0, 100] after translation.
    """
    if not dx and not dy:
        return part

    updates: dict[str, object] = {
        "x": min(100.0, max(0.0, part.x + dx)),
        "y": min(100.0, max(0.0, part.y + dy)),
    }

    if part.points is not None:
        updates["points"] = [
            (
                min(100.0, max(0.0, px + dx)),
                min(100.0, max(0.0, py + dy)),
            )
            for px, py in part.points
        ]

    return part.model_copy(update=updates)


# ---------------------------------------------------------------------------
# Fit-to-box
# ---------------------------------------------------------------------------


def _fit_to_box(parts: list[GeometrySpec]) -> list[GeometrySpec]:
    """Translate + uniform-scale *parts* so the combined bbox fits in [5, 95].

    Steps:
    1. Translate so the combined centroid is at (50, 50).
    2. If after centring the union still exceeds 90 units on any axis, shrink
       uniformly (scale ≤ 1.0 — never enlarge).
    3. Clamp all coords to [0, 100].

    PATH ``d`` strings are left intact; only ``x``, ``y``, ``width``,
    ``height`` are scaled (same approximation as ``_translate_part``).
    """
    if not parts:
        return parts

    # Union bbox.
    boxes = [part_bbox(p) for p in parts]
    ux1 = min(b[0] for b in boxes)
    uy1 = min(b[1] for b in boxes)
    ux2 = max(b[2] for b in boxes)
    uy2 = max(b[3] for b in boxes)

    # Step 1: translate to centre.
    tx = 50.0 - (ux1 + ux2) / 2.0
    ty = 50.0 - (uy1 + uy2) / 2.0
    if tx or ty:
        parts = [_translate_part(p, tx, ty) for p in parts]
        # Recompute union after translate.
        boxes = [part_bbox(p) for p in parts]
        ux1 = min(b[0] for b in boxes)
        uy1 = min(b[1] for b in boxes)
        ux2 = max(b[2] for b in boxes)
        uy2 = max(b[3] for b in boxes)

    union_w = ux2 - ux1
    union_h = uy2 - uy1

    # Step 2: shrink if necessary.
    if union_w <= 0 or union_h <= 0:
        return parts  # degenerate — nothing to scale

    usable = _HALF * 2.0  # 90 units
    scale = min(1.0, usable / union_w, usable / union_h)

    if abs(scale - 1.0) < 1e-9:
        return parts  # already fits

    parts = [_scale_part(p, scale) for p in parts]
    return parts


def _scale_coord(v: float, scale: float) -> float:
    """Scale one coordinate about the box centre (50, 50), clamped to [0, 100].

    Inlined from geometry.py to avoid importing a private symbol.
    """
    return min(100.0, max(0.0, 50.0 + (v - 50.0) * scale))


def _scale_part(part: GeometrySpec, scale: float) -> GeometrySpec:
    """Return a uniformly scaled copy of *part* about (50, 50).

    - Scalar fields (``x``, ``y``, ``width``, ``height``, ``corner_radius``,
      ``font_size``) are scaled.
    - POLYGON ``points`` are scaled point-by-point.
    - PATH ``d`` string is left intact; ``x``, ``y``, ``width``, ``height``
      are scaled (same approximation as elsewhere in this module).
    """
    updates: dict[str, object] = {
        "x": _scale_coord(part.x, scale),
        "y": _scale_coord(part.y, scale),
        "width": min(100.0, max(1.0, part.width * scale)),
        "height": min(100.0, max(1.0, part.height * scale)),
    }

    if part.corner_radius:
        updates["corner_radius"] = min(50.0, part.corner_radius * scale)

    if part.font_size:
        updates["font_size"] = min(20.0, max(0.5, part.font_size * scale))

    if part.points is not None:
        updates["points"] = [
            (_scale_coord(px, scale), _scale_coord(py, scale))
            for px, py in part.points
        ]

    return part.model_copy(update=updates)
