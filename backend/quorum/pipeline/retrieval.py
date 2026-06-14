"""Semantic retrieval — the embeddings tier between rules/templates and the LLM.

Two jobs, both backed by one :class:`~quorum.pipeline.embeddings.Embedder`:

1. **Semantic few-shot references** — embed the utterance, return the closest
   known-good drawings (the template bank + remembered CREATEs) as references
   for the LLM. Better than keyword match: "a frosty figure" still finds the
   snowman. ALWAYS safe — it only changes which examples the model sees.

2. **Near-duplicate result cache** — remember each CREATE (utterance → geometry);
   when a later utterance is near-identical (cosine ≥ threshold) AND looks like a
   fresh create (no modify/extend markers), reuse the stored geometry and skip
   the LLM entirely. Reuse is always a CREATE, so it is NON-DESTRUCTIVE (it adds
   a node, never overwrites one) — the safety floor for caching context.

In-memory cosine over a normalized-vector matrix — at this scale (hundreds of
templates) a numpy matmul beats standing up an external vector DB. The reference
index is rebuilt from the (deterministic) template bank — warmed once at startup
(see ``app.py`` lifespan). The CREATE cache is the only learned state, so it is
the part worth persisting to disk (``retrieval_cache_path``) so a restart keeps
the drawings the room has already produced.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from quorum.domain.geometry import GeometrySpec
from quorum.observability import get_logger
from quorum.pipeline.embeddings import Embedder

_log = get_logger("pipeline.retrieval")

# Bump when the on-disk cache layout changes so stale files are ignored, never
# mis-parsed.
_CACHE_FORMAT_VERSION = 1

# Utterances with any of these markers are context-dependent (modify/extend the
# current scene), so a cached CREATE must NOT be reused for them.
_MODIFY_MARKER_RE = re.compile(
    r"\b(?:it|this|that|them|its|bigger|smaller|make|change|turn|recolou?r|"
    r"shade|add|remove|delete|put|move|give|attach|inside|above|below|"
    r"next to|beside|on top|behind|undo|connect)\b"
)

# A reference must clear this cosine to be worth injecting (below it the nearest
# template is unrelated noise).
_REF_MIN_SIM = 0.30


def is_create_like(text: str) -> bool:
    """True when the utterance reads as a fresh standalone create (no markers of
    modifying/extending an existing scene) — the only safe case to reuse a cache."""
    return _MODIFY_MARKER_RE.search(text.lower()) is None


class _Index:
    """Append-only store of L2-normalized vectors with a cosine top-k query."""

    def __init__(self) -> None:
        self._mat: np.ndarray | None = None

    def __len__(self) -> int:
        return 0 if self._mat is None else int(self._mat.shape[0])

    def add(self, vec: np.ndarray) -> None:
        row = vec.astype(np.float32).reshape(1, -1)
        self._mat = row if self._mat is None else np.vstack([self._mat, row])

    @property
    def matrix(self) -> np.ndarray | None:
        """The raw row-per-vector matrix (None when empty) — for serialization."""
        return self._mat

    def load_matrix(self, mat: np.ndarray) -> None:
        """Replace the whole store from a deserialized matrix (cache restore)."""
        self._mat = mat.astype(np.float32) if mat.size else None

    def query(self, vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._mat is None:
            return []
        sims = self._mat @ vec.astype(np.float32)  # cosine: rows + query normalized
        k = min(k, sims.shape[0])
        top = np.argsort(-sims)[:k]
        return [(int(i), float(sims[i])) for i in top]


class SemanticRetrieval:
    """Embeddings-tier references + a near-duplicate CREATE cache."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        top_k: int = 2,
        cache_threshold: float = 0.94,
        model_id: str = "unknown",
        cache_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._emb = embedder
        self._top_k = top_k
        self._cache_threshold = cache_threshold
        # Identifies the embedding space the cached vectors live in. A cache file
        # written by a different model is meaningless (cosine across spaces is
        # noise), so load_cache() refuses to restore one whose model_id differs.
        self._model_id = model_id
        self._cache_path = Path(cache_path) if cache_path is not None else None
        self._ref_index = _Index()
        self._ref_specs: list[GeometrySpec] = []
        self._ref_names: list[str] = []
        self._cache_index = _Index()
        self._cache_specs: list[GeometrySpec] = []
        self._indexed = False
        # Serializes index_references so the startup warm and the lazy
        # first-utterance fallback can't both build the index (which appends, so a
        # concurrent double-build would DOUBLE every reference).
        self._index_lock = threading.Lock()
        # Serializes cache writes (this is a process-wide singleton shared across
        # rooms, so concurrent remembers can race the same file). Acquired in
        # creation order, so the newest snapshot always lands last.
        self._persist_lock = asyncio.Lock()
        self._persist_tasks: set[asyncio.Task[None]] = set()

    # -- references -------------------------------------------------------- #
    def index_references(self, items: list[tuple[str, GeometrySpec]]) -> None:
        """Embed and store known-good (name, geometry) pairs (the template bank).
        Idempotent AND thread-safe: the first caller builds the index, every later
        (or concurrent) caller is a no-op. Synchronous (heavy) — call via a thread
        from async paths. The lock lets the startup warm and the lazy
        first-utterance fallback race harmlessly (without it a concurrent
        double-build would append the whole bank twice)."""
        with self._index_lock:
            if self._indexed:
                return
            if items:
                vecs = self._emb.embed([name for name, _ in items])
                for i, (name, spec) in enumerate(items):
                    self._ref_index.add(vecs[i])
                    self._ref_names.append(name)
                    self._ref_specs.append(spec)
            self._indexed = True

    @property
    def indexed(self) -> bool:
        return self._indexed

    async def references(self, text: str) -> list[tuple[str, GeometrySpec]]:
        """Top-k known-good (name, geometry) pairs nearest to *text*."""
        if len(self._ref_index) == 0:
            return []
        vec = await asyncio.to_thread(self._embed_one, text)
        return [
            (self._ref_names[i], self._ref_specs[i])
            for i, sim in self._ref_index.query(vec, self._top_k)
            if sim >= _REF_MIN_SIM
        ]

    # -- cache ------------------------------------------------------------- #
    async def cached(self, text: str) -> GeometrySpec | None:
        """Return a remembered CREATE geometry when *text* is a near-duplicate of
        a prior create-like utterance; else None."""
        if len(self._cache_index) == 0 or not is_create_like(text):
            return None
        vec = await asyncio.to_thread(self._embed_one, text)
        hits = self._cache_index.query(vec, 1)
        if hits and hits[0][1] >= self._cache_threshold:
            return self._cache_specs[hits[0][0]]
        return None

    async def remember(self, text: str, spec: GeometrySpec) -> None:
        """Store a CREATE's geometry keyed by its utterance for later reuse, and
        persist the cache when a path is configured (so a restart keeps it)."""
        vec = await asyncio.to_thread(self._embed_one, text)
        # Mutate on the event loop (no await between these two lines), so a
        # concurrent cached()/remember() never sees a half-updated cache.
        self._cache_index.add(vec)
        self._cache_specs.append(spec)
        if self._cache_path is not None:
            # Snapshot synchronously (consistent + ordered on the event loop),
            # then persist in the BACKGROUND so the disk write never delays the
            # classify return. Track the task so it isn't GC'd mid-write.
            payload = self._serialize_cache()
            task = asyncio.create_task(self._persist(payload))
            self._persist_tasks.add(task)
            task.add_done_callback(self._persist_tasks.discard)

    async def flush(self) -> None:
        """Await any in-flight cache writes — for tests and graceful shutdown."""
        if self._persist_tasks:
            await asyncio.gather(*tuple(self._persist_tasks), return_exceptions=True)

    # -- persistence ------------------------------------------------------- #
    async def _persist(self, payload: dict[str, object]) -> None:
        """Serialize the actual file write so concurrent remembers can't clobber
        each other's `.tmp` — the lock is FIFO, so the newest snapshot lands last."""
        async with self._persist_lock:
            await asyncio.to_thread(self._write_cache_file, payload)

    def _serialize_cache(self) -> dict[str, object]:
        """A JSON-able snapshot of the current cache (taken on the event loop)."""
        mat = self._cache_index.matrix
        vecs = mat.tolist() if mat is not None else []
        return {
            "version": _CACHE_FORMAT_VERSION,
            "model": self._model_id,
            "vectors": vecs,
            "specs": [spec.model_dump_json() for spec in self._cache_specs],
        }

    def _write_cache_file(self, payload: dict[str, object]) -> None:
        """Atomically write the snapshot (tmp + os.replace) so a crash mid-write
        can't leave a truncated file. Never raises into the caller — a failed
        persist must not break the live drawing loop."""
        assert self._cache_path is not None
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, self._cache_path)
        except OSError as exc:  # disk full, perms, etc. — log and carry on
            _log.warning("retrieval_cache_write_failed", error=str(exc))

    def load_cache(self) -> int:
        """Restore the CREATE cache from disk when ``cache_path`` exists and was
        written by the SAME embedding model. Returns the number of entries
        loaded (0 on a missing/corrupt/mismatched/foreign file). Never raises —
        a bad cache file must degrade to an empty cache, not crash startup."""
        if self._cache_path is None or not self._cache_path.exists():
            return 0
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):  # valid JSON but not our object (null/list/…)
                _log.warning("retrieval_cache_not_an_object", path=str(self._cache_path))
                return 0
            if raw.get("version") != _CACHE_FORMAT_VERSION:
                _log.info("retrieval_cache_skipped_version", path=str(self._cache_path))
                return 0
            if raw.get("model") != self._model_id:
                # Vectors from another embedding space would corrupt every query.
                _log.info(
                    "retrieval_cache_skipped_model",
                    want=self._model_id,
                    got=raw.get("model"),
                )
                return 0
            vectors = raw.get("vectors") or []
            specs_json = raw.get("specs") or []
            if len(vectors) != len(specs_json):
                _log.warning("retrieval_cache_length_mismatch", path=str(self._cache_path))
                return 0
            if not vectors:
                return 0
            mat = np.asarray(vectors, dtype=np.float32)
            if mat.ndim != 2 or mat.shape[0] != len(specs_json):  # tampered/ragged file
                _log.warning("retrieval_cache_bad_shape", path=str(self._cache_path))
                return 0
            self._cache_index.load_matrix(mat)
            self._cache_specs = [GeometrySpec.model_validate_json(s) for s in specs_json]
            _log.info("retrieval_cache_loaded", entries=len(self._cache_specs))
            return len(self._cache_specs)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
            # A bad/tampered cache file must degrade to an empty cache, never crash
            # startup — so we catch anything a malformed payload could throw.
            _log.warning("retrieval_cache_load_failed", error=str(exc))
            return 0

    # -- internal ---------------------------------------------------------- #
    def _embed_one(self, text: str) -> np.ndarray:
        return np.asarray(self._emb.embed([text])[0], dtype=np.float32)


@lru_cache(maxsize=1)
def _shared(
    backend_value: str, model: str, top_k: int, threshold: float, cache_path: str | None
) -> SemanticRetrieval | None:
    from quorum.config.settings import Backend
    from quorum.pipeline.embeddings import LocalEmbedder

    if backend_value != Backend.LOCAL.value:
        return None
    retrieval = SemanticRetrieval(
        LocalEmbedder(model),
        top_k=top_k,
        cache_threshold=threshold,
        model_id=model,
        cache_path=cache_path,
    )
    retrieval.load_cache()  # restore a prior session's CREATEs (no-op if no file)
    return retrieval


def get_retrieval(settings: object) -> SemanticRetrieval | None:
    """The PROCESS-WIDE retrieval tier (one embedder + reference index + cache
    shared across all rooms), or None when retrieval is off. `build_classifier`
    runs per room — without this singleton each room would reload the model and
    re-embed the whole template bank."""
    backend = getattr(settings, "retrieval_backend", None)
    backend_value = backend.value if backend is not None else "mock"
    cache_path = getattr(settings, "retrieval_cache_path", None)
    return _shared(
        backend_value,
        str(getattr(settings, "embedding_model", "all-MiniLM-L6-v2")),
        int(getattr(settings, "retrieval_top_k", 2)),
        float(getattr(settings, "retrieval_cache_threshold", 0.94)),
        str(cache_path) if cache_path else None,
    )
