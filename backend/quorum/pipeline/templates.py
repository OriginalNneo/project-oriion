"""Template library — retrieval stage between rules and the LLM (stage B).

A small bank of canonical sketches (mined from the CC-BY Quick, Draw! dataset
by ``scripts/mine_templates.py`` into ``templates/quickdraw.json``), used two
ways:

1. **Direct hit** (:class:`TemplateClassifier`): a bare create-intent
   utterance that names exactly one known concept ("a snowman", "draw a
   tree") returns the template instantly — 0 ms instead of the ~1-2 s Groq
   round-trip. Anything richer (extra words, colors, scenes) declines with a
   zero-confidence NOOP so the cascade escalates to the LLM.

2. **Few-shot retrieval** (:func:`match`): the LLM stage injects up to two
   matched templates into its user message as ``reference_sketches`` — the
   model adapts a known-good drawing instead of inventing geometry.

Everything here is read-only and latency-trivial (one combined regex).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.observability import get_logger

_log = get_logger("pipeline.templates")

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Spoken-word aliases -> canonical template names (Quick, Draw! categories or
# the parametric isometric set). Longest spoken form wins at match time, so
# "3d cube" resolves before a bare "cube" could.
_SYNONYMS: dict[str, str] = {
    "phone": "cell phone",
    "smartphone": "cell phone",
    "mobile": "cell phone",
    "tv": "television",
    "automobile": "car",
    "bike": "bicycle",
    "motorcycle": "motorbike",
    "glasses": "eyeglasses",
    "spectacles": "eyeglasses",
    "boat": "sailboat",
    "sofa": "couch",
    "bulb": "light bulb",
    "plane": "airplane",
    "lorry": "truck",
    # parametric isometric set
    "3d cube": "cube",
    "isometric cube": "cube",
    "3d box": "cuboid",
    "box in 3d": "cuboid",
    "isometric box": "cuboid",
    "rectangular prism": "cuboid",
    "3d pyramid": "pyramid",
    "3d sphere": "sphere",
    "ball": "sphere",
    "cog": "gear",
    "cogwheel": "gear",
    "gear wheel": "gear",
    "3d stairs": "staircase",
    "isometric stairs": "staircase",
}

# Words that may surround a bare create-intent without changing it.
_FILLER = frozenset(
    "please draw sketch make create a an the me us we i want lets let's "
    "okay ok now how about maybe just simple basic quick 3d isometric iso "
    "in view".split()
)


@lru_cache(maxsize=1)
def _library() -> dict[str, GeometrySpec]:
    """All templates, merged across every JSON bank in the templates dir."""
    lib: dict[str, GeometrySpec] = {}
    for file in sorted(_TEMPLATES_DIR.glob("*.json")):
        raw = json.loads(file.read_text())
        for name, spec in raw["templates"].items():
            lib[name] = GeometrySpec.model_validate(spec)
    if not lib:
        _log.warning("templates_missing", path=str(_TEMPLATES_DIR))
    return lib


@lru_cache(maxsize=1)
def _index() -> list[tuple[re.Pattern[str], str]]:
    """(compiled word pattern, canonical name), longest spoken form first."""
    lib = _library()
    entries: list[tuple[str, str]] = [(name, name) for name in lib]
    entries += [(syn, name) for syn, name in _SYNONYMS.items() if name in lib]
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return [(re.compile(rf"\b{re.escape(word)}s?\b"), name) for word, name in entries]


def match(text: str, *, limit: int = 2) -> list[tuple[str, str, GeometrySpec]]:
    """Templates whose name (or synonym) the utterance mentions.

    Returns ``(canonical_name, matched_text, spec)`` tuples, at most `limit`,
    longest spoken form matched first so "cell phone" beats "phone".
    """
    lowered = text.lower()
    lib = _library()
    found: list[tuple[str, str, GeometrySpec]] = []
    for pattern, name in _index():
        if any(name == f[0] for f in found):
            continue
        m = pattern.search(lowered)
        if m:
            found.append((name, m.group(0), lib[name]))
            if len(found) >= limit:
                break
    return found


class TemplateClassifier:
    """Stage B: instant answer for bare "a <known thing>" create utterances.

    Satisfies the Classifier Protocol. Declines (zero-confidence NOOP) unless
    the utterance is a single known concept plus filler — richer phrasing
    belongs to the LLM (which still gets the template as few-shot reference).
    """

    async def classify(
        self,
        text: str,
        *,
        speaker_id: str,
        utterance_id: str,
        context: ClassifierContext,
    ) -> DesignOp:
        lowered = text.lower().strip(" .!?,")
        hits = match(lowered, limit=1)
        decline = DesignOp(
            op_type=OpType.NOOP,
            speaker_id=speaker_id,
            utterance_id=utterance_id,
            confidence=0.0,
            source_stage="template",
            raw_text=text,
        )
        if not hits:
            return decline
        name, matched, spec = hits[0]
        residue = lowered.replace(matched, " ", 1)
        leftover = [w for w in re.findall(r"[a-z0-9']+", residue) if w not in _FILLER]
        if leftover:
            return decline  # extra meaning -> LLM territory (with few-shot refs)
        _log.debug("template_hit", name=name, utterance_id=utterance_id)
        return DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.GROUP if spec.kind is ShapeKind.GROUP else spec.kind,
            geometry=spec.model_copy(deep=True),
            speaker_id=speaker_id,
            utterance_id=utterance_id,
            confidence=0.9,
            source_stage="template",
            raw_text=text,
        )
