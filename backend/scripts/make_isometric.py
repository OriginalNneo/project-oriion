"""Generate exact isometric/3D templates into ``templates/isometric.json``.

Unlike the mined Quick, Draw! bank (wobbly human strokes), these are computed:
a true isometric projection (30°) with per-face shading — light top, mid
front, dark side — so "a 3D cube" / "a cylinder" / "a gear" snap out crisp at
0 ms via the template stage, and double as high-quality references for the
LLM when they appear inside larger scenes.

Run (no network):

    uv run python scripts/make_isometric.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from quorum.domain.geometry import GeometrySpec
from quorum.pipeline.renderer import SvgRenderer

_OUT = Path(__file__).resolve().parents[1] / "quorum" / "pipeline" / "templates" / "isometric.json"

_STROKE = "#1f2937"
_LIGHT, _MID, _DARK = "#e5e7eb", "#9ca3af", "#6b7280"

_COS30 = math.cos(math.pi / 6)  # 0.866
_SIN30 = 0.5


def _project(px: float, py: float, pz: float) -> tuple[float, float]:
    """World (x right, y UP, z toward viewer-left) -> 0..100 screen (y down)."""
    sx = (px - pz) * _COS30
    sy = (px + pz) * _SIN30 - py
    return sx, sy


def _polygon(
    pts3: list[tuple[float, float, float]], fill: str, name: str
) -> dict[str, Any]:
    pts = [_project(*p) for p in pts3]
    return _polygon2d(pts, fill, name)


def _polygon2d(pts: list[tuple[float, float]], fill: str, name: str) -> dict[str, Any]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {
        "kind": "polygon",
        "name": name,
        "x": round((min(xs) + max(xs)) / 2, 1),
        "y": round((min(ys) + max(ys)) / 2, 1),
        "width": round(max(max(xs) - min(xs), 1.0), 1),
        "height": round(max(max(ys) - min(ys), 1.0), 1),
        "stroke": _STROKE,
        "fill": fill,
        "fill_style": "solid",
        "points": [[round(x, 1), round(y, 1)] for x, y in pts],
    }


def _fit(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Center/scale a group of polygon/ellipse/path parts into 8..92."""
    xs: list[float] = []
    ys: list[float] = []
    for p in parts:
        if "points" in p and p.get("points"):
            xs += [pt[0] for pt in p["points"]]
            ys += [pt[1] for pt in p["points"]]
        else:
            xs += [p["x"] - p["width"] / 2, p["x"] + p["width"] / 2]
            ys += [p["y"] - p["height"] / 2, p["y"] + p["height"] / 2]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    scale = 84.0 / max(x1 - x0, y1 - y0, 1.0)
    ox = (100 - (x1 - x0) * scale) / 2 - x0 * scale
    oy = (100 - (y1 - y0) * scale) / 2 - y0 * scale

    def fx(v: float) -> float:
        return round(v * scale + ox, 1)

    def fy(v: float) -> float:
        return round(v * scale + oy, 1)

    for p in parts:
        if "points" in p and p.get("points"):
            p["points"] = [[fx(px), fy(py)] for px, py in p["points"]]
        if "d" in p and p.get("d"):
            p["d"] = _scale_path(p["d"], scale, ox, oy)
        p["x"], p["y"] = fx(p["x"]), fy(p["y"])
        p["width"] = round(p["width"] * scale, 1)
        p["height"] = round(p["height"] * scale, 1)
    return {"kind": "group", "parts": parts}


def _scale_path(d: str, scale: float, ox: float, oy: float) -> str:
    """Rescale a constrained path: coordinates map; arc radii scale only."""
    out: list[str] = []
    tokens = d.replace(",", " ").split()
    i = 0
    cmd = ""
    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            out.append(t)
            i += 1
            continue
        if cmd == "A":  # rx ry rot large sweep x y
            rx, ry, rot, la, sw, x, y = tokens[i : i + 7]
            out += [
                f"{float(rx) * scale:.1f}",
                f"{float(ry) * scale:.1f}",
                rot,
                la,
                sw,
                f"{float(x) * scale + ox:.1f}",
                f"{float(y) * scale + oy:.1f}",
            ]
            i += 7
            continue
        x, y = tokens[i], tokens[i + 1]
        out += [f"{float(x) * scale + ox:.1f}", f"{float(y) * scale + oy:.1f}"]
        i += 2
    return " ".join(out)


def _box(w: float, h: float, d: float) -> list[dict[str, Any]]:
    """Visible faces of a w-by-h-by-d box sitting at the origin."""
    return [
        _polygon([(0, h, d), (w, h, d), (w, h, 0), (0, h, 0)], _LIGHT, "face-top"),
        _polygon([(0, 0, d), (w, 0, d), (w, h, d), (0, h, d)], _MID, "face-front"),
        _polygon([(w, 0, d), (w, 0, 0), (w, h, 0), (w, h, d)], _DARK, "face-right"),
    ]


def _pyramid(w: float, h: float) -> list[dict[str, Any]]:
    apex = (w / 2, h, w / 2)
    a, b, c = (0.0, 0.0, w), (w, 0.0, w), (w, 0.0, 0.0)
    return [
        _polygon([apex, a, b], _MID, "face-front"),
        _polygon([apex, b, c], _DARK, "face-right"),
    ]


def _cylinder(r: float, h: float) -> list[dict[str, Any]]:
    ry = r * 0.38
    body = {
        "kind": "path",
        "name": "body",
        "x": 50.0,
        "y": 50.0,
        "width": 2 * r,
        "height": h + ry,
        "stroke": _STROKE,
        "fill": _MID,
        "fill_style": "solid",
        # left edge down, bottom bulge (lower half-ellipse), right edge up
        "d": f"M {50 - r} 30 L {50 - r} {30 + h} "
        f"A {r} {ry} 0 0 0 {50 + r} {30 + h} L {50 + r} 30 Z",
    }
    top = {
        "kind": "ellipse",
        "name": "top",
        "x": 50.0,
        "y": 30.0,
        "width": 2 * r,
        "height": 2 * ry,
        "stroke": _STROKE,
        "fill": _LIGHT,
        "fill_style": "solid",
    }
    return [body, top]


def _cone(r: float, h: float) -> list[dict[str, Any]]:
    ry = r * 0.38
    body = {
        "kind": "path",
        "name": "body",
        "x": 50.0,
        "y": 50.0,
        "width": 2 * r,
        "height": h + ry,
        "stroke": _STROKE,
        "fill": _MID,
        "fill_style": "solid",
        # base arc runs right->left, so the downward bulge needs sweep=1
        "d": f"M {50 - r} {20 + h} L 50 20 L {50 + r} {20 + h} "
        f"A {r} {ry} 0 0 1 {50 - r} {20 + h} Z",
    }
    return [body]


def _sphere(r: float) -> list[dict[str, Any]]:
    return [
        {
            "kind": "circle",
            "name": "ball",
            "x": 50.0,
            "y": 50.0,
            "width": 2 * r,
            "height": 2 * r,
            "stroke": _STROKE,
            "fill": _LIGHT,
            "fill_style": "solid",
        },
        {
            "kind": "ellipse",
            "name": "equator",
            "x": 50.0,
            "y": 50.0,
            "width": 2 * r,
            "height": r * 0.6,
            "stroke": _STROKE,
            "fill": None,
            "fill_style": "none",
        },
    ]


def _gear(teeth: int = 8, r_out: float = 44.0, r_in: float = 34.0) -> list[dict[str, Any]]:
    pts: list[tuple[float, float]] = []
    step = 2 * math.pi / teeth
    for i in range(teeth):  # 4 vertices per tooth -> 32 points (polygon cap)
        a = i * step
        for frac, r in ((0.0, r_in), (0.25, r_in), (0.3, r_out), (0.7, r_out)):
            ang = a + frac * step
            pts.append((50 + r * math.cos(ang), 50 + r * math.sin(ang)))
    return [
        _polygon2d(pts, _MID, "teeth"),
        {
            "kind": "circle",
            "name": "hub",
            "x": 50.0,
            "y": 50.0,
            "width": 24.0,
            "height": 24.0,
            "stroke": _STROKE,
            "fill": _LIGHT,
            "fill_style": "solid",
        },
    ]


def _staircase(steps: int = 3, w: float = 26.0, rise: float = 11.0, run: float = 11.0
               ) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    # right-side profile (x = w plane), walking the step outline
    profile: list[tuple[float, float, float]] = [(w, 0, 0)]
    z = steps * run
    profile.append((w, 0, z))
    for k in range(steps):
        y1 = (k + 1) * rise
        z_front = z - k * run
        profile.append((w, y1, z_front))
        profile.append((w, y1, z_front - run))
    profile.append((w, steps * rise, 0))
    parts.append(_polygon(profile, _DARK, "side"))
    for k in range(steps):
        y1 = (k + 1) * rise
        z_front = z - k * run
        parts.append(
            _polygon(
                [(0, k * rise, z_front), (w, k * rise, z_front),
                 (w, y1, z_front), (0, y1, z_front)],
                _MID,
                f"riser-{k + 1}",
            )
        )
        parts.append(
            _polygon(
                [(0, y1, z_front), (w, y1, z_front),
                 (w, y1, z_front - run), (0, y1, z_front - run)],
                _LIGHT,
                f"tread-{k + 1}",
            )
        )
    return parts


def main() -> int:
    shapes: dict[str, list[dict[str, Any]]] = {
        "cube": _box(36, 36, 36),
        "cuboid": _box(52, 22, 26),
        "pyramid": _pyramid(46, 40),
        "cylinder": _cylinder(20, 42),
        "cone": _cone(22, 44),
        "sphere": _sphere(36),
        "gear": _gear(),
        "staircase": _staircase(),
    }
    renderer = SvgRenderer()
    out: dict[str, Any] = {}
    for name, parts in shapes.items():
        spec_dict = _fit(parts)
        spec = GeometrySpec.model_validate(spec_dict)
        svg = renderer.render(spec)
        assert svg.startswith("<svg"), name
        out[name] = spec_dict
        print(f"ok   {name}: {len(parts)} part(s)")
    _OUT.write_text(
        json.dumps(
            {
                "_attribution": "Parametric isometric primitives generated by "
                "scripts/make_isometric.py (no external data).",
                "templates": out,
            },
            separators=(",", ":"),
        )
    )
    print(f"wrote {len(out)} templates -> {_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
