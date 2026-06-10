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

from pydantic import BaseModel, Field


class ShapeKind(StrEnum):
    """The primitive shapes Quorum can sketch (geometry mode)."""

    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    TRIANGLE = "triangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    # workflow-mode primitives (Phase 2+): a labelled box and a connector
    NODE = "node"
    EDGE = "edge"


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

    def cache_key(self) -> str:
        """Stable key for SVG render caching (RULES.md §6: cache repeated geometry)."""
        return self.model_dump_json()


def apply_modifiers(geom: GeometrySpec, modifiers: list[str]) -> GeometrySpec:
    """Fold textual modifiers into a geometry spec — the one shared vocabulary.

    Both the classifier (resolving a CREATE's geometry) and the engine (MODIFYing
    an existing node) fold the same modifier strings the same way; keeping this in
    the domain stops the two stages from drifting or reaching into each other.

    Supported: ``fillet``/``rounded``, ``radius:<n>``, ``bigger``, ``smaller``,
    ``color:<css-color>``.
    """
    updates: dict[str, float | str] = {}
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
        elif m == "smaller":
            updates["width"] = max(4.0, geom.width * 0.7)
            updates["height"] = max(4.0, geom.height * 0.7)
        elif m.startswith("color:"):
            color = m.split(":", 1)[1].strip()
            if color:
                updates["stroke"] = color
    return geom.model_copy(update=updates) if updates else geom
