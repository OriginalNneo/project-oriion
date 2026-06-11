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
