"""Evaluation tooling for the drawing pipeline.

Pure, deterministic scorers used by the offline eval scripts (``scripts/
eval_adherence.py``) — separate from the live pipeline so measuring never
touches serving. See :mod:`quorum.eval.adherence` (plan.md §11 D4).
"""
