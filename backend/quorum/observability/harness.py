"""Latency harness — a repeatable rig that times the loop end to end.

RULES.md §6 requires a repeatable latency harness from Phase 1 onward (fixed
sample utterances -> run the loop -> log per-stage timings, track p50/p95). We
stand it up now in Phase 0 so the discipline exists before the slow stages
(STT/LLM) arrive — adding a stage means adding its timer, not building the rig.

It drives the *real* engine + classifier + renderer (the parts that exist), and
reports per-stage p50/p95 plus the end-to-end common-case figure. STT/VAD/LLM
rows are absent until those stages land; the harness picks them up automatically
via the shared ledger once they call ``stage_timer``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from quorum.engine import DesignStateEngine
from quorum.engine.clock import SystemClock
from quorum.observability.latency import LatencyLedger, get_ledger, stage_timer
from quorum.pipeline.classify import MockClassifier

# Fixed sample utterances — the repeatable corpus. Mix of create/branch/modify/
# preference so the cascade fast path is exercised the way a real session would.
SAMPLE_UTTERANCES: list[str] = [
    "draw a rectangle",
    "a rectangle with a fillet",
    "how about a triangle instead",
    "make it bigger",
    "a circle",
    "let's go with the triangle",
    "an ellipse",
    "add a fillet",
]


@dataclass
class HarnessResult:
    iterations: int
    e2e_p50_ms: float
    e2e_p95_ms: float
    per_stage: dict[str, dict[str, float]]


async def run_loop_benchmark(
    iterations: int = 50, *, ledger: LatencyLedger | None = None
) -> HarnessResult:
    """Run the classify->engine->render loop over the sample corpus N times.

    Returns per-stage p50/p95 (from the shared ledger) and the measured
    end-to-end common-case latency (no STT/LLM yet, so this is the fast path).
    """
    ledger = ledger or get_ledger()
    ledger.reset()
    classifier = MockClassifier()
    engine = DesignStateEngine(room="bench", clock=SystemClock())

    e2e: list[float] = []
    for i in range(iterations):
        text = SAMPLE_UTTERANCES[i % len(SAMPLE_UTTERANCES)]
        uid = f"bench:u{i}"
        start = time.perf_counter()
        async with stage_timer("classify", utterance_id=uid):
            op = await classifier.classify(
                text,
                speaker_id="bench",
                utterance_id=uid,
                context=engine.classifier_context(),
            )
        engine.apply(op)  # records 'engine' + 'render' stage timings internally
        e2e.append((time.perf_counter() - start) * 1000.0)

    e2e_sorted = sorted(e2e)
    p50 = e2e_sorted[len(e2e_sorted) // 2]
    p95 = e2e_sorted[min(len(e2e_sorted) - 1, int(len(e2e_sorted) * 0.95))]
    return HarnessResult(
        iterations=iterations,
        e2e_p50_ms=round(p50, 3),
        e2e_p95_ms=round(p95, 3),
        per_stage=ledger.summary(),
    )
