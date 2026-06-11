"""D2 drawing-quality evaluation script.

Runs 10 fixed prompts sequentially through the full cascade (including live LLM
calls), saves SVGs, and prints a summary table with quality signals.

Usage (from backend/):
    uv run python scripts/eval_d2.py --mode before
    uv run python scripts/eval_d2.py --mode after

GROQ pacing: 12-second inter-call gap; retries once on 429 after 20 seconds.
Do NOT run in automated tests — this makes live API calls.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from quorum.engine import DesignStateEngine
from quorum.pipeline.classify import build_classifier

PROMPTS: list[str] = [
    "a 3D engine with pistons",
    "a 3D car",
    "an isometric house with a chimney",
    "a coffee mug with steam",
    "a desk lamp",
    "a castle with two towers",
    "a sailboat on water",
    "a simple bicycle",
    "a snowman wearing a top hat",
    "a rocket with three fins, colored in",
]

_INTER_CALL_SECONDS = 12
_RETRY_WAIT_SECONDS = 20


def _bbox(part):  # type: ignore[no-untyped-def]
    """Returns (x1, y1, x2, y2) axis-aligned bounding box for a part."""
    if part.points:
        xs = [p[0] for p in part.points]
        ys = [p[1] for p in part.points]
        return min(xs), min(ys), max(xs), max(ys)
    hw = (part.width or 10) / 2
    hh = (part.height or 10) / 2
    return part.x - hw, part.y - hh, part.x + hw, part.y + hh


def _overlaps(parts):  # type: ignore[no-untyped-def]
    """True if any two parts' bboxes overlap (strict interior intersection)."""
    boxes = [_bbox(p) for p in parts]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            x1a, y1a, x2a, y2a = boxes[i]
            x1b, y1b, x2b, y2b = boxes[j]
            if x1a < x2b and x2a > x1b and y1a < y2b and y2a > y1b:
                return True
    return False


def _summarise(op, latency_s: float) -> dict:  # type: ignore[no-untyped-def]
    """Compute summary dict for one prompt result."""
    geom = op.geometry
    if geom is None:
        return {
            "stage": op.source_stage,
            "op_type": str(op.op_type),
            "part_count": 0,
            "fills_used": 0,
            "overlap": False,
            "latency_s": latency_s,
        }

    from quorum.domain.geometry import ShapeKind

    if geom.kind is ShapeKind.GROUP:
        parts = geom.parts
        part_count = len(parts)
        fills_used = sum(1 for p in parts if p.fill is not None)
        overlap = _overlaps(parts)
    else:
        part_count = 1
        fills_used = 1 if geom.fill is not None else 0
        overlap = False

    return {
        "stage": op.source_stage,
        "op_type": str(op.op_type),
        "part_count": part_count,
        "fills_used": fills_used,
        "overlap": overlap,
        "latency_s": latency_s,
    }


async def run_eval(mode: str) -> None:
    clf = build_classifier()
    summaries: list[dict] = []

    for i, prompt in enumerate(PROMPTS):
        if i > 0:
            print(f"  [pacing: waiting {_INTER_CALL_SECONDS}s before next call]")
            await asyncio.sleep(_INTER_CALL_SECONDS)

        # Fresh engine per prompt — independent scenes
        eng = DesignStateEngine(room=f"eval_{mode}_{i}")
        ctx = eng.classifier_context()

        attempt = 0
        op = None
        while attempt < 2:
            t0 = time.perf_counter()
            try:
                op = await clf.classify(
                    prompt, speaker_id="eval", utterance_id=f"u{i}", context=ctx
                )
                latency_s = time.perf_counter() - t0
                break
            except Exception as exc:
                latency_s = time.perf_counter() - t0
                err = str(exc)
                if "429" in err and attempt == 0:
                    print(f"  [429 on prompt {i}, retrying after {_RETRY_WAIT_SECONDS}s]")
                    await asyncio.sleep(_RETRY_WAIT_SECONDS)
                    attempt += 1
                    continue
                print(f"  [error on prompt {i}: {exc}]")
                break

        if op is None:
            # Build a dummy NOOP so we can still record timing
            from quorum.domain.op import DesignOp, OpType
            op = DesignOp(
                op_type=OpType.NOOP,
                speaker_id="eval",
                utterance_id=f"u{i}",
                confidence=0.0,
                source_stage="error",
                raw_text=prompt,
            )
            latency_s = 0.0

        diff = eng.apply(op)
        summary = _summarise(op, latency_s)
        summaries.append(summary)

        # Save SVG
        svg_path = Path(f"/tmp/d2_{mode}_{i}.svg")
        svg_content = "<svg/>"
        for node in diff.upserted:
            if node.svg:
                svg_content = node.svg
                break
        # Write synchronously — this is a CLI eval script, not a server handler
        svg_path.write_text(svg_content)  # noqa: ASYNC240

        print(
            f"[{i:2d}] {prompt[:40]!r:<42} "
            f"stage={summary['stage']:<8} op={summary['op_type']:<8} "
            f"parts={summary['part_count']} fills={summary['fills_used']} "
            f"overlap={'Y' if summary['overlap'] else 'N'} "
            f"lat={summary['latency_s']:.2f}s -> {svg_path}"
        )

    # Summary table
    print()
    print(
        f"{'i':>2}  {'prompt':30}  {'stage':<8}  {'op':<8}  "
        f"{'parts':>5}  {'fills':>5}  {'over':>4}  {'lat(s)':>6}"
    )
    print("-" * 80)
    for i, (prompt, s) in enumerate(zip(PROMPTS, summaries, strict=True)):
        print(
            f"{i:2d}  {prompt[:30]:<30}  {s['stage']:<8}  {s['op_type']:<8}  "
            f"{s['part_count']:>5}  {s['fills_used']:>5}  "
            f"{'Y' if s['overlap'] else 'N':>4}  {s['latency_s']:>6.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="D2 drawing-quality eval")
    parser.add_argument(
        "--mode",
        choices=["before", "after"],
        required=True,
        help="Tag SVGs as d2_before_<i>.svg or d2_after_<i>.svg",
    )
    args = parser.parse_args()
    asyncio.run(run_eval(args.mode))


if __name__ == "__main__":
    main()
