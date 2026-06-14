"""Unit tests for the embeddings tier (quorum.pipeline.retrieval).

Uses a deterministic STUB embedder (no sentence-transformers / torch needed) so
the cache + reference logic is verifiable in CI. The real LocalEmbedder is only
exercised by the live probe.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path
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


# --- startup warming: index_references must be idempotent ------------------- #
async def test_index_references_is_idempotent() -> None:
    # The startup warm and the lazy first-utterance fallback can both call this;
    # without the idempotent guard a second build would APPEND the bank twice.
    r = SemanticRetrieval(StubEmbedder(), top_k=2)
    items = [("snowman", _spec("snowman")), ("rocket", _spec("rocket"))]
    r.index_references(items)
    r.index_references(items)  # second call must be a no-op, not a re-append
    assert len(r._ref_specs) == 2  # the invariant: built once, not appended twice
    refs = await r.references("a snowman")
    assert len(refs) == 1  # snowman once, not duplicated


def test_index_references_empty_still_marks_indexed() -> None:
    r = SemanticRetrieval(StubEmbedder())
    r.index_references([])
    assert r.indexed  # so the lazy fallback won't keep retrying an empty bank


# --- cache persistence ----------------------------------------------------- #
async def test_cache_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    r1 = SemanticRetrieval(StubEmbedder(), cache_threshold=0.94, model_id="stub", cache_path=path)
    await r1.remember("a snowman", _spec("snowman"))
    await r1.flush()  # the write is backgrounded — wait for it
    assert path.exists()  # remember() persisted it

    # A fresh process (new instance) restores the cache from disk.
    r2 = SemanticRetrieval(StubEmbedder(), cache_threshold=0.94, model_id="stub", cache_path=path)
    assert r2.load_cache() == 1
    hit = await r2.cached("draw a snowman")  # cosine 0.99 with "a snowman"
    assert hit is not None and hit.name == "snowman"


async def test_cache_no_path_does_not_persist(tmp_path: Path) -> None:
    # Default (cache_path=None) keeps the in-memory-only behavior — no file ever.
    r = SemanticRetrieval(StubEmbedder(), model_id="stub")
    await r.remember("a snowman", _spec("snowman"))
    assert os.listdir(tmp_path) == []  # os, not pathlib, to satisfy ASYNC240


async def test_cache_load_rejects_foreign_model(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    r1 = SemanticRetrieval(StubEmbedder(), model_id="model-a", cache_path=path)
    await r1.remember("a snowman", _spec("snowman"))
    await r1.flush()
    # A cache written by a different embedding model is meaningless cosine-wise.
    r2 = SemanticRetrieval(StubEmbedder(), model_id="model-b", cache_path=path)
    assert r2.load_cache() == 0
    assert await r2.cached("draw a snowman") is None


def test_cache_load_missing_file_is_empty(tmp_path: Path) -> None:
    r = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=tmp_path / "nope.json")
    assert r.load_cache() == 0


async def test_cache_load_corrupt_file_is_empty_and_still_works(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("{not valid json", encoding="utf-8")
    r = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r.load_cache() == 0  # degrades, doesn't raise
    # ...and the instance is still fully functional after a bad load.
    await r.remember("a snowman", _spec("snowman"))
    assert await r.cached("draw a snowman") is not None
    await r.flush()


def test_cache_load_skips_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "version": 999,
                "model": "stub",
                "vectors": [[1.0, 0.0, 0.0, 0.0]],
                "specs": [_spec("snowman").model_dump_json()],
            }
        ),
        encoding="utf-8",
    )
    r = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r.load_cache() == 0


def test_cache_load_skips_length_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "model": "stub",
                "vectors": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
                "specs": [_spec("snowman").model_dump_json()],  # 1 spec vs 2 vectors
            }
        ),
        encoding="utf-8",
    )
    r = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r.load_cache() == 0


async def test_cache_persist_survives_multiple_remembers(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    r1 = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    await r1.remember("a snowman", _spec("snowman"))
    await r1.remember("a rocket", _spec("rocket"))
    await r1.flush()
    r2 = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r2.load_cache() == 2
    assert (await r2.cached("a rocket")) is not None
    assert (await r2.cached("a snowman")) is not None


# --- load_cache must never raise on a bad/tampered file (review fixes) ------- #
@pytest.mark.parametrize("body", ["null", "[1, 2, 3]", "42", '"a string"'])
def test_cache_load_skips_non_object_json(tmp_path: Path, body: str) -> None:
    # Valid JSON that isn't our {version, model, ...} object must degrade, not
    # raise AttributeError on raw.get(...).
    path = tmp_path / "cache.json"
    path.write_text(body, encoding="utf-8")
    r = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r.load_cache() == 0


def test_cache_load_skips_malformed_vectors(tmp_path: Path) -> None:
    # Non-numeric vector elements make np.asarray raise TypeError, not ValueError.
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "model": "stub",
                "vectors": [{"not": "a number"}],
                "specs": [_spec("snowman").model_dump_json()],
            }
        ),
        encoding="utf-8",
    )
    r = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r.load_cache() == 0  # honored "never raises" contract


def test_cache_load_skips_wrong_rank_vectors(tmp_path: Path) -> None:
    # A flat (1-D) vectors array would later make query() raise IndexError; reject
    # it at load instead so a tampered file can't crash a request.
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "model": "stub",
                "vectors": [1.0, 0.0, 0.0, 0.0],  # flat, not a list-of-vectors
                "specs": [_spec("snowman").model_dump_json()],
            }
        ),
        encoding="utf-8",
    )
    r = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r.load_cache() == 0


async def test_concurrent_remembers_all_persist(tmp_path: Path) -> None:
    # Two novel CREATEs fired together (the shared process-wide singleton case):
    # the persist lock must serialize the writes so BOTH survive a restart — the
    # pre-fix shared-.tmp race could let an older 1-entry snapshot win.
    path = tmp_path / "cache.json"
    r1 = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    await asyncio.gather(
        r1.remember("a snowman", _spec("snowman")),
        r1.remember("a rocket", _spec("rocket")),
    )
    await r1.flush()
    r2 = SemanticRetrieval(StubEmbedder(), model_id="stub", cache_path=path)
    assert r2.load_cache() == 2
