"""Pipeline stages — each a swappable module behind a Protocol.

Stage order (plan.md §3.3):
  1. VAD / endpointing   (interfaces.VAD)         — Phase 1
  2. STT                 (interfaces.Transcriber) — Phase 1
  3. Classify cascade    (interfaces.Classifier)  — Phase 1 (rules) -> Phase 4
  4. Design State Engine (quorum.engine)          — Phase 2
  5. Renderer            (interfaces.Renderer)    — Phase 0  <-- here
  6. Broadcast           (quorum.gateway)         — Phase 0

A stage never imports another stage's implementation; it depends only on the
Protocols in ``interfaces`` and the domain contracts. That is what keeps stages
independently testable and swappable (RULES.md §2/§5).
"""

from quorum.pipeline.interfaces import VAD, Classifier, Renderer, Transcriber
from quorum.pipeline.renderer import SvgRenderer, get_renderer

__all__ = [
    "VAD",
    "Classifier",
    "Renderer",
    "SvgRenderer",
    "Transcriber",
    "get_renderer",
]
