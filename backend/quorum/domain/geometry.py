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
