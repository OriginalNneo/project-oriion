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
templates) a numpy matmul beats standing up an external vector DB. State is
per-process (rebuilt from the template bank on startup; the cache starts empty).
"""

from __future__ import annotations

import asyncio
import re
from functools import lru_cache

import numpy as np

from quorum.domain.geometry import GeometrySpec
from quorum.pipeline.embeddings import Embedder

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
    ) -> None:
        self._emb = embedder
        self._top_k = top_k
        self._cache_threshold = cache_threshold
        self._ref_index = _Index()
        self._ref_specs: list[GeometrySpec] = []
        self._ref_names: list[str] = []
        self._cache_index = _Index()
        self._cache_specs: list[GeometrySpec] = []
        self._indexed = False

    # -- references -------------------------------------------------------- #
    def index_references(self, items: list[tuple[str, GeometrySpec]]) -> None:
        """Embed and store known-good (name, geometry) pairs (the template bank).
        Idempotent-ish: call once at warm-up. Synchronous (heavy) — call via a
        thread from async paths."""
        if not items:
            self._indexed = True
            return
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
        """Store a CREATE's geometry keyed by its utterance for later reuse."""
        vec = await asyncio.to_thread(self._embed_one, text)
        self._cache_index.add(vec)
        self._cache_specs.append(spec)

    # -- internal ---------------------------------------------------------- #
    def _embed_one(self, text: str) -> np.ndarray:
        return np.asarray(self._emb.embed([text])[0], dtype=np.float32)


@lru_cache(maxsize=1)
def _shared(
    backend_value: str, model: str, top_k: int, threshold: float
) -> SemanticRetrieval | None:
    from quorum.config.settings import Backend
    from quorum.pipeline.embeddings import LocalEmbedder

    if backend_value != Backend.LOCAL.value:
        return None
    return SemanticRetrieval(LocalEmbedder(model), top_k=top_k, cache_threshold=threshold)


def get_retrieval(settings: object) -> SemanticRetrieval | None:
    """The PROCESS-WIDE retrieval tier (one embedder + reference index + cache
    shared across all rooms), or None when retrieval is off. `build_classifier`
    runs per room — without this singleton each room would reload the model and
    re-embed the whole template bank."""
    backend = getattr(settings, "retrieval_backend", None)
    backend_value = backend.value if backend is not None else "mock"
    return _shared(
        backend_value,
        str(getattr(settings, "embedding_model", "all-MiniLM-L6-v2")),
        int(getattr(settings, "retrieval_top_k", 2)),
        float(getattr(settings, "retrieval_cache_threshold", 0.94)),
    )
