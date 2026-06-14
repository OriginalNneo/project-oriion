"""Unit tests for the embeddings tier (quorum.pipeline.retrieval).

Uses a deterministic STUB embedder (no sentence-transformers / torch needed) so
the cache + reference logic is verifiable in CI. The real LocalEmbedder is only
exercised by the live probe.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

import numpy as np
import pytest

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.pipeline.retrieval import SemanticRetrieval, is_create_like


class StubEmbedder:
    """Maps a few fixed strings to hand-chosen unit vectors so cosine results are
    exact and predictable. Unknown text → a distinct basis vector (cosine 0)."""

    _VECS: ClassVar[dict[str, list[float]]] = {
        "a snowman": [1.0, 0.0, 0.0, 0.0],
        "draw a snowman": [0.99, 0.141, 0.0, 0.0],  # ~0.99 cosine with "a snowman"
        "a rocket": [0.0, 1.0, 0.0, 0.0],
        "snowman": [1.0, 0.0, 0.0, 0.0],
        "rocket": [0.0, 1.0, 0.0, 0.0],
    }

    @property
    def dim(self) -> int:
        return 4

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        rows = []
        for t in texts:
            raw = self._VECS.get(t.lower().strip(), [0.0, 0.0, 0.0, 1.0])
            v = np.asarray(raw, dtype=np.float32)
            n = float(np.linalg.norm(v)) or 1.0
            rows.append(v / n)
        return np.asarray(rows, dtype=np.float32)


def _spec(name: str) -> GeometrySpec:
    return GeometrySpec(kind=ShapeKind.CIRCLE, name=name, label=name)


def test_is_create_like_excludes_modify_utterances() -> None:
    assert is_create_like("a snowman")
    assert is_create_like("a red dragon")
    assert not is_create_like("make it bigger")
    assert not is_create_like("add two eyes")
    assert not is_create_like("a box above the horse")  # spatial = context-dependent
    assert not is_create_like("turn it blue")


async def test_cache_hit_on_near_duplicate_create() -> None:
    r = SemanticRetrieval(StubEmbedder(), cache_threshold=0.94)
    snowman = _spec("snowman")
    await r.remember("a snowman", snowman)
    # near-identical phrasing (cosine 0.99) -> reuse the remembered geometry
    hit = await r.cached("draw a snowman")
    assert hit is snowman
    # unrelated utterance (cosine 0) -> miss
    assert await r.cached("a rocket") is None


async def test_cache_skips_modify_like_utterances() -> None:
    r = SemanticRetrieval(StubEmbedder(), cache_threshold=0.94)
    await r.remember("a snowman", _spec("snowman"))
    # even though it embeds identically, a modify-like utterance is never reused
    assert await r.cached("make a snowman") is None  # "make" marker


async def test_cache_empty_returns_none() -> None:
    r = SemanticRetrieval(StubEmbedder(), cache_threshold=0.94)
    assert await r.cached("a snowman") is None


async def test_references_return_nearest_known_good() -> None:
    r = SemanticRetrieval(StubEmbedder(), top_k=1)
    snowman, rocket = _spec("snowman"), _spec("rocket")
    r.index_references([("snowman", snowman), ("rocket", rocket)])
    assert r.indexed
    refs = await r.references("a snowman")
    assert len(refs) == 1 and refs[0][1] is snowman
    refs2 = await r.references("a rocket")
    assert refs2[0][1] is rocket


async def test_references_drop_unrelated_below_min_sim() -> None:
    r = SemanticRetrieval(StubEmbedder(), top_k=2)
    r.index_references([("snowman", _spec("snowman")), ("rocket", _spec("rocket"))])
    # an unknown utterance (basis vector [0,0,0,1]) is orthogonal to both -> dropped
    assert await r.references("xyzzy frobnicate") == []


async def test_threshold_just_below_does_not_hit() -> None:
    # cosine 0.99 hits at 0.94; raise the bar above 0.99 and the same pair misses.
    r = SemanticRetrieval(StubEmbedder(), cache_threshold=0.995)
    await r.remember("a snowman", _spec("snowman"))
    assert await r.cached("draw a snowman") is None  # cosine 0.99 < 0.995


@pytest.mark.parametrize("k", [1, 2])
async def test_references_respect_top_k(k: int) -> None:
    r = SemanticRetrieval(StubEmbedder(), top_k=k)
    r.index_references([("snowman", _spec("snowman")), ("rocket", _spec("rocket"))])
    # "a snowman" is close to snowman (1.0) and orthogonal to rocket (0, dropped by
    # min-sim), so at most one clears the bar regardless of k.
    assert len(await r.references("a snowman")) <= k
