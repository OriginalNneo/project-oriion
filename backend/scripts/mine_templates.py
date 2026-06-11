"""Mine Google Quick, Draw! into Quorum IR geometry templates.

Source: the public simplified-drawing dumps (one ndjson per category,
strokes RDP-simplified into a 0..255 box) from
``storage.googleapis.com/quickdraw_dataset`` — CC-BY-4.0 (attribution:
"Quick, Draw! dataset, Google" — see the templates JSON header).

Mines **every** official category (list fetched from the dataset repo; the
curated list below is the offline fallback). For each category it scans the
first few hundred drawings and keeps the most *elaborate* recognized one that
still fits our IR caps — scored by stroke/point richness — then rescales
0..255 → 8..92 (aspect kept), downsamples each stroke to ≤30 points, and emits
one GeometrySpec dict: a single ``path`` for one-stroke drawings, else a
``group`` of paths. Every template is validated AND rendered before writing.

Run (network; ~1 request per category):

    uv run python scripts/mine_templates.py            # all official categories
    uv run python scripts/mine_templates.py --curated  # fallback curated list
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx

from quorum.domain.geometry import GeometrySpec
from quorum.pipeline.renderer import SvgRenderer

_BASE = "https://storage.googleapis.com/quickdraw_dataset/full/simplified"
_OUT = Path(__file__).resolve().parents[1] / "quorum" / "pipeline" / "templates" / "quickdraw.json"

# Curated, design-conversation-relevant categories (exact Quick, Draw! names).
CATEGORIES = [
    "airplane", "alarm clock", "ambulance", "apple", "axe", "backpack",
    "basket", "bathtub", "bed", "bench", "bicycle", "binoculars", "bird",
    "bridge", "broom", "bucket", "bulldozer", "bus", "butterfly", "cactus",
    "camera", "campfire", "candle", "cannon", "canoe", "car", "castle", "cat",
    "ceiling fan", "cell phone", "chair", "church", "clock", "cloud",
    "coffee cup", "compass", "computer", "couch", "crown", "cruise ship",
    "cup", "dog", "door", "drill", "duck", "dumbbell", "envelope",
    "eyeglasses", "fan", "fence", "fire hydrant", "fish", "flashlight",
    "flower", "fork", "frying pan", "guitar", "hammer", "hat", "headphones",
    "helicopter", "helmet", "hospital", "hot air balloon", "house", "key",
    "keyboard", "knife", "ladder", "lantern", "laptop", "light bulb",
    "lighthouse", "lightning", "mailbox", "megaphone", "microphone",
    "microwave", "motorbike", "mountain", "mug", "mushroom", "pencil",
    "piano", "pickup truck", "pliers", "police car", "pond", "power outlet",
    "rabbit", "radio", "rain", "rainbow", "rake", "remote control",
    "rifle", "river", "rollerskates", "sailboat", "saw", "scissors",
    "screwdriver", "shovel", "skateboard", "skull", "skyscraper", "snowman",
    "speedboat", "spider", "stairs", "stethoscope", "stove",
    "submarine", "suitcase", "sun", "swing set", "sword", "syringe", "table",
    # NOTE: "street light" and "watch" are NOT Quick, Draw! categories (404).
    "telephone", "television", "tent", "toaster", "toilet", "toothbrush",
    "tractor", "traffic light", "train", "tree", "truck", "umbrella", "van",
    "violin", "washing machine", "wheel", "windmill", "wine glass",
    "wristwatch", "zigzag",
]

_MAX_STROKES = 16          # group parts cap is 60; 16 keeps sketches readable
_MAX_STROKE_POINTS = 30    # path cap: 64 commands / 200 numbers / 600 chars
_SCAN_LINES = 1000         # how deep to look for a good drawing per category
_CATEGORIES_URL = (
    "https://raw.githubusercontent.com/googlecreativelab/quickdraw-dataset"
    "/master/categories.txt"
)


def _downsample(xs: list[int], ys: list[int], cap: int) -> tuple[list[int], list[int]]:
    n = len(xs)
    if n <= cap:
        return xs, ys
    idx = [round(i * (n - 1) / (cap - 1)) for i in range(cap)]
    return [xs[i] for i in idx], [ys[i] for i in idx]


def _candidates(
    lines: list[str], *, min_strokes: int
) -> list[tuple[int, list[list[list[int]]]]]:
    out: list[tuple[int, list[list[list[int]]]]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("recognized"):
            continue
        drawing: list[list[list[int]]] = row.get("drawing", [])
        strokes = len(drawing)
        total = sum(len(s[0]) for s in drawing)
        if not (min_strokes <= strokes <= _MAX_STROKES and 12 <= total <= 320):
            continue
        if total / strokes > 32:  # one long dense stroke = a scribble, not a sketch
            continue
        out.append((total, drawing))
    return out


def _pick(lines: list[str]) -> list[list[list[int]]] | None:
    """A *canonically structured* recognized drawing, not the densest one.

    Max-points selection favors scribblers and pure medians favor sloppy
    typicals. Instead: (1) find the MODAL stroke count across the candidate
    pool — the crowd's canonical decomposition of the object (snowman = 3
    strokes, house = 5...) — then (2) within that modal group take the drawing
    closest to 1.2x the group's median point count: slightly richer than
    typical, same recognizable structure. Single-stroke is the fallback for
    inherently-one-line categories (zigzag, circle, moon...).
    """
    pool = _candidates(lines, min_strokes=2) or _candidates(lines, min_strokes=1)
    if not pool:
        return None
    counts = statistics.multimode(len(d) for _, d in pool)
    modal = max(counts)  # ties -> the richer decomposition
    group = [c for c in pool if len(c[1]) == modal]
    target = 1.2 * statistics.median(t for t, _ in group)
    return min(group, key=lambda c: abs(c[0] - target))[1]


def _all_categories(client: httpx.Client) -> list[str]:
    """The official category list; falls back to the curated one on failure."""
    try:
        resp = client.get(_CATEGORIES_URL)
        resp.raise_for_status()
        cats = [c.strip() for c in resp.text.splitlines() if c.strip()]
        if len(cats) > 200:
            return cats
    except Exception as exc:
        print(f"category list fetch failed ({exc}); using curated fallback")
    return CATEGORIES


def _to_spec(drawing: list[list[list[int]]]) -> dict[str, Any]:
    xs_all = [x for s in drawing for x in s[0]]
    ys_all = [y for s in drawing for y in s[1]]
    x0, x1 = min(xs_all), max(xs_all)
    y0, y1 = min(ys_all), max(ys_all)
    span = max(x1 - x0, y1 - y0, 1)
    scale = 84.0 / span
    # center the (aspect-preserved) drawing in the 0..100 box
    ox = (100.0 - (x1 - x0) * scale) / 2.0
    oy = (100.0 - (y1 - y0) * scale) / 2.0

    def tx(x: int) -> float:
        return round(ox + (x - x0) * scale, 1)

    def ty(y: int) -> float:
        return round(oy + (y - y0) * scale, 1)

    paths: list[dict[str, Any]] = []
    for stroke in drawing:
        sx, sy = _downsample(stroke[0], stroke[1], _MAX_STROKE_POINTS)
        pts = [(tx(x), ty(y)) for x, y in zip(sx, sy, strict=True)]
        d = "M" + " L".join(f"{px:g} {py:g}" for px, py in pts)
        pxs = [p[0] for p in pts]
        pys = [p[1] for p in pts]
        paths.append(
            {
                "kind": "path",
                "x": round((min(pxs) + max(pxs)) / 2, 1),
                "y": round((min(pys) + max(pys)) / 2, 1),
                "width": round(max(max(pxs) - min(pxs), 1.0), 1),
                "height": round(max(max(pys) - min(pys), 1.0), 1),
                "d": d,
                "fill_style": "none",
            }
        )
    if len(paths) == 1:
        return paths[0]
    return {"kind": "group", "parts": paths}


def main() -> int:
    renderer = SvgRenderer()
    out: dict[str, Any] = {}
    failed: list[str] = []
    with httpx.Client(timeout=30.0) as client:
        cats = CATEGORIES if "--curated" in sys.argv[1:] else _all_categories(client)
        for cat in cats:
            url = f"{_BASE}/{cat}.ndjson"
            try:
                lines: list[str] = []
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        lines.append(line)
                        if len(lines) >= _SCAN_LINES:
                            break
                drawing = _pick(lines)
                if drawing is None:
                    failed.append(f"{cat} (no suitable drawing in {len(lines)} rows)")
                    continue
                spec_dict = _to_spec(drawing)
                spec = GeometrySpec.model_validate(spec_dict)  # hard validation
                renderer.render(spec)  # must render through the reference renderer
                out[cat] = spec_dict
                n = 1 if spec_dict["kind"] == "path" else len(spec_dict["parts"])
                print(f"ok   {cat}: {n} stroke(s)")
            except Exception as exc:  # report and continue mining
                failed.append(f"{cat} ({exc})")
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(
        json.dumps(
            {
                "_attribution": "Templates derived from the Quick, Draw! dataset "
                "(Google, https://quickdraw.withgoogle.com/data), CC-BY-4.0.",
                "templates": out,
            },
            indent=None,
            separators=(",", ":"),
        )
    )
    print(f"\nwrote {len(out)} templates -> {_OUT}")
    if failed:
        print(f"FAILED ({len(failed)}):")
        for f in failed:
            print(f"  - {f}")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
