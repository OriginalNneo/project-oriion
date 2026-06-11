"""Template library (cascade stage B) tests.

The library is mined from Quick, Draw! by ``scripts/mine_templates.py`` into
``pipeline/templates/quickdraw.json`` (checked in). Pinned here: every shipped
template validates and renders; matching handles synonyms and plurals; the
direct-hit stage answers bare create utterances and DECLINES rich ones; the
cascade consults templates before paying for the LLM; and the LLM user payload
carries matched references.
"""

from __future__ import annotations

import json

from quorum.domain.op import ClassifierContext, OpType
from quorum.pipeline.classify import CascadeClassifier, RulesClassifier
from quorum.pipeline.llm import LLMClassifier
from quorum.pipeline.renderer import SvgRenderer
from quorum.pipeline.templates import TemplateClassifier, _library, match

from .test_cascade import FakeLLM

_CTX = ClassifierContext()


def test_library_loads_and_every_template_renders() -> None:
    lib = _library()
    assert len(lib) >= 50  # the curated bank actually shipped
    renderer = SvgRenderer()
    for name, spec in lib.items():
        svg = renderer.render(spec)
        assert svg.startswith("<svg"), name


def test_match_finds_named_concept_and_synonym() -> None:
    assert [m[0] for m in match("a snowman in the corner")] == ["snowman"]
    assert [m[0] for m in match("a smartphone")] == ["cell phone"]  # synonym
    assert [m[0] for m in match("two houses")] == ["house"]  # plural
    assert match("ummm what about lunch") == []


async def _template_op(text: str) -> object:
    return await TemplateClassifier().classify(
        text, speaker_id="a", utterance_id="u1", context=_CTX
    )


async def test_direct_hit_answers_bare_create_utterance() -> None:
    op = await _template_op("draw a snowman")
    assert op.op_type is OpType.CREATE  # type: ignore[attr-defined]
    assert op.source_stage == "template"  # type: ignore[attr-defined]
    assert op.confidence == 0.9  # type: ignore[attr-defined]
    assert op.geometry is not None  # type: ignore[attr-defined]


async def test_rich_utterance_declines_to_llm() -> None:
    op = await _template_op("a snowman with a red scarf and a blue hat")
    assert op.op_type is OpType.NOOP  # type: ignore[attr-defined]
    assert op.confidence == 0.0  # type: ignore[attr-defined]


async def test_cascade_template_hit_skips_llm() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm, template=TemplateClassifier())
    op = await cascade.classify(
        "a snowman", speaker_id="a", utterance_id="u1", context=_CTX
    )
    assert op.source_stage == "template"
    assert llm.calls == 0  # the known concept costs nothing


async def test_cascade_template_decline_still_reaches_llm() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm, template=TemplateClassifier())
    op = await cascade.classify(
        "a snowman wearing a top hat made of gears",
        speaker_id="a",
        utterance_id="u1",
        context=_CTX,
    )
    assert llm.calls == 1
    assert op.source_stage == "llm"


def test_llm_user_payload_carries_reference_sketches() -> None:
    payload = json.loads(
        LLMClassifier._user_payload("a snowman wearing a top hat", _CTX)
    )
    refs = payload["context"]["reference_sketches"]
    assert refs is not None and refs[0]["name"] == "snowman"
    assert "kind" in refs[0]["geometry"]

    no_refs = json.loads(LLMClassifier._user_payload("something abstract", _CTX))
    assert no_refs["context"]["reference_sketches"] is None
