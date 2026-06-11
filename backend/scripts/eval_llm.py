"""Benchmark candidate Groq models for cascade stage C — measured, not argued.

For each model x eval utterance the REAL :class:`LLMClassifier` runs (same
prompt, same validation, same retry), so a model only scores when its JSON
survives the strict pydantic gate AND the geometry renders. Reported per
model: validity %, mean parts per scene (geometry richness), latency p50/p95.

Run (network; needs the Groq key in .env):

    uv run python scripts/eval_llm.py                       # default candidates
    uv run python scripts/eval_llm.py model-a model-b ...   # explicit list
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time

from quorum.config.settings import Backend, Settings
from quorum.domain.op import ClassifierContext, OpType
from quorum.pipeline.llm import LLMClassifier
from quorum.pipeline.renderer import SvgRenderer

# Verified against GET /openai/v1/models (kimi was decommissioned).
_DEFAULT_MODELS = [
    "llama-3.3-70b-versatile",                  # current choice
    "meta-llama/llama-4-scout-17b-16e-instruct",  # newer mid-tier
    "llama-3.1-8b-instant",                     # cheaper/faster tier
    "openai/gpt-oss-20b",                       # small reasoning model
]

# Free-tier Groq rate limits are tokens-per-minute PER MODEL and our system
# prompt is ~3.5k tokens, so calls must be paced or every result is a 429.
_PACE_S = 12.0
_RETRIES = 2
_RETRY_WAIT_S = 20.0

_UTTERANCES = [
    "a five-pointed star",
    "a snowman wearing a top hat",
    "a robot with an antenna and two wheels",
    "a funnel turned on its side with five thrusters attached",
    "a 3D pyramid next to a cylinder",
    "a basic smartphone, colored blue",
]

_CTX = ClassifierContext()


async def _eval_model(model: str, api_key: str) -> dict[str, object]:
    clf = LLMClassifier(backend=Backend.GROQ, model=model, api_key=api_key)
    renderer = SvgRenderer()
    latencies: list[float] = []
    parts: list[int] = []
    ok = 0
    for i, text in enumerate(_UTTERANCES):
        for attempt in range(_RETRIES + 1):
            t0 = time.perf_counter()
            op = await clf.classify(
                text, speaker_id="eval", utterance_id=f"e{i}", context=_CTX
            )
            dt = time.perf_counter() - t0
            if op.confidence > 0:
                break
            if attempt < _RETRIES:
                await asyncio.sleep(_RETRY_WAIT_S)  # rate-limit window reset
        valid = op.confidence > 0 and op.op_type is not OpType.NOOP and op.geometry is not None
        if valid and op.geometry is not None:
            try:
                renderer.render(op.geometry)
            except Exception:
                valid = False
        if valid and op.geometry is not None:
            ok += 1
            latencies.append(dt)
            parts.append(max(1, len(op.geometry.parts)))
        flag = "ok " if valid else "BAD"
        print(f"  {flag} [{dt:5.2f}s] {text!r}")
        await asyncio.sleep(_PACE_S)
    return {
        "model": model,
        "validity": f"{ok}/{len(_UTTERANCES)}",
        "parts_mean": round(statistics.mean(parts), 1) if parts else 0,
        "p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "p95_s": round(max(latencies), 2) if latencies else None,  # n small: max≈p95
    }


async def main(models: list[str]) -> int:
    api_key = Settings().require_groq_key()
    rows = []
    for model in models:
        print(f"\n=== {model}")
        rows.append(await _eval_model(model, api_key))
    print(f"\n{'model':<34} {'valid':>7} {'parts':>6} {'p50':>6} {'p95':>6}")
    for r in rows:
        print(f"{r['model']:<34} {r['validity']:>7} {r['parts_mean']:>6} "
              f"{r['p50_s']!s:>6} {r['p95_s']!s:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or _DEFAULT_MODELS)))
