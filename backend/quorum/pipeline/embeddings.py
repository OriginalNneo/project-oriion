"""Text embedding behind a small Protocol (the cascade's embeddings tier).

The embedder turns an utterance into an L2-normalized vector so the retrieval
layer (:mod:`quorum.pipeline.retrieval`) can do semantic few-shot lookup and a
near-duplicate result cache. Kept behind a Protocol + config factory like every
other swappable stage (RULES.md §5): default is OFF (no embedder, no heavy dep),
and the local sentence-transformers backend is imported lazily only when chosen
via ``QUORUM_RETRIEVAL_BACKEND=local`` (needs the ``embeddings`` extra).

``embed`` is synchronous CPU work — async callers must wrap it in
``asyncio.to_thread`` so the event loop never blocks (RULES.md §5).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from quorum.config.settings import Backend, Settings


@runtime_checkable
class Embedder(Protocol):
    """Maps texts to a row-per-text matrix of L2-normalized float32 vectors."""

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class LocalEmbedder:
    """sentence-transformers backed embedder. The model (and the heavy import)
    load lazily on first use so process startup and `mock` runs pay nothing."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: object | None = None
        self._dim = 0

    def _ensure(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self._model_name)
            self._model = model
            # method renamed across sentence-transformers versions
            get_dim = getattr(model, "get_embedding_dimension", None) or (
                model.get_sentence_embedding_dimension
            )
            self._dim = int(get_dim())

    @property
    def dim(self) -> int:
        self._ensure()
        return self._dim

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self._ensure()
        assert self._model is not None  # set by _ensure
        vecs = self._model.encode(  # type: ignore[attr-defined]
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return np.asarray(vecs, dtype=np.float32).reshape(len(texts), -1)


def build_embedder(settings: Settings) -> Embedder | None:
    """Return the configured embedder, or None when retrieval is off (MOCK)."""
    if settings.retrieval_backend is Backend.LOCAL:
        return LocalEmbedder(settings.embedding_model)
    return None
