"""Utterance → machine-checkable :class:`~quorum.eval.adherence.Expectation`.

The offline D4 harness (``scripts/eval_adherence.py``) uses hand-annotated
expectations; the LIVE render→critique→repair pass (``pipeline/llm.py``, gated
by ``QUORUM_LLM_CRITIQUE``) has only the utterance, so this module derives a
conservative Expectation from the words themselves. Conservative on purpose:
every extractor only fires on unambiguous surface forms — a missed expectation
merely skips a dimension (adherence scores the dimensions that APPLY), while a
wrong one would trigger repairs the model can never satisfy.

Pure text → data, no I/O, no model — same "code measures" stance as the scorer.
"""

from __future__ import annotations

import re

from quorum.eval.adherence import NAMED_COLORS, Expectation, Relation
from quorum.pipeline.intent import has_3d_intent

# Number words worth counting. "one"/"a" are skipped — a single instance is the
# default reading and scoring it adds noise, not signal.
_NUMBER_WORDS: dict[str, int] = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

_COUNT_RE = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS) + r"|\d+)\s+([a-z][a-z-]*)\b",
)

# Nouns that follow a number without naming a countable part ("three
# dimensional", "two more") — never count these.
_COUNT_STOP = frozenset(
    {"d", "dimensional", "dimensions", "more", "times", "of", "or", "other"}
) | frozenset(NAMED_COLORS)

_COLOR_RE = re.compile(r"\b(" + "|".join(NAMED_COLORS) + r")\b")

# Explicit fill-the-body phrasing only; a bare color name colors SOMETHING but
# does not promise a solid fill.
_COLORED_IN_RE = re.compile(r"\b(?:colou?red|filled?)\s+in\b")

# Spatial predicate words → the Relation.kind vocabulary adherence verifies.
_REL_WORDS: dict[str, str] = {
    "inside": "inside",
    "within": "inside",
    "above": "above",
    "over": "above",
    "below": "below",
    "under": "below",
    "beneath": "below",
    "beside": "beside",
}

# Tokens that can't be the subject/object of a spatial relation (articles,
# colors, common adjectives) — skipped when resolving "X inside Y".
_REL_STOP = frozenset(
    {
        "a", "an", "the", "of", "it", "its", "is", "and", "with", "in",
        "big", "small", "little", "large", "tiny", "simple", "basic",
        "new", "second", "first", "one",
    }
) | frozenset(NAMED_COLORS)

_TOKEN_RE = re.compile(r"[a-z0-9-]+")


def _singular(word: str) -> str:
    """Naive singularization for part-role matching ("pistons" → "piston")."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("xes", "ses", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _extract_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for num, noun in _COUNT_RE.findall(text):
        n = _NUMBER_WORDS.get(num) or (int(num) if num.isdigit() else 0)
        role = _singular(noun)
        if n < 2 or role in _COUNT_STOP or len(role) < 3:
            continue
        counts[role] = n
    return counts


def _extract_relations(tokens: list[str]) -> tuple[Relation, ...]:
    relations: list[Relation] = []
    for i, tok in enumerate(tokens):
        kind = _REL_WORDS.get(tok)
        if kind is None:
            continue
        inner = next(
            (t for t in reversed(tokens[:i]) if t not in _REL_STOP), None
        )
        outer = next((t for t in tokens[i + 1 :] if t not in _REL_STOP), None)
        if inner and outer and inner != outer:
            relations.append(Relation(kind, _singular(inner), _singular(outer)))
    return tuple(relations)


def parse_expectation(text: str) -> Expectation:
    """Derive a conservative Expectation from one utterance (see module doc)."""
    t = text.lower()
    tokens = _TOKEN_RE.findall(t)
    colors = tuple(dict.fromkeys(_COLOR_RE.findall(t)))  # ordered, de-duped
    return Expectation(
        counts=_extract_counts(t),
        colors=colors,
        colored_in=bool(_COLORED_IN_RE.search(t)),
        relations=_extract_relations(tokens),
        expect_3d=has_3d_intent(text),
    )
