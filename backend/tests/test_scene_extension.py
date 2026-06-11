"""Detection escalation + scene-extension tests (no network).

Two gaps closed here, found at the "draw more complicated things" review:

1. *False-confident rules matches*: "a rocket with a box body and five
   thrusters" contains "box", so the rules stage used to emit a lone rectangle
   at 0.85 and the LLM never saw the utterance. Now ≥2 unexplained content
   words push a matched op below the cascade threshold — the LLM takes it, and
   the rules op remains the dead-LLM fallback.

2. *Scenes couldn't be extended*: "now add five thrusters" needs the LLM to see
   the focused node's current geometry (``ClassifierContext.focus_geometry``)
   and the engine to accept replacement geometry on MODIFY. The prompt's
   Example D (funnel-on-its-side + thrusters) is pinned through validation and
   the reference renderer, like the other worked examples.
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.engine import DesignStateEngine
from quorum.engine.clock import FixedClock
from quorum.pipeline.classify import CascadeClassifier, RulesClassifier
from quorum.pipeline.llm import _LLMPayload, payload_to_op
from quorum.pipeline.renderer import SvgRenderer

from .test_cascade import FakeLLM

_CTX = ClassifierContext()


async def _rules(text: str) -> DesignOp:
    return await RulesClassifier().classify(
        text, speaker_id="a", utterance_id="u1", context=_CTX
    )


# --------------------------------------------------------------------------- #
# 1) coverage heuristic: hazy utterances escalate, plain ones stay fast       #
# --------------------------------------------------------------------------- #
async def test_shape_word_inside_rich_utterance_escalates() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "a rocket with a box body and five thrusters",
        speaker_id="a",
        utterance_id="u1",
        context=_CTX,
    )
    assert llm.calls == 1  # "rocket"/"thrusters" outweigh the matched "box"
    assert op.source_stage == "llm"


async def test_plain_shape_utterance_stays_on_fast_path() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "a red circle", speaker_id="a", utterance_id="u1", context=_CTX
    )
    assert llm.calls == 0
    assert op.source_stage == "rules"
    assert op.confidence >= 0.85


async def test_one_unknown_word_does_not_escalate() -> None:
    # A single stray word ("wheel") isn't enough to pay the LLM round-trip.
    op = await _rules("a circle for the wheel")
    assert op.op_type == OpType.CREATE
    assert op.confidence >= 0.85


async def test_hazy_rules_op_is_the_dead_llm_fallback() -> None:
    llm = FakeLLM(op_type=OpType.NOOP, confidence=0.0)  # dead LLM
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "a rocket with a box body and five thrusters",
        speaker_id="a",
        utterance_id="u1",
        context=_CTX,
    )
    assert llm.calls == 1
    assert op.source_stage == "rules"  # degraded to the basic shape, not dropped
    assert op.op_type == OpType.CREATE


async def test_hazy_scene_composition_escalates_too() -> None:
    op = await _rules("a circle on top of a box for the snowman rocket thing")
    assert op.target_shape == ShapeKind.GROUP
    assert op.confidence < 0.55  # below the default cascade threshold


# --------------------------------------------------------------------------- #
# 2) engine: MODIFY accepts replacement geometry (LLM re-emits the scene)     #
# --------------------------------------------------------------------------- #
def _scene(parts: list[GeometrySpec]) -> GeometrySpec:
    return GeometrySpec(kind=ShapeKind.GROUP, parts=parts)


def test_modify_with_geometry_replaces_scene() -> None:
    eng = DesignStateEngine(room="t", clock=FixedClock())
    created = eng.apply(
        DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.GROUP,
            geometry=_scene([GeometrySpec(kind=ShapeKind.POLYGON, name="funnel-body",
                                          points=[[12.0, 28.0], [12.0, 72.0], [86.0, 50.0]])]),
            speaker_id="alice",
            utterance_id="u1",
        )
    ).upserted[0]

    extended = _scene(
        [
            GeometrySpec(kind=ShapeKind.POLYGON, name="funnel-body",
                         points=[[12.0, 28.0], [12.0, 72.0], [86.0, 50.0]]),
            GeometrySpec(kind=ShapeKind.RECTANGLE, name="thruster-1", x=7, y=40,
                         width=8, height=7),
            GeometrySpec(kind=ShapeKind.RECTANGLE, name="thruster-2", x=7, y=60,
                         width=8, height=7),
        ]
    )
    diff = eng.apply(
        DesignOp(
            op_type=OpType.MODIFY,
            target_node_id=created.id,
            geometry=extended,
            speaker_id="alice",
            utterance_id="u2",
        )
    )
    node = diff.upserted[0]
    assert [p.name for p in node.geometry.parts] == ["funnel-body", "thruster-1", "thruster-2"]
    assert node.svg and node.svg.startswith("<svg")


def test_modify_without_geometry_still_mutates_in_place() -> None:
    eng = DesignStateEngine(room="t", clock=FixedClock())
    created = eng.apply(
        DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.CIRCLE,
            geometry=GeometrySpec(kind=ShapeKind.CIRCLE, width=20, height=20),
            speaker_id="alice",
            utterance_id="u1",
        )
    ).upserted[0]
    diff = eng.apply(
        DesignOp(
            op_type=OpType.MODIFY,
            target_node_id=created.id,
            modifiers=["bigger"],
            speaker_id="alice",
            utterance_id="u2",
        )
    )
    assert diff.upserted[0].geometry.width > 20


def test_classifier_context_carries_focus_geometry() -> None:
    eng = DesignStateEngine(room="t", clock=FixedClock())
    assert eng.classifier_context().focus_geometry is None
    eng.apply(
        DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.CIRCLE,
            geometry=GeometrySpec(kind=ShapeKind.CIRCLE, width=33, height=33),
            speaker_id="alice",
            utterance_id="u1",
        )
    )
    ctx = eng.classifier_context()
    assert ctx.focus_geometry is not None
    assert ctx.focus_geometry.kind is ShapeKind.CIRCLE
    assert ctx.focus_geometry.width == 33


# --------------------------------------------------------------------------- #
# 3) prompt Example D (extend-scene) pinned through validation + renderer     #
# --------------------------------------------------------------------------- #
_EXTEND = """
{"op_type":"modify","target_shape":"group","target_node_id":"n3","confidence":0.85,
 "geometry":{"kind":"group","x":50,"y":50,"width":90,"height":60,"stroke":"#1f2937","parts":[
   {"kind":"polygon","name":"funnel-body","x":50,"y":50,"width":74,"height":44,
    "stroke":"#1f2937","points":[[12,28],[12,72],[58,56],[86,52],[86,48],[58,44]]},
   {"kind":"rectangle","name":"thruster-1","x":7,"y":32,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-2","x":7,"y":41,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-3","x":7,"y":50,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-4","x":7,"y":59,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-5","x":7,"y":68,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"}]}}
"""


def test_prompt_example_d_extend_scene_parses_and_renders() -> None:
    payload = _LLMPayload.model_validate_json(_EXTEND)
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="add five thrusters")
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n3"
    assert op.geometry is not None
    names = [p.name for p in op.geometry.parts]
    assert names[0] == "funnel-body" and len(names) == 6
    assert SvgRenderer().render(op.geometry).startswith("<svg")
