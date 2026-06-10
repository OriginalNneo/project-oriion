"""Cascade (stage A -> stage C) and LLM-payload contract tests.

No network: the LLM is faked. What's pinned here is the *escalation policy*
(confident rules result never pays LLM latency; weak/NOOP results escalate;
a dead LLM falls back to the rules result — plan.md §9 graceful degradation)
and the strict JSON -> DesignOp parsing the real LLM backend relies on.
"""

from __future__ import annotations

from quorum.domain.geometry import ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.pipeline.classify import CascadeClassifier, RulesClassifier
from quorum.pipeline.llm import _LLMPayload, payload_to_op

_CTX = ClassifierContext()


class FakeLLM:
    """Scriptable stage C; counts calls so tests can assert escalation."""

    def __init__(self, op_type: OpType = OpType.CREATE, confidence: float = 0.9) -> None:
        self.calls = 0
        self._op_type = op_type
        self._confidence = confidence

    async def classify(
        self, text: str, *, speaker_id: str, utterance_id: str, context: ClassifierContext
    ) -> DesignOp:
        self.calls += 1
        return DesignOp(
            op_type=self._op_type,
            target_shape=ShapeKind.GROUP if self._op_type is OpType.CREATE else None,
            speaker_id=speaker_id,
            utterance_id=utterance_id,
            confidence=self._confidence,
            source_stage="llm",
        )


async def _run(cascade: CascadeClassifier, text: str) -> DesignOp:
    return await cascade.classify(text, speaker_id="a", utterance_id="u1", context=_CTX)


async def test_confident_rules_result_skips_llm() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await _run(cascade, "a red circle")
    assert op.source_stage == "rules"
    assert llm.calls == 0  # the fast path never pays LLM latency


async def test_noop_escalates_to_llm() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await _run(cascade, "a snowman wearing a hat")  # no rule matches this
    assert llm.calls == 1
    assert op.source_stage == "llm"
    assert op.op_type == OpType.CREATE


async def test_dead_llm_falls_back_to_rules() -> None:
    # A failed LLM call surfaces as a zero-confidence NOOP (see llm.py).
    llm = FakeLLM(op_type=OpType.NOOP, confidence=0.0)
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await _run(cascade, "ummm what about lunch")
    assert llm.calls == 1
    assert op.source_stage == "rules"  # degraded, not broken
    assert op.op_type == OpType.NOOP


def test_llm_payload_parses_group_scene() -> None:
    raw = """
    {"op_type": "create", "target_shape": "group", "confidence": 0.85,
     "geometry": {"kind": "group", "parts": [
        {"kind": "circle", "x": 50, "y": 76, "width": 32, "height": 32},
        {"kind": "circle", "x": 50, "y": 52, "width": 24, "height": 24},
        {"kind": "circle", "x": 50, "y": 33, "width": 16, "height": 16}]}}
    """
    payload = _LLMPayload.model_validate_json(raw)
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="a snowman")
    assert op.op_type == OpType.CREATE
    assert op.source_stage == "llm"
    assert op.geometry is not None and len(op.geometry.parts) == 3
    assert all(p.kind == ShapeKind.CIRCLE for p in op.geometry.parts)


def test_llm_payload_rejects_out_of_range_values() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _LLMPayload.model_validate_json('{"op_type": "create", "confidence": 7}')
