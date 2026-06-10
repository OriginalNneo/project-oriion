"""Quorum — voice-driven collaborative design tool.

A modular monolith: an async FastAPI gateway in front of a pipeline of swappable
stages (VAD -> STT -> classify -> design-state-engine -> render -> broadcast).
Each stage sits behind a Protocol so backends are a config change, not a rewrite.
"""

__version__ = "0.1.0"
