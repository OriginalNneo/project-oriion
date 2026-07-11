"""D3 — TRUE 3D via the `solids` payload (plan.md §11 D3).

The LLM places axis-aligned solids in a relative 3D space; `payload_to_op`
projects them to an exact isometric GROUP via `domain/isometric.project_solids`
("model proposes, code disposes"). These tests pin:

  * every worked example in `_SYSTEM_PROMPT` parses, survives `payload_to_op`,
    and (if it carries geometry) renders — so a broken example fails loudly;
  * a `solids` payload becomes a renderable flat polygon/path GROUP fully
    inside the 0..100 box;
  * out-of-range solid numbers are clamped (repair, not reject);
  * a `patch` takes precedence over `solids`; unknown/empty solids degrade.
"""

from __future__ import annotations

import json

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import OpType
from quorum.pipeline.llm import (
    _SYSTEM_PROMPT,
    _LLMPayload,
    _parse_and_repair,
    _SolidSpec,
    payload_to_op,
)
from quorum.pipeline.renderer import SvgRenderer

# A self-contained 3D assembly: one block box with three cylinders on top.
_ENGINE = {
    "op_type": "create",
    "target_shape": "group",
    "confidence": 0.9,
    "label": "engine",
    "solids": [
        {"shape": "box", "x": 8, "y": 0, "z": 10, "w": 64, "d": 34, "h": 22,
         "color": "#6b7280", "name": "block"},
        {"shape": "cylinder", "x": 16, "y": 22, "z": 20, "w": 12, "d": 12, "h": 20,
         "color": "#9ca3af", "name": "piston-1"},
        {"shape": "cylinder", "x": 34, "y": 22, "z": 20, "w": 12, "d": 12, "h": 20,
         "color": "#9ca3af", "name": "piston-2"},
        {"shape": "cylinder", "x": 52, "y": 22, "z": 20, "w": 12, "d": 12, "h": 20,
         "color": "#9ca3af", "name": "piston-3"},
    ],
}


def _op(payload: _LLMPayload):  # type: ignore[no-untyped-def]
    return payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="x")


def _all_coords_in_box(spec: GeometrySpec) -> bool:
    """Every vertex / center+extent of a (possibly grouped) spec lies in 0..100."""
    parts = spec.parts if spec.kind is ShapeKind.GROUP else [spec]
    for p in parts:
        if p.points is not None:
            for px, py in p.points:
                if not (0.0 <= px <= 100.0 and 0.0 <= py <= 100.0):
                    return False
        # center +/- half-extent (path numbers are validated separately by the
        # domain validator already, so we only spot-check center coords here)
        if not (0.0 <= p.x <= 100.0 and 0.0 <= p.y <= 100.0):
            return False
    return True


# --------------------------------------------------------------------------- #
# Prompt examples must all stay valid end to end.
# --------------------------------------------------------------------------- #
def test_every_prompt_example_parses_and_renders() -> None:
    """Each `{"op_type"...}` worked example in the system prompt must validate,
    survive payload_to_op, and render when it carries geometry. Catches a typo
    in any example (including the new Example J solids one)."""
    lines = [
        ln.strip()
        for ln in _SYSTEM_PROMPT.splitlines()
        if ln.strip().startswith('{"op_type"')
    ]
    assert len(lines) >= 10, "expected the A..J worked examples"
    for raw in lines:
        payload = _LLMPayload.model_validate(json.loads(raw))
        op = _op(payload)
        if op.geometry is not None:
            assert SvgRenderer().render(op.geometry).startswith("<svg")


def test_prompt_teaches_solids() -> None:
    assert '"solids"' in _SYSTEM_PROMPT
    assert "Example J" in _SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# The solids path itself.
# --------------------------------------------------------------------------- #
def test_solids_payload_projects_to_renderable_group() -> None:
    payload = _LLMPayload.model_validate(_ENGINE)
    op = _op(payload)
    assert op.op_type is OpType.CREATE
    assert op.geometry is not None
    assert op.geometry.kind is ShapeKind.GROUP
    kinds = {p.kind for p in op.geometry.parts}
    # box -> polygon faces; cylinders -> path body + ellipse top
    assert ShapeKind.POLYGON in kinds
    assert kinds & {ShapeKind.PATH, ShapeKind.ELLIPSE}
    assert _all_coords_in_box(op.geometry)
    assert SvgRenderer().render(op.geometry).startswith("<svg")
    # label is preserved from the payload
    assert op.label == "engine"


def test_single_box_yields_three_visible_faces() -> None:
    payload = _LLMPayload.model_validate(
        {
            "op_type": "create",
            "solids": [
                {"shape": "box", "x": 20, "y": 20, "z": 20,
                 "w": 30, "d": 30, "h": 30, "color": "#dc2626", "name": "cube"}
            ],
        }
    )
    op = _op(payload)
    assert op.geometry is not None and op.geometry.kind is ShapeKind.GROUP
    faces = [p for p in op.geometry.parts if p.kind is ShapeKind.POLYGON]
    assert len(faces) == 3  # exactly the visible top/front/right; back faces culled
    # three distinct shades (light top / mid front / dark side)
    fills = {p.fill for p in faces}
    assert len(fills) == 3


def test_out_of_range_solids_are_clamped_not_rejected() -> None:
    raw = json.dumps(
        {
            "op_type": "create",
            "solids": [
                {"shape": "box", "x": 200, "y": -50, "z": 10,
                 "w": -5, "d": 999, "h": 30}
            ],
        }
    )
    payload = _parse_and_repair(raw)
    assert payload is not None
    assert payload.solids is not None
    s = payload.solids[0]
    assert 0.0 <= s.x <= 100.0 and 0.0 <= s.y <= 100.0
    assert s.w > 0.0 and s.d <= 100.0
    op = _op(payload)
    assert op.geometry is not None
    assert _all_coords_in_box(op.geometry)


def test_patch_takes_precedence_over_solids() -> None:
    """If a payload (oddly) carries both, the patch path wins and solids are
    ignored — solids must not graft a 3D body onto an edit."""
    focus = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[GeometrySpec(kind=ShapeKind.CIRCLE, name="eye-left", x=30, y=30,
                            width=4, height=4)],
    )
    payload = _LLMPayload.model_validate(
        {
            "op_type": "modify",
            "target_node_id": "n2",
            "patch": {"set": [{"part": "eye-left", "width": 8, "height": 8}],
                      "add": [], "remove": []},
            "solids": [{"shape": "box", "x": 10, "y": 10, "z": 10,
                        "w": 20, "d": 20, "h": 20}],
        }
    )
    op = payload_to_op(
        payload, speaker_id="a", utterance_id="u1", raw_text="make the eye bigger",
        focus_geometry=focus, focus_node_id="n2",
    )
    assert op.geometry is not None
    # patched circle, NOT a projected box: still a single-part group of a circle
    assert op.geometry.kind is ShapeKind.GROUP
    assert [p.kind for p in op.geometry.parts] == [ShapeKind.CIRCLE]


def test_unknown_or_empty_solids_degrade_to_no_geometry() -> None:
    # unknown shape -> project_solids returns None -> geometry untouched (None)
    payload = _LLMPayload.model_validate(
        {"op_type": "create", "solids": [{"shape": "torus", "x": 1, "y": 1, "z": 1,
                                          "w": 5, "d": 5, "h": 5}]}
    )
    op = _op(payload)
    assert op.geometry is None
    # empty list is falsy -> the solids branch never fires
    payload2 = _LLMPayload.model_validate({"op_type": "create", "solids": []})
    op2 = _op(payload2)
    assert op2.geometry is None


def test_solid_spec_defaults() -> None:
    s = _SolidSpec()
    assert s.shape == "box"
    assert s.w > 0 and s.d > 0 and s.h > 0
    assert s.color is None and s.name is None


def test_projected_solids_bypass_relation_snapping() -> None:
    """A 3D utterance containing 'within'/'inside' must NOT pass the projected
    geometry through snap_relations — its _snap_all_inside would yank the
    cylinder cap into the body. The op geometry must equal the raw projection."""
    from quorum.domain.isometric import Solid, project_solids

    payload = _LLMPayload.model_validate(_ENGINE)
    expected = project_solids(
        [
            Solid(shape=s.shape, x=s.x, y=s.y, z=s.z, w=s.w, d=s.d, h=s.h,
                  color=s.color, name=s.name)
            for s in payload.solids or []
        ]
    )
    op = payload_to_op(
        payload, speaker_id="a", utterance_id="u1",
        raw_text="a 3D engine with the pistons within the block",  # triggers _snap_all_inside
    )
    assert op.geometry == expected  # byte-identical: snapping was skipped


def test_modify_with_solids_pins_target_to_focus() -> None:
    """modify+solids must aim at the focused node, not a hallucinated id
    (mirrors the patch branch) — otherwise the 3D body grafts onto the wrong card."""
    payload = _LLMPayload.model_validate(
        {
            "op_type": "modify",
            "target_node_id": "WRONG-NODE",
            "solids": [{"shape": "box", "x": 10, "y": 10, "z": 10,
                        "w": 20, "d": 20, "h": 20}],
        }
    )
    op = payload_to_op(
        payload, speaker_id="a", utterance_id="u1", raw_text="make it 3D",
        focus_geometry=None, focus_node_id="n5",
    )
    assert op.target_node_id == "n5"


def test_create_with_solids_keeps_target_none() -> None:
    """A CREATE keeps target_node_id None even when a focus exists — it's a new idea."""
    payload = _LLMPayload.model_validate(_ENGINE)  # op_type create
    op = payload_to_op(
        payload, speaker_id="a", utterance_id="u1", raw_text="a 3D engine",
        focus_geometry=None, focus_node_id="n5",
    )
    assert op.target_node_id is None


def test_sphere_and_hemisphere_solids_round_trip_to_group_op() -> None:
    """A solids list mixing box + sphere + hemisphere validates as an
    _LLMPayload and payload_to_op projects it to ONE renderable flat GROUP —
    the wider vocabulary rides the same path as box/cylinder/wedge."""
    payload = _LLMPayload.model_validate(
        {
            "op_type": "create",
            "target_shape": "group",
            "confidence": 0.9,
            "label": "snowman",
            "solids": [
                {"shape": "box", "x": 20, "y": 0, "z": 20, "w": 40, "d": 40, "h": 6,
                 "color": "#9ca3af", "name": "base"},
                {"shape": "sphere", "x": 28, "y": 6, "z": 28, "w": 24, "d": 24, "h": 24,
                 "color": "#e5e7eb", "name": "body"},
                {"shape": "hemisphere", "x": 32, "y": 30, "z": 32, "w": 16, "d": 16,
                 "h": 9, "color": "#dc2626", "name": "hat"},
            ],
        }
    )
    op = _op(payload)
    assert op.op_type is OpType.CREATE
    assert op.geometry is not None
    assert op.geometry.kind is ShapeKind.GROUP
    names = [p.name or "" for p in op.geometry.parts]
    assert "body-body" in names and "body-highlight" in names
    assert "hat-dome" in names and "hat-highlight" in names
    assert _all_coords_in_box(op.geometry)
    assert SvgRenderer().render(op.geometry).startswith("<svg")
    assert op.label == "snowman"


def test_prompt_teaches_sphere_and_hemisphere() -> None:
    assert "sphere" in _SYSTEM_PROMPT and "hemisphere" in _SYSTEM_PROMPT


def test_payload_to_op_honours_max_parts() -> None:
    """The soft parts cap flows from the classifier seam into the projection."""
    payload = _LLMPayload.model_validate(
        {
            "op_type": "create",
            "solids": [
                {"shape": "box", "x": i * 4.0, "y": 0, "z": i * 4.0,
                 "w": 6, "d": 6, "h": 6, "name": f"box-{i}"}
                for i in range(25)  # 75 faces
            ],
        }
    )
    op_default = _op(payload)
    assert op_default.geometry is not None
    assert len(op_default.geometry.parts) <= 60
    op_raised = payload_to_op(
        payload, speaker_id="a", utterance_id="u1", raw_text="x", max_parts=90,
    )
    assert op_raised.geometry is not None
    assert len(op_raised.geometry.parts) == 75
