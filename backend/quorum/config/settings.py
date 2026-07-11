"""12-factor configuration.

All knobs that vary between local/cloud or between deployments are read from the
environment with a ``QUORUM_`` prefix. Code never branches on a hardcoded
backend name; it asks Settings. This is what makes "swap local Whisper for Groq"
a config change rather than a rewrite (plan.md §2, RULES.md §5).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Backend(StrEnum):
    """Which implementation a swappable stage should use."""

    MOCK = "mock"
    LOCAL = "local"
    GROQ = "groq"
    OPENROUTER = "openrouter"


class Settings(BaseSettings):
    """Process-wide configuration. Constructed once via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="QUORUM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Pipeline stage backends (chosen by env, never hardcoded in a stage) ---
    stt_backend: Backend = Backend.MOCK
    llm_backend: Backend = Backend.MOCK
    vad_backend: Backend = Backend.MOCK

    # --- Latency knobs ---
    # The endpointing silence window is the single most impactful latency lever
    # (plan.md §5). Tunable without touching code.
    vad_silence_ms: int = Field(default=300, ge=50, le=2000)

    # LLM cascade escalation: rules results below this confidence go to the LLM
    # stage (when one is configured). Higher = fewer LLM calls = lower median
    # latency, at some accuracy cost (RULES.md §6 tuning lever #3).
    llm_escalation_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    llm_timeout_s: float = Field(default=8.0, gt=0, le=60)

    # Stage-C render→critique→repair pass: after a CREATE scene lands, score it
    # with the keyless adherence scorer and — when it falls below the threshold —
    # spend ONE extra LLM call feeding the concrete failure notes back to the
    # model, keeping whichever attempt scores higher. Default OFF so the default
    # behavior and latency are byte-identical; never touches the rules fast path.
    llm_critique: bool = False
    llm_critique_threshold: float = Field(default=0.8, ge=0.0, le=1.0)

    # Soft cap on parts per scene (isometric projection output, patch adds).
    # GeometrySpec carries a hard model ceiling of 120 (domain/geometry.py);
    # this knob tunes the working cap without touching the frozen model.
    max_scene_parts: int = Field(default=60, ge=1, le=120)

    # --- Local model selection (only consulted when a backend is LOCAL) ---
    whisper_model: str = "small"
    ollama_model: str = "llama3.2:3b"
    ollama_url: str = "http://localhost:11434"

    # --- Cloud creds (only required when a backend is GROQ) ---
    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-8b-instant"

    # --- Cloud creds (only required when a backend is OPENROUTER) ---
    openrouter_api_key: str | None = None
    # Picked by the D4 adherence bake-off (2026-06-14): fast (~2 s) AND strong on
    # color/placement/3D, where the cheapest 'ling' model was slow + weak.
    openrouter_model: str = "google/gemini-2.5-flash-lite"

    # --- Escalation tier (D4 part 2): a STRONGER model for intricate/3D prompts
    # only. Default None = disabled → every utterance uses the single fast tier
    # (byte-identical to today). When set, utterances flagged 3D/intricate route
    # to this backend+model while simple shapes stay on the fast tier — so an
    # "engine with pistons" gets a stronger model without slowing "a red circle".
    # Reuses the same groq/openrouter API keys (chosen by the escalation backend).
    llm_escalation_backend: Backend | None = None
    llm_escalation_model: str = ""

    # --- Semantic retrieval / embeddings tier (optional; needs the `embeddings`
    # extra). MOCK = off (keyword refs only, no cache — zero behavior change, no
    # heavy dep). LOCAL = sentence-transformers: semantic few-shot references +
    # an utterance->geometry cache that lets near-duplicate CREATEs skip the LLM.
    retrieval_backend: Backend = Backend.MOCK
    embedding_model: str = "all-MiniLM-L6-v2"
    retrieval_top_k: int = Field(default=2, ge=1, le=8)
    # Cosine ≥ this between two utterances ⇒ reuse the cached CREATE (skip the
    # LLM). High by design: only near-identical requests reuse a drawing.
    retrieval_cache_threshold: float = Field(default=0.94, ge=0.5, le=1.0)
    # Where to persist the near-duplicate CREATE cache so it survives a restart.
    # None = in-memory only (cache rebuilt empty each boot). The file is keyed by
    # embedding model, so a model change safely ignores a stale file.
    retrieval_cache_path: str | None = None

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = False

    def require_groq_key(self) -> str:
        """Return the Groq key or fail loudly — better than a silent 401 later."""
        if not self.groq_api_key:
            raise RuntimeError("QUORUM_GROQ_API_KEY is required when a backend is set to 'groq'.")
        return self.groq_api_key

    def require_openrouter_key(self) -> str:
        """Return the OpenRouter key or fail loudly — better than a silent 401 later."""
        if not self.openrouter_api_key:
            raise RuntimeError(
                "QUORUM_OPENROUTER_API_KEY is required when a backend is set to 'openrouter'."
            )
        return self.openrouter_api_key

    def require_key_for(self, backend: Backend) -> str | None:
        """Resolve the API key a cloud backend needs (None for LOCAL/MOCK).

        Used to wire the escalation tier without duplicating key fields — the
        escalation backend reuses whichever cloud key it corresponds to.
        """
        if backend is Backend.GROQ:
            return self.require_groq_key()
        if backend is Backend.OPENROUTER:
            return self.require_openrouter_key()
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first read)."""
    return Settings()
