"""Latency benchmark — a first-class test (RULES.md §3/§6), not optional.

Phase 0 has no STT/LLM, so this measures the fast-path tail (classify + engine +
render). Budget for the fast path is generous (plan.md §5: classify fast path
0.05-0.2 s, render <0.5 s); we assert it stays comfortably under 50 ms p95 here,
which leaves the whole STT/LLM budget free. The numbers print so they can be
copied into the context.md ledger.
"""

from __future__ import annotations

import pytest

from quorum.observability.harness import run_loop_benchmark

# Fast-path budget for the (no-STT/LLM) Phase-0 loop. This is the classify+
# engine+render slice only; the end-to-end <5 s budget includes STT/LLM later.
FAST_PATH_P95_BUDGET_MS = 50.0


@pytest.mark.latency
async def test_fast_path_within_budget(capsys: pytest.CaptureFixture[str]) -> None:
    result = await run_loop_benchmark(iterations=200)
    with capsys.disabled():
        print("\n--- latency harness (Phase 0 fast path) ---")
        print(f"iterations: {result.iterations}")
        print(f"end-to-end  p50={result.e2e_p50_ms} ms  p95={result.e2e_p95_ms} ms")
        for stage, s in sorted(result.per_stage.items()):
            p50, p95, n = s["p50_ms"], s["p95_ms"], int(s["count"])
            print(f"  {stage:10s} p50={p50:.3f} ms  p95={p95:.3f} ms  n={n}")

    assert result.e2e_p95_ms < FAST_PATH_P95_BUDGET_MS, (
        f"fast-path p95 {result.e2e_p95_ms}ms exceeds budget {FAST_PATH_P95_BUDGET_MS}ms"
    )
    # the render and engine stages must each be well under their own budgets
    assert "engine" in result.per_stage
    assert result.per_stage["engine"]["p95_ms"] < 20.0
