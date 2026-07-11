"""D4 instruction-adherence benchmark (plan.md §11 D4).

Unlike ``eval_llm.py`` (which scores JSON validity + parts-per-scene), this runs
a fixed set of intricate/3D/instruction-heavy prompts through the REAL stage-C
:class:`LLMClassifier` and scores how well each result ADHERES to the utterance
— part counts, named colors, coherence (anti exploded-view), spatial relations,
and 3D-shading — using the pure :mod:`quorum.eval.adherence` scorer (no vision
model). Reports a per-dimension + overall adherence table per model.

Run (from ``backend/``):

    uv run python scripts/eval_adherence.py --self-test     # keyless: score fixtures
    uv run python scripts/eval_adherence.py                 # default OpenRouter model
    uv run python scripts/eval_adherence.py model-a model-b # benchmark several models

Network mode needs an OpenRouter key in ``.env`` (QUORUM_OPENROUTER_API_KEY).
Do NOT run the network mode inside automated tests — it makes live API calls.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

from quorum.config.settings import Backend, Settings
from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind
from quorum.domain.isometric import Solid, project_solids
from quorum.domain.op import ClassifierContext, OpType
from quorum.eval.adherence import AdherenceScore, Expectation, Relation, score
from quorum.eval.battery import SETS
from quorum.pipeline.llm import LLMClassifier
from quorum.pipeline.renderer import SvgRenderer

# Cheap, JSON-capable OpenRouter models (verified against /models 2026-06-13);
# override by passing model ids as positional args.
_DEFAULT_MODELS = [
    "inclusionai/ling-2.6-flash",            # cheapest ($0.01/$0.03 per Mtok)
    "meta-llama/llama-3.1-8b-instruct",      # known mid-tier
    "mistralai/mistral-nemo",
    "qwen/qwen3-235b-a22b-2507",             # strong-but-cheap
    "openai/gpt-oss-20b",                    # small reasoning model
]

# The adherence prompt set now lives in ``quorum.eval.battery`` (tuning/held-out
# split for the refinement loop); select one with ``--set``. Each prompt is a
# single-shot CREATE annotated with machine-checkable expectations, so an empty
# context is correct and the LLM stage is isolated to model quality.

# OpenRouter passes through per-model upstream 429s; the cheapest models throttle
# rapid calls (≈10 req/min). Pace generously (--pace) to stay under the cap; a
# NOOP (conf 0) from an exhausted 429 triggers a paced retry so a transient
# rate-limit doesn't masquerade as a model failure (the "quota-corrupted row").
_RETRIES = 3
_RETRY_WAIT_S = 6.0


def _render_ok(renderer: SvgRenderer, geom: GeometrySpec | None) -> bool:
    if geom is None:
        return False
    try:
        renderer.render(geom)
        return True
    except Exception:
        return False


def _agg(scores: list[AdherenceScore], dim: str) -> float | None:
    vals = [s.applicable()[dim] for s in scores if dim in s.applicable()]
    return round(statistics.mean(vals), 2) if vals else None


async def _eval_model(
    model: str,
    api_key: str,
    pace_s: float,
    verbose: bool,
    prompts: list[tuple[str, Expectation]],
) -> dict[str, object]:
    clf = LLMClassifier(
        backend=Backend.OPENROUTER, model=model, api_key=api_key, record_diagnostics=True
    )
    renderer = SvgRenderer()
    scores: list[AdherenceScore] = []
    latencies: list[float] = []
    solids_used = 0
    solids_prompts = 0
    for i, (text, expect) in enumerate(prompts):
        op = None
        dt = 0.0
        for attempt in range(_RETRIES + 1):
            t0 = time.perf_counter()
            op = await clf.classify(
                text, speaker_id="eval", utterance_id=f"a{i}", context=ClassifierContext()
            )
            dt = time.perf_counter() - t0
            if op.confidence > 0:
                break
            if attempt < _RETRIES:
                await asyncio.sleep(_RETRY_WAIT_S)
        geom = op.geometry if (op and op.op_type is not OpType.NOOP) else None
        rendered = _render_ok(renderer, geom)
        s = score(geom, expect, rendered_ok=rendered, payload_kind=clf.last_payload_kind)
        scores.append(s)
        if rendered:
            latencies.append(dt)
        if expect.expect_3d:
            solids_prompts += 1
            if clf.last_payload_kind == "solids":
                solids_used += 1
        flag = "ok " if s.valid else "BAD"
        print(f"  {flag} [{dt:5.2f}s] overall={s.overall:.2f} {text!r}")
        if verbose:
            for n in s.notes:
                print(f"        - {n}")
        await asyncio.sleep(pace_s)

    valid = sum(1 for s in scores if s.valid)
    # `overall` is the mean over VALID responses only (quality conditional on a
    # drawing being produced), so it is comparable to the per-dimension columns
    # which also skip invalid rows; the `validity` column carries coverage. A
    # model is not double-penalised for a NOOP in both columns (review find).
    valid_overall = [s.overall for s in scores if s.valid]
    # Strict-overall: an INVALID (no-geometry) row counts as 0.0, so an outright
    # failure (e.g. a 3D wedge the model can't produce) is not hidden the way the
    # conditional `overall` column hides it. This is the refinement loop's fitness.
    strict_overall = round(statistics.mean([s.overall if s.valid else 0.0 for s in scores]), 3)
    return {
        "model": model,
        "validity": f"{valid}/{len(scores)}",
        "strict": strict_overall,
        "overall": round(statistics.mean(valid_overall), 2) if valid_overall else 0.0,
        "count": _agg(scores, "count"),
        "color": _agg(scores, "color"),
        "coherence": _agg(scores, "coherence"),
        "relations": _agg(scores, "relations"),
        "solids3d": _agg(scores, "solids3d"),
        "solids_rate": (f"{solids_used}/{solids_prompts}" if solids_prompts else "-"),
        "p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "p95_s": round(max(latencies), 2) if latencies else None,
    }


# --------------------------------------------------------------------------- #
# Keyless self-test: score known fixtures, assert the harness behaves.
# --------------------------------------------------------------------------- #
def _self_test() -> int:
    checks: list[tuple[str, bool]] = []

    house = GeometrySpec(kind=ShapeKind.GROUP, parts=[
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="wall", x=50, y=60, width=40, height=40),
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="window-left", x=40, y=55, width=8, height=8,
                     stroke="#2563eb", fill="#2563eb", fill_style=FillStyle.SOLID),
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="window-right", x=60, y=55, width=8, height=8,
                     stroke="#2563eb", fill="#2563eb", fill_style=FillStyle.SOLID),
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="door", x=50, y=72, width=10, height=16),
    ])
    sh = score(house, Expectation(counts={"window": 2, "door": 1}, colors=("blue",), min_parts=4,
                                  relations=(Relation("inside", "window-left", "wall"),)))
    checks.append(("coherent house scores 1.0", abs(sh.overall - 1.0) < 1e-9))

    exploded = GeometrySpec(kind=ShapeKind.GROUP, parts=[
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="a", x=10, y=10, width=8, height=8),
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="b", x=50, y=50, width=8, height=8),
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="c", x=90, y=90, width=8, height=8),
    ])
    se = score(exploded, Expectation(min_parts=3))
    checks.append(("exploded 3-island coherence == 0.0", se.coherence == 0.0))

    wc = score(house, Expectation(counts={"window": 5}))
    checks.append(("count 2/5 partial-credit < 1", wc.count is not None and wc.count < 1.0))

    # scorer-v2: a multi-part feature (each antenna = touching rod + tip) counts
    # ONCE per connected component, not per part. Two spaced antennas, each drawn
    # as a touching rod+tip pair (4 parts), must score 2/2 = 1.0 — the substring
    # count would over-count to 4/2 and score 0.0.
    def _r(name: str, x: float, y: float, w: float, h: float) -> GeometrySpec:
        return GeometrySpec(kind=ShapeKind.RECTANGLE, name=name, x=x, y=y, width=w, height=h)

    antennas = GeometrySpec(kind=ShapeKind.GROUP, parts=[
        _r("antenna-1-rod", 40, 40, 2, 20), _r("antenna-1-tip", 40, 28, 6, 6),
        _r("antenna-2-rod", 60, 40, 2, 20), _r("antenna-2-tip", 60, 28, 6, 6),
    ])
    ac = score(antennas, Expectation(counts={"antenna": 2}))
    checks.append(("two multi-part antennas count as 2 features (v2)", ac.count == 1.0))

    miscolor = score(house, Expectation(colors=("orange",)))
    checks.append(("absent color scores 0", miscolor.color == 0.0))

    proj = project_solids([Solid("box", 8, 0, 10, 64, 34, 22, "#6b7280", "block"),
                           Solid("cylinder", 16, 22, 20, 12, 12, 20, "#9ca3af", "piston-1")])
    s_kind = score(proj, Expectation(expect_3d=True, min_parts=2), payload_kind="solids")
    s_sig = score(proj, Expectation(expect_3d=True, min_parts=2))
    checks.append(("solids via payload_kind == 1.0", s_kind.solids3d == 1.0))
    checks.append(("solids via shading signature == 1.0", s_sig.solids3d == 1.0))

    flat3d = GeometrySpec(kind=ShapeKind.GROUP, parts=[
        GeometrySpec(kind=ShapeKind.RECTANGLE, name="box", x=50, y=50, width=30, height=30),
    ])
    s_flat = score(flat3d, Expectation(expect_3d=True))
    checks.append(("flat answer to 3D prompt scores solids3d 0", s_flat.solids3d == 0.0))

    checks.append(("invalid (no geometry) overall == 0", score(None, Expectation()).overall == 0.0))

    print("Adherence harness self-test (keyless):")
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    n_pass = sum(p for _, p in checks)
    print(f"\n{'ALL PASS' if ok else 'FAILURES PRESENT'} ({n_pass}/{len(checks)})")
    return 0 if ok else 1


def _print_table(rows: list[dict[str, object]]) -> None:
    cols = ["strict", "overall", "count", "color", "coherence", "relations", "solids3d"]
    print(f"\n{'model':<40} {'valid':>6} {'solids':>7} "
          + " ".join(f"{c:>9}" for c in cols) + f" {'p50':>5} {'p95':>5}")
    for r in rows:
        print(f"{r['model']!s:<40} {r['validity']!s:>6} {r['solids_rate']!s:>7} "
              + " ".join(f"{r[c]!s:>9}" for c in cols)
              + f" {r['p50_s']!s:>5} {r['p95_s']!s:>5}")


async def _run(
    models: list[str], pace_s: float, verbose: bool, prompts: list[tuple[str, Expectation]]
) -> int:
    api_key = Settings().require_openrouter_key()
    rows = []
    for model in models:
        print(f"\n=== {model}")
        rows.append(await _eval_model(model, api_key, pace_s, verbose, prompts))
    _print_table(rows)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="D4 instruction-adherence benchmark")
    parser.add_argument("models", nargs="*", help="OpenRouter model ids (default: cheap tier)")
    parser.add_argument("--self-test", action="store_true",
                        help="Keyless: score fixtures to verify the harness, then exit")
    parser.add_argument("--set", choices=("tuning", "heldout", "all"), default="all",
                        help="Which battery slice to run (default: all)")
    parser.add_argument("--pace", type=float, default=0.5, help="Seconds between calls")
    parser.add_argument("--verbose", action="store_true", help="Print per-dimension notes")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    return asyncio.run(
        _run(args.models or _DEFAULT_MODELS, args.pace, args.verbose, SETS[args.set])
    )


if __name__ == "__main__":
    sys.exit(main())
