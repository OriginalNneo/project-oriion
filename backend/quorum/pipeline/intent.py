"""Shared intent-detection utilities used by both classify.py and llm.py.

Kept in its own module so neither imports the other (classify.py imports llm.py
already; llm.py cannot import classify.py without a cycle).
"""
import re

# 3-D intent tokens. A dedicated pattern is more robust than the len > 2 filter
# in _unexplained_words() which misses "3d". Covers spoken forms: "3d", "3-d",
# "isometric", "iso", "three dimensional".
_3D_INTENT_RE = re.compile(
    r"\b(3[-\s]?d|isometric|iso|three[\s-]dimensional)\b",
    re.IGNORECASE,
)


def has_3d_intent(text: str) -> bool:
    """Return True when the utterance signals 3-D / isometric intent."""
    return bool(_3D_INTENT_RE.search(text))


# Volumetric-by-name solids: a spoken "sphere"/"hemisphere"/"orb" IS a 3D body
# even without a "3d"/"isometric" marker. Kept separate from _3D_INTENT_RE
# because the rules stage must NOT treat these as extrusion triggers ("add a
# sphere to it" would wrongly extrude the focus) — only the LLM stage's
# reference-suppression and tier-routing use the wider signal.
_VOLUMETRIC_RE = re.compile(r"\b(spheres?|hemispheres?|orbs?)\b", re.IGNORECASE)


def has_volumetric_intent(text: str) -> bool:
    """3-D intent OR a solid named outright (sphere/hemisphere/orb).

    Used by the LLM stage to (a) suppress flat reference sketches that would
    fight a solids answer — the 'sphere' template is a flat circle+equator —
    and (b) route to the escalation tier when one is configured.
    """
    return has_3d_intent(text) or bool(_VOLUMETRIC_RE.search(text))
