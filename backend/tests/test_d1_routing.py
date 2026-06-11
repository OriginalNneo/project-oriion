"""D1 routing-repair tests — 3D-intent escalation.

Pins the three acceptance criteria from the D1 segment spec:

1. "a 3D box" must NOT resolve as a confident rules CREATE of a flat rect.
   The rules stage must be capped at _HAZY_CONFIDENCE (0.5) so the cascade
   escalates past it.  "a 3D box" has the synonym "3d box" -> "cuboid" in
   the template bank, so the cascade returns the isometric cuboid from the
   template stage — not a flat rectangle from the rules stage.

2. "a 3D cube" must still hit the isometric template directly (conf 0.9,
   source=template) — the template stage treats "3d" as filler and "cube"
   as the concept keyword, so no escalation cost is paid.

3. Plain "a box" stays a fast confident rules match (no LLM tax).

Additional variant coverage: "isometric", "three dimensional", "3-d".
"""

from __future__ import annotations

import pytest

from quorum.domain.geometry import ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.pipeline.classify import _HAZY_CONFIDENCE, CascadeClassifier, RulesClassifier
from quorum.pipeline.templates import TemplateClassifier

_CTX = ClassifierContext()


async def _rules_op(text: str) -> DesignOp:
    """Run only the rules stage (no cascade) and return the DesignOp."""
    return await RulesClassifier().classify(
        text, speaker_id="a", utterance_id="u1", context=_CTX
    )


# ── acceptance criterion 1: 3D-intent → rules result is hazy ─────────────── #


@pytest.mark.parametrize(
    "utterance",
    [
        "a 3D box",
        "a 3d box",
        "a 3-d box",
        "draw a 3d rectangle",
        "an isometric rectangle",
        "a three dimensional circle",
    ],
)
async def test_3d_intent_caps_rules_confidence(utterance: str) -> None:
    """Rules stage must emit _HAZY_CONFIDENCE (0.5) for any 3D-flagged utterance."""
    op = await _rules_op(utterance)
    assert op.confidence == _HAZY_CONFIDENCE, (
        f"{utterance!r}: expected conf {_HAZY_CONFIDENCE}, got {op.confidence}"
    )


async def test_3d_box_does_not_ship_confident_flat_rect() -> None:
    """'a 3D box' must not return a confident rules CREATE (the flat-rect bug)."""
    op = await _rules_op("a 3D box")
    # Rules may still identify a CREATE, but confidence must be capped below threshold.
    assert op.confidence < 0.55, (
        f"confidence {op.confidence} would skip escalation — flat-rect bug not fixed"
    )


async def test_3d_box_cascade_escapes_rules_stage() -> None:
    """'a 3D box' must escape the rules stage (hazy cap forces escalation).

    'a 3D box' maps to the 'cuboid' isometric template via the synonym
    "3d box" -> "cuboid", so the template stage answers it correctly.  The
    test verifies:
    - The rules stage emits a hazy (0.5) result (the 3D cap is working).
    - The cascade does NOT return the flat-rect rules result; it escalates
      and returns from the template stage with the isometric cuboid.
    """
    # Rules stage alone: must be hazy.
    rules_op = await _rules_op("a 3D box")
    assert rules_op.confidence == _HAZY_CONFIDENCE, (
        f"rules stage not capped: conf={rules_op.confidence}"
    )

    # Full cascade (with dead LLM): must return from template (cuboid), not rules.
    class _DeadLLM:
        calls: int = 0

        async def classify(
            self, text: str, *, speaker_id: str, utterance_id: str, context: ClassifierContext
        ) -> DesignOp:
            _DeadLLM.calls += 1
            return DesignOp(
                op_type=OpType.NOOP,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                confidence=0.0,
                source_stage="llm",
            )

    _DeadLLM.calls = 0
    cascade = CascadeClassifier(
        RulesClassifier(),
        _DeadLLM(),
        template=TemplateClassifier(),
    )
    op = await cascade.classify(
        "a 3D box", speaker_id="a", utterance_id="u1", context=_CTX
    )
    # "3d box" -> "cuboid" is a template synonym; cascade returns from template.
    assert op.source_stage == "template", (
        f"expected template to catch '3D box' via cuboid synonym, got {op.source_stage}"
    )
    assert op.confidence == 0.9
    # LLM was not needed (template answered it).
    assert _DeadLLM.calls == 0


# ── acceptance criterion 2: "a 3D cube" hits the template directly ────────── #


async def test_3d_cube_is_template_direct_hit() -> None:
    """'a 3D cube' must resolve via the template bank, not cost an LLM call."""
    op = await TemplateClassifier().classify(
        "a 3D cube", speaker_id="a", utterance_id="u1", context=_CTX
    )
    assert op.op_type is OpType.CREATE, f"expected CREATE, got {op.op_type}"
    assert op.source_stage == "template", f"expected template, got {op.source_stage}"
    assert op.confidence == 0.9
    assert op.geometry is not None and len(op.geometry.parts) == 3


async def test_3d_cube_cascade_skips_llm() -> None:
    """In the full cascade 'a 3D cube' must return from template (no LLM cost)."""

    class _CountingLLM:
        calls: int = 0

        async def classify(
            self, text: str, *, speaker_id: str, utterance_id: str, context: ClassifierContext
        ) -> DesignOp:
            _CountingLLM.calls += 1
            return DesignOp(
                op_type=OpType.CREATE,
                target_shape=ShapeKind.GROUP,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                confidence=0.9,
                source_stage="llm",
            )

    _CountingLLM.calls = 0
    cascade = CascadeClassifier(
        RulesClassifier(),
        _CountingLLM(),
        template=TemplateClassifier(),
    )
    op = await cascade.classify(
        "a 3D cube", speaker_id="a", utterance_id="u1", context=_CTX
    )
    assert op.source_stage == "template", f"expected template, got {op.source_stage}"
    assert _CountingLLM.calls == 0, "LLM was called for a known template — no-op tax bug"


# ── acceptance criterion 3: plain "a box" stays fast and confident ─────────── #


async def test_plain_box_stays_confident_rules_result() -> None:
    """'a box' has no 3D intent; the rules stage must return a confident match."""
    op = await _rules_op("a box")
    assert op.op_type is OpType.CREATE
    assert op.source_stage == "rules"
    assert op.confidence >= 0.55, (
        f"plain 'a box' was capped hazy ({op.confidence}) — fast path broken"
    )


async def test_plain_box_cascade_skips_llm() -> None:
    """In the full cascade 'a box' must return from rules without paying LLM."""

    class _CountingLLM2:
        calls: int = 0

        async def classify(
            self, text: str, *, speaker_id: str, utterance_id: str, context: ClassifierContext
        ) -> DesignOp:
            _CountingLLM2.calls += 1
            return DesignOp(
                op_type=OpType.CREATE,
                target_shape=ShapeKind.GROUP,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                confidence=0.9,
                source_stage="llm",
            )

    _CountingLLM2.calls = 0
    cascade = CascadeClassifier(
        RulesClassifier(),
        _CountingLLM2(),
        template=TemplateClassifier(),
    )
    op = await cascade.classify(
        "a box", speaker_id="a", utterance_id="u1", context=_CTX
    )
    assert op.source_stage == "rules"
    assert _CountingLLM2.calls == 0, "LLM was called for plain 'a box' — fast path broken"
