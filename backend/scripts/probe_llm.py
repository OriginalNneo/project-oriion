"""Live stage-C probe: drive real utterances through the cascade + engine.

Run from ``backend/`` (so ``.env`` with the Groq key loads):

    uv run python scripts/probe_llm.py "a 3D cube" "a simple smartphone"

Utterances run *sequentially against one engine*, so follow-ups ("now add five
thrusters") exercise the real focus_geometry/extend path. Each resulting node's
reference SVG is written to ``/tmp/probe_<i>.svg`` for eyeballing.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from quorum.domain.geometry import GeometrySpec
from quorum.engine import DesignStateEngine
from quorum.pipeline.classify import build_classifier

_DEFAULT = [
    "a funnel turned on its side",
    "now add five thrusters to it",
    "a 3D cube",
    "a simple smartphone",
    "a snowman with a red scarf and a blue hat, colored in",
]


def _summ(s: GeometrySpec) -> str:
    bits = [str(s.kind)]
    if s.name:
        bits.append(f"name={s.name}")
    bits.append(f"at({s.x:.0f},{s.y:.0f}) {s.width:.0f}x{s.height:.0f}")
    bits.append(f"stroke={s.stroke}")
    if s.fill:
        bits.append(f"fill={s.fill}")
    if s.fill_style:
        bits.append(f"fill_style={s.fill_style}")
    if s.points:
        bits.append(f"{len(s.points)}pts")
    if s.d:
        bits.append(f"d[{len(s.d)}ch]")
    if s.label:
        bits.append(f"label={s.label!r}")
    return " ".join(bits)


async def main(utterances: list[str]) -> list[tuple[Path, str]]:
    clf = build_classifier()
    eng = DesignStateEngine(room="probe")
    svgs: list[tuple[Path, str]] = []
    for i, text in enumerate(utterances):
        ctx = eng.classifier_context()
        t0 = time.perf_counter()
        op = await clf.classify(text, speaker_id="probe", utterance_id=f"u{i}", context=ctx)
        dt = time.perf_counter() - t0
        diff = eng.apply(op)
        print(f"\n=== {text!r}  [{dt:.2f}s  stage={op.source_stage}  "
              f"op={op.op_type}  conf={op.confidence:.2f}]")
        if op.geometry is not None:
            print(f"  {_summ(op.geometry)}")
            for p in op.geometry.parts:
                print(f"    - {_summ(p)}")
        else:
            print("  (no geometry)")
        for n in diff.upserted:
            if n.svg is None:
                continue
            out = Path(f"/tmp/probe_{i}.svg")
            svgs.append((out, n.svg))
            print(f"  node={n.id} -> {out}")
    return svgs


if __name__ == "__main__":
    for path, svg in asyncio.run(main(sys.argv[1:] or _DEFAULT)):
        path.write_text(svg)
