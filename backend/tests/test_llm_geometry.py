"""Stage C intricate-geometry contract tests (no network).

The LLM prompt (``pipeline/llm._SYSTEM_PROMPT``) now teaches the Geometry IR v2
primitives — polygon / path / text — so it can draw shapes the rules stage
can't. These tests pin the exact example payloads that prompt instructs the
model to emit: each must (1) pass the strict ``_LLMPayload`` validation, (2)
survive ``payload_to_op``, and (3) render through the deterministic reference
renderer. If a future prompt edit drifts the schema, these break — which is the
point. We assert the contract the live model is being told to satisfy, without
paying for a live call.
"""

from __future__ import annotations

from quorum.config.settings import Backend
from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.pipeline.llm import LLMClassifier, _LLMPayload, payload_to_op
from quorum.pipeline.renderer import SvgRenderer

# The three worked examples copied verbatim from _SYSTEM_PROMPT. Keeping them
# here as literals is deliberate: the test fails loudly if the prompt teaches
# geometry the validators would reject.
_STAR = """
{"op_type":"create","target_shape":"polygon","confidence":0.9,
 "geometry":{"kind":"polygon","x":50,"y":50,"width":50,"height":50,"stroke":"#1f2937",
   "points":[[50,12],[61,38],[89,38],[66,56],[75,84],[50,67],[25,84],[34,56],[11,38],[39,38]]}}
"""

_HOUSE = """
{"op_type":"create","target_shape":"group","confidence":0.85,
 "geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"stroke":"#1f2937","parts":[
   {"kind":"rectangle","name":"wall","x":50,"y":64,"width":48,"height":40,"stroke":"#1f2937"},
   {"kind":"polygon","name":"roof","x":50,"y":36,"width":56,"height":24,"stroke":"#b91c1c",
    "points":[[24,44],[50,22],[76,44]]},
   {"kind":"rectangle","name":"door","x":50,"y":74,"width":10,"height":20,"stroke":"#92400e"},
   {"kind":"rectangle","name":"window-left","x":36,"y":58,"width":9,"height":9,"stroke":"#2563eb"},
   {"kind":"rectangle","name":"window-right","x":64,"y":58,"width":9,"height":9,"stroke":"#2563eb"}]}}
"""

_HEART = """
{"op_type":"create","target_shape":"path","confidence":0.88,
 "geometry":{"kind":"path","x":50,"y":50,"width":60,"height":54,"stroke":"#dc2626",
   "d":"M50 78 C20 56 22 30 40 30 C48 30 50 38 50 42 C50 38 52 30 60 30 C78 30 80 56 50 78 Z"}}
"""


def _op(raw: str) -> DesignOp:
    payload = _LLMPayload.model_validate_json(raw)
    return payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="x")


def test_star_polygon_parses_and_renders() -> None:
    op = _op(_STAR)
    assert op.op_type == OpType.CREATE
    assert op.geometry is not None
    assert op.geometry.kind is ShapeKind.POLYGON
    assert op.geometry.points is not None and len(op.geometry.points) == 10
    assert SvgRenderer().render(op.geometry).startswith("<svg")


def test_house_group_mixes_polygon_and_rectangles() -> None:
    op = _op(_HOUSE)
    assert op.geometry is not None and op.geometry.kind is ShapeKind.GROUP
    kinds = [p.kind for p in op.geometry.parts]
    assert ShapeKind.POLYGON in kinds  # the roof
    assert kinds.count(ShapeKind.RECTANGLE) == 4  # wall, door, two windows
    # named parts survive for later targeted MODIFY
    assert {p.name for p in op.geometry.parts} == {
        "wall",
        "roof",
        "door",
        "window-left",
        "window-right",
    }
    assert SvgRenderer().render(op.geometry).startswith("<svg")


def test_heart_path_obeys_absolute_uppercase_constraint() -> None:
    op = _op(_HEART)
    assert op.geometry is not None and op.geometry.kind is ShapeKind.PATH
    assert op.geometry.d is not None
    # constrained path: absolute uppercase commands only (no lowercase letters)
    assert not any(c.islower() for c in op.geometry.d)
    assert SvgRenderer().render(op.geometry).startswith("<svg")


async def test_llm_classifier_parses_intricate_payload_via_mock() -> None:
    """End to end through the real LLMClassifier with the HTTP call faked."""

    clf = LLMClassifier(backend=Backend.GROQ, model="x", api_key="k")

    async def _fake_complete(text: str, context: object, *, references: object = None) -> str:
        return _HEART

    clf._complete = _fake_complete  # type: ignore[method-assign]

    op = await clf.classify(
        "a heart", speaker_id="a", utterance_id="u1", context=ClassifierContext()
    )
    assert op.op_type == OpType.CREATE
    assert op.source_stage == "llm"
    assert op.geometry is not None and op.geometry.kind is ShapeKind.PATH


def test_payload_label_flows_to_op() -> None:
    """R5 (plan.md §12 R3): a model-supplied label lands on the DesignOp."""
    payload = _LLMPayload(op_type=OpType.CREATE, label="tabby cat")
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="a tabby cat")
    assert op.label == "tabby cat"


def test_create_without_label_falls_back_to_template_concept() -> None:
    """CREATE with no model label takes the matched template name ("snowman")
    so the node stays addressable ("make the snowman blue") — plan.md §12 R3."""
    payload = _LLMPayload(op_type=OpType.CREATE)
    op = payload_to_op(
        payload, speaker_id="a", utterance_id="u1", raw_text="a snowman wearing a top hat"
    )
    assert op.label == "snowman"


def test_modify_without_label_stays_none_for_inheritance() -> None:
    """MODIFY leaves label None — the engine inherits the parent node's label."""
    payload = _LLMPayload(op_type=OpType.MODIFY, target_node_id="n1")
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="make the cat orange")
    assert op.label is None


def _mouse_scene() -> GeometrySpec:
    return GeometrySpec.model_validate(
        {
            "kind": "group",
            "parts": [
                {"kind": "circle", "name": "body", "x": 40, "y": 55, "width": 30, "height": 24},
                {"kind": "circle", "name": "eye-left", "x": 31, "y": 40, "width": 4, "height": 4},
                {"kind": "circle", "name": "eye-right", "x": 40, "y": 40, "width": 4, "height": 4},
            ],
        }
    )


def test_patch_payload_composes_scene_against_focus() -> None:
    """§13 N3: the model emits only the delta; code composes the scene."""
    from quorum.domain.parts import PartsPatch

    payload = _LLMPayload(
        op_type=OpType.MODIFY,
        target_node_id="n9",  # patch was computed against the FOCUS — must be re-pointed
        patch=PartsPatch(set=[{"part": "eye-left", "width": 7.0, "height": 7.0}]),
    )
    op = payload_to_op(
        payload,
        speaker_id="a",
        utterance_id="u1",
        raw_text="make the left eye bigger",
        focus_geometry=_mouse_scene(),
        focus_node_id="n2",
    )
    assert op.target_node_id == "n2"
    assert op.geometry is not None
    by_name = {p.name: p for p in op.geometry.parts}
    assert by_name["eye-left"].width == 7.0 and by_name["eye-left"].height == 7.0
    assert by_name["eye-right"].width == 4.0  # untouched sibling
    assert by_name["body"].width == 30.0


def test_patch_with_all_clauses_dropped_changes_nothing() -> None:
    """A patch full of unknown part names degrades to a no-geometry op."""
    from quorum.domain.parts import PartsPatch

    payload = _LLMPayload(
        op_type=OpType.MODIFY,
        patch=PartsPatch(set=[{"part": "nose", "width": 9.0}], remove=["whiskers"]),
    )
    op = payload_to_op(
        payload,
        speaker_id="a",
        utterance_id="u1",
        raw_text="make the nose bigger",
        focus_geometry=_mouse_scene(),
        focus_node_id="n2",
    )
    assert op.geometry is None


def test_patch_add_clamps_out_of_range_coords_via_repair() -> None:
    """The clamp repair pass covers patch.add parts too."""
    raw = (
        '{"op_type":"modify","confidence":0.9,"patch":{"set":[],"remove":[],'
        '"add":[{"kind":"circle","name":"hat","x":140,"y":-3,"width":8,"height":8}]}}'
    )
    from quorum.pipeline.llm import _parse_and_repair

    payload = _parse_and_repair(raw)
    assert payload is not None and payload.patch is not None
    assert payload.patch.add[0].x == 100.0 and payload.patch.add[0].y == 0.0
