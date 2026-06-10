"""Observability — structured logging and per-stage latency timing.

Per-stage latency is a product requirement (plan.md §5, RULES.md §6), not a
nice-to-have. Every pipeline stage times itself via :func:`stage_timer`; the
:class:`LatencyLedger` aggregates p50/p95 so the benchmark harness and the
``/metrics``-style endpoints report real numbers, never estimates.
"""

from quorum.observability.latency import (
    LatencyLedger,
    StageTiming,
    get_ledger,
    stage_timer,
)
from quorum.observability.logging import configure_logging, get_logger

__all__ = [
    "LatencyLedger",
    "StageTiming",
    "configure_logging",
    "get_ledger",
    "get_logger",
    "stage_timer",
]
