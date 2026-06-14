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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first read)."""
    return Settings()
