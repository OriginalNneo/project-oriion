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

    # --- Local model selection (only consulted when a backend is LOCAL) ---
    whisper_model: str = "small"
    ollama_model: str = "llama3.2:3b"

    # --- Cloud creds (only required when a backend is GROQ) ---
    groq_api_key: str | None = None

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first read)."""
    return Settings()
