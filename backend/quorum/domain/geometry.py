"""Geometry spec — the pure-data input to the SVG renderer.

The renderer is a *pure, deterministic* function of a GeometrySpec (plan.md §3.3
stage 5). Keeping geometry as plain validated data (no SVG strings, no rough.js
in here) is what makes the renderer cacheable and trivially testable, and lets
the *same* spec drive both the server-side reference renderer and the client's
rough.js renderer.

Geometry mode primitives now; workflow-mode nodes/edges are additive later
(plan.md §1 two modes) — they'll be new ShapeKinds, not a new module.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from quorum.domain import pathdata
from quorum.domain.color import retint


class ShapeKind(StrEnum):
    """The primitive shapes Quorum can sketch (geometry mode)."""

    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    TRIANGLE = "triangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    # A composed scene: several positioned primitives in ONE sketch
    # ("a circle with a square on top" is one idea node, not two).
    GROUP = "group"
    # IR v2 — the intricacy primitives (isometric faces, wireframes, labels):
    POLYGON = "polygon"  # explicit `points` in the 0..100 box
    PATH = "path"  # constrained SVG path data `d` (see domain/pathdata.py)
    TEXT = "text"  # renders `label` at (x, y); not a rough-sketch shape
    # workflow-mode primitives (Phase 2+): a labelled box and a connector
    NODE = "node"
    EDGE = "edge"


class FillStyle(StrEnum):
    """How a shape's fill is drawn (mirrors rough.js fillStyle choices)."""

    HACHURE = "hachure"
    SOLID = "solid"
    NONE = "none"


class GeometrySpec(BaseModel):
    """A resolution-independent description of one sketch.

    Coordinates live in an abstract 0..100 unit box; the renderer maps that to
    the SVG viewport. This keeps specs display-size-independent.
    """

    model_config = {"frozen": True}

    kind: ShapeKind
    # Center/anchor in 0..100 abstract units.
    x: float = Field(default=50.0, ge=0, le=100)
    y: float = Field(default=50.0, ge=0, le=100)
    # Extent in abstract units (interpretation depends on kind).
    width: float = Field(default=40.0, gt=0, le=100)
    height: float = Field(default=30.0, gt=0, le=100)
    # Corner rounding / fillet radius in abstract units (rectangles).
    corner_radius: float = Field(default=0.0, ge=0, le=50)
    # Free-text label (workflow-mode nodes; ignored by pure shapes).
    label: str | None = None
    # Stroke/fill hints — kept minimal; the low-fi look is the renderer's job.
    stroke: str = "#1f2937"
    fill: str | None = None
    # GROUP only: the composed primitives, each positioned in the SAME 0..100
    # box (absolute coords, no nesting transforms — keeps renderers trivial).
    parts: list[GeometrySpec] = Field(default_factory=list, max_length=60)
    # --- IR v2 fields. All default so v1 specs validate and render unchanged.
    # Addressable part name ("screen", "home-indicator") — lets a later MODIFY
    # target one part of a scene, and gives tests/drivers a stable hook.
    name: str | None = None
    # POLYGON: vertices in the 0..100 box.
    points: list[tuple[float, float]] | None = Field(default=None, min_length=3, max_length=32)
    # PATH: constrained SVG path data, 0..100 box, absolute uppercase commands
    # only (validated via domain/pathdata.py).
    d: str | None = Field(default=None, max_length=600)
    # TEXT: glyph size in abstract units (4 ≈ 15px in the 400px viewBox).
    font_size: float = Field(default=4.0, gt=0, le=20)
    # Stroke width in viewBox px; None = each renderer's default.
    stroke_width: float | None = Field(default=None, gt=0, le=10)
    # None = renderer default (server: solid; client: hachure).
    fill_style: FillStyle | None = None

    @model_validator(mode="after")
    def _check_kind_payload(self) -> GeometrySpec:
        if self.kind is ShapeKind.POLYGON and not self.points:
            raise ValueError("polygon requires `points`")
        if self.points is not None and not all(
            0.0 <= px <= 100.0 and 0.0 <= py <= 100.0 for px, py in self.points
        ):
            raise ValueError("polygon points must lie in the 0..100 box")
        if self.kind is ShapeKind.PATH:
            if not self.d:
                raise ValueError("path requires `d`")
            pathdata.parse(self.d)  # raises ValueError on anything malformed
        if self.kind is ShapeKind.TEXT and not self.label:
            raise ValueError("text requires `label`")
        if any(part.kind is ShapeKind.GROUP for part in self.parts):
            raise ValueError("groups must stay flat — no group inside parts")
        return self

    def cache_key(self) -> str:
        """Stable key for SVG render caching (RULES.md §6: cache repeated geometry)."""
        return self.model_dump_json()


def _scale_coord(v: float, scale: float) -> float:
    """Scale one coordinate about the box center (50, 50), clamped to the box."""
    return min(100.0, max(0.0, 50.0 + (v - 50.0) * scale))


def _scale_payload(geom: GeometrySpec, scale: float, updates: dict[str, object]) -> None:
    """Fold size scaling into the v2 payload fields (points / path data / text)."""
    if geom.points is not None:
        updates["points"] = [
            (_scale_coord(px, scale), _scale_coord(py, scale)) for px, py in geom.points
        ]
    if geom.d is not None:
        updates["d"] = pathdata.scale_about_center(geom.d, scale)
    if geom.kind is ShapeKind.TEXT:
        updates["font_size"] = min(20.0, max(0.5, geom.font_size * scale))


def apply_modifiers(geom: GeometrySpec, modifiers: list[str]) -> GeometrySpec:
    """Fold textual modifiers into a geometry spec — the one shared vocabulary.

    Both the classifier (resolving a CREATE's geometry) and the engine (MODIFYing
    an existing node) fold the same modifier strings the same way; keeping this in
    the domain stops the two stages from drifting or reaching into each other.

    Supported: ``fillet``/``rounded``, ``radius:<n>``, ``bigger``, ``smaller``,
    ``color:<css-color>``.
    """
    if geom.kind is ShapeKind.GROUP and geom.parts:
        # Scenes scale around the box center so parts keep their arrangement;
        # non-size modifiers (color, fillet) recurse into every part.
        scale = 1.0
        rest: list[str] = []
        for mod in modifiers:
            m = mod.strip().lower()
            if m == "bigger":
                scale *= 1.3
            elif m == "smaller":
                scale *= 0.7
            else:
                rest.append(mod)
        parts = []
        for part in geom.parts:
            p = apply_modifiers(part, rest)
            if scale != 1.0:
                update: dict[str, object] = {
                    "x": _scale_coord(p.x, scale),
                    "y": _scale_coord(p.y, scale),
                    "width": min(100.0, max(1.0, p.width * scale)),
                    "height": min(100.0, max(1.0, p.height * scale)),
                }
                _scale_payload(p, scale, update)
                p = p.model_copy(update=update)
            parts.append(p)
        return geom.model_copy(update={"parts": parts})

    updates: dict[str, object] = {}
    for mod in modifiers:
        m = mod.strip().lower()
        if m in ("fillet", "rounded"):
            updates["corner_radius"] = max(geom.corner_radius, 12.0)
        elif m.startswith("radius:"):
            try:
                updates["corner_radius"] = min(50.0, max(0.0, float(m.split(":", 1)[1])))
            except ValueError:
                pass
        elif m == "bigger":
            updates["width"] = min(100.0, geom.width * 1.3)
            updates["height"] = min(100.0, geom.height * 1.3)
            _scale_payload(geom, 1.3, updates)
        elif m == "smaller":
            updates["width"] = max(4.0, geom.width * 0.7)
            updates["height"] = max(4.0, geom.height * 0.7)
            _scale_payload(geom, 0.7, updates)
        elif m.startswith("color:"):
            color = m.split(":", 1)[1].strip()
            if color:
                if geom.fill is not None:
                    # Re-tint filled shapes: adopt target hue/saturation while
                    # preserving relative lightness so shading survives (the
                    # cuboid's light/mid/dark grays become light/mid/dark reds).
                    updates["fill"] = retint(geom.fill, color)
                    updates["stroke"] = retint(geom.stroke, color)
                else:
                    # Stroke-only sketch (QuickDraw line drawings): set the
                    # stroke exactly to the requested color, unchanged.
                    updates["stroke"] = color
    return geom.model_copy(update=updates) if updates else geom
