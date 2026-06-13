"""Eyeball-gate helper for D3 (plan.md §11): render the deterministic isometric
projection of a few solid assemblies to SVG (+ PNG via qlmanage) so a human/
agent can verify the projection, shading, hidden-face removal and depth-sort.

    uv run python scripts/render_d3.py
    # writes /tmp/d3_<name>.svg and /tmp/d3_<name>.png

This drives `domain.isometric.project_solids` exactly as `pipeline/llm.py`'s
`payload_to_op` does for an LLM `solids` payload — no LLM call, fully offline.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from quorum.domain.isometric import Solid, project_solids
from quorum.pipeline.renderer import SvgRenderer

_OUT = Path("/tmp")

_SCENES: dict[str, list[Solid]] = {
    "cube": [Solid("box", 20, 20, 20, 30, 30, 30, color="#dc2626", name="cube")],
    "wedge": [Solid("wedge", 20, 0, 20, 40, 30, 30, color="#2563eb", name="ramp")],
    "cylinder": [Solid("cylinder", 20, 0, 20, 24, 24, 44, color="#16a34a", name="can")],
    "engine": [
        Solid("box", 8, 0, 10, 64, 34, 22, color="#6b7280", name="block"),
        Solid("cylinder", 16, 22, 20, 12, 12, 20, color="#9ca3af", name="piston-1"),
        Solid("cylinder", 34, 22, 20, 12, 12, 20, color="#9ca3af", name="piston-2"),
        Solid("cylinder", 52, 22, 20, 12, 12, 20, color="#9ca3af", name="piston-3"),
    ],
    "stack": [
        Solid("box", 0, 0, 0, 40, 40, 16, color="#9ca3af", name="base"),
        Solid("box", 10, 16, 10, 22, 22, 18, color="#6b7280", name="mid"),
        Solid("box", 16, 34, 16, 10, 10, 14, color="#374151", name="top"),
    ],
}


def main() -> int:
    renderer = SvgRenderer()
    for name, solids in _SCENES.items():
        spec = project_solids(solids)
        if spec is None:
            print(f"FAIL {name}: project_solids returned None")
            continue
        svg = renderer.render(spec)
        svg_path = _OUT / f"d3_{name}.svg"
        svg_path.write_text(svg)
        n_parts = len(spec.parts)
        # PNG thumbnail for eyeballing (best-effort; needs the macOS SVG QL plugin)
        subprocess.run(
            ["qlmanage", "-t", "-s", "512", "-o", str(_OUT), str(svg_path)],
            capture_output=True,
        )
        print(f"ok   {name}: {n_parts} parts -> {svg_path}  (+ d3_{name}.svg.png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
