"""Keyless regression guards for the drawing-quality refinement loop.

The live adherence battery (:mod:`quorum.eval.battery`) is the loop's fitness
signal but needs a network + key, so it cannot run in the gate. These tests lock
the DETERMINISTIC facts each accepted refinement relies on — the "code disposes"
half of every fix — so a later segment cannot silently undo a gain. They are
pure/keyless and run in ``uv run pytest -q``.

Add one guard per accepted segment (name it ``test_seg<N>_...``).
"""

from __future__ import annotations

import json

from quorum.domain.geometry import ShapeKind
from quorum.domain.isometric import Solid, project_solids
from quorum.eval.adherence import NAMED_COLORS
from quorum.eval.battery import ALL, HELDOUT, SETS, TUNING
from quorum.pipeline.llm import (
    _LLMPayload,
    _normalize_solid_shape,
    _parse_and_repair,
    payload_to_op,
)


# --------------------------------------------------------------------------- #
# Battery integrity — the fitness set must stay machine-checkable.
# --------------------------------------------------------------------------- #
def test_battery_sets_are_disjoint_and_nonempty() -> None:
    tuning_texts = {t for t, _ in TUNING}
    heldout_texts = {t for t, _ in HELDOUT}
    assert tuning_texts and heldout_texts
    # A held-out prompt tuned against would defeat the anti-Goodhart split.
    assert tuning_texts.isdisjoint(heldout_texts)
    assert len(tuning_texts) == len(TUNING)  # no dup prompts within a set
    assert len(heldout_texts) == len(HELDOUT)
    assert SETS["all"] == ALL == TUNING + HELDOUT


def test_battery_colors_are_all_scorable() -> None:
    # Every color an Expectation asks for must have a NAMED_COLORS entry, else
    # the scorer reports "unknown" and the prompt silently can't earn color.
    for _text, expect in ALL:
        for color in expect.colors:
            assert color in NAMED_COLORS, f"{color!r} not in NAMED_COLORS"


def test_battery_relations_reference_named_parts() -> None:
    for _text, expect in ALL:
        for rel in expect.relations:
            assert rel.kind in {"inside", "above", "below", "beside"}
            assert rel.inner and rel.outer


# --------------------------------------------------------------------------- #
# Seg 1 (wedge/ramp 3D): the deterministic projector already handles a wedge;
# lock that so the model-facing fix has a valid target to emit into.
# --------------------------------------------------------------------------- #
def test_wedge_projects_to_shaded_solid() -> None:
    spec = project_solids([Solid("wedge", 0, 0, 0, 40, 24, 30, "#9ca3af", "ramp")])
    assert spec is not None
    assert spec.kind is ShapeKind.GROUP
    # A wedge shows two visible faces from the isometric view (front tri + slope).
    assert len(spec.parts) >= 2
    # Faces are distinctly shaded (not a flat fill) — the solids3d signature.
    fills = {p.fill for p in spec.parts}
    assert len(fills) >= 2


# --------------------------------------------------------------------------- #
# Seg 1 (3D-invalid fix): gemini-2.5-flash-lite emits the STRING "null" for
# target_shape on single-solid answers, which failed ShapeKind validation and
# discarded otherwise-perfect solids payloads (all 5 measured 3D failures).
# The parse path now normalizes these quirks deterministically — lock it.
# --------------------------------------------------------------------------- #
def _solid_payload(solids: object, target_shape: object = "null") -> str:
    """The exact shape of a live gemini-2.5-flash-lite single-solid reply."""
    return json.dumps({
        "op_type": "create",
        "target_shape": target_shape,
        "target_node_id": None,
        "relation_to_node": None,
        "modifiers": [],
        "preference_signal": 0.0,
        "confidence": 0.9,
        "label": "solid",
        "geometry": None,
        "patch": None,
        "solids": solids,
    })


def test_seg1_string_null_target_shape_is_salvaged() -> None:
    # Verbatim live failure for "a 3D sphere": target_shape is the STRING "null".
    raw = _solid_payload(
        [{"shape": "sphere", "x": 50, "y": 50, "z": 50, "w": 50, "d": 50, "h": 50,
          "color": "#9ca3af", "name": "sphere"}],
        target_shape="null",
    )
    payload = _parse_and_repair(raw)
    assert payload is not None
    assert payload.target_shape is None
    assert payload.solids is not None and payload.solids[0].shape == "sphere"
    op = payload_to_op(payload, speaker_id="p", utterance_id="u", raw_text="a 3D sphere")
    assert op.geometry is not None
    assert op.geometry.kind is ShapeKind.GROUP
    assert len(op.geometry.parts) >= 1


def test_seg1_each_known_solid_yields_valid_group() -> None:
    # One wedge / cylinder / sphere / hemisphere payload each must survive the
    # full parse→project path into a non-empty shaded GROUP.
    for shape, min_parts in (("wedge", 2), ("cylinder", 2), ("sphere", 1),
                             ("hemisphere", 1), ("box", 3)):
        raw = _solid_payload(
            [{"shape": shape, "x": 25, "y": 0, "z": 25, "w": 50, "d": 50, "h": 50,
              "color": "#6b7280", "name": shape}]
        )
        payload = _parse_and_repair(raw)
        assert payload is not None, shape
        op = payload_to_op(payload, speaker_id="p", utterance_id="u", raw_text=f"a 3D {shape}")
        assert op.geometry is not None, shape
        assert op.geometry.kind is ShapeKind.GROUP, shape
        assert len(op.geometry.parts) >= min_parts, shape


def test_seg1_solid_shape_synonyms_normalize() -> None:
    assert _normalize_solid_shape("prism") == "wedge"
    assert _normalize_solid_shape("triangular prism") == "wedge"
    assert _normalize_solid_shape("ramp") == "wedge"
    assert _normalize_solid_shape("ball") == "sphere"
    assert _normalize_solid_shape("orb") == "sphere"
    assert _normalize_solid_shape("tube") == "cylinder"
    assert _normalize_solid_shape("can") == "cylinder"
    assert _normalize_solid_shape("cube") == "box"
    assert _normalize_solid_shape("dome") == "hemisphere"
    # Exact projector names pass through untouched (case-insensitive).
    assert _normalize_solid_shape("Sphere") == "sphere"
    # Unknown shapes default to box — a 3D prompt must never return invalid.
    assert _normalize_solid_shape("dodecahedron") == "box"


def test_seg1_synonym_solid_projects_to_geometry() -> None:
    raw = _solid_payload(
        [{"shape": "prism", "x": 25, "y": 0, "z": 25, "w": 50, "d": 50, "h": 50,
          "color": "#6b7280", "name": "prism-body"}]
    )
    payload = _parse_and_repair(raw)
    assert payload is not None
    assert payload.solids is not None and payload.solids[0].shape == "wedge"
    op = payload_to_op(payload, speaker_id="p", utterance_id="u",
                       raw_text="a triangular prism in 3D")
    assert op.geometry is not None and len(op.geometry.parts) >= 2


def test_seg1_bare_solid_object_becomes_one_element_list() -> None:
    raw = _solid_payload(
        {"shape": "sphere", "x": 50, "y": 0, "z": 50, "w": 40, "d": 40, "h": 40,
         "color": None, "name": "ball"}
    )
    payload = _parse_and_repair(raw)
    assert payload is not None
    assert payload.solids is not None and len(payload.solids) == 1
    assert payload.solids[0].shape == "sphere"


# --------------------------------------------------------------------------- #
# Seg 2 (truncated-JSON salvage): verbose scenes overrun the output-token cap
# and the reply arrives cut off mid `geometry.parts` (measured live: "a car
# with four wheels" → 8046 chars ending mid-object, JSONDecodeError, NOOP,
# adherence 0.00). The parse path now recovers the largest valid prefix —
# complete leading parts kept, the half-written trailing element dropped —
# instead of discarding everything. Lock the salvage AND its conservatism.
# --------------------------------------------------------------------------- #
def _car_parts(n_wheels: int = 4) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = [
        {"kind": "rectangle", "name": "body", "x": 50, "y": 60, "width": 70,
         "height": 18, "corner_radius": 3, "stroke": "#1f2937", "parts": []},
        {"kind": "rectangle", "name": "cabin", "x": 50, "y": 46, "width": 34,
         "height": 14, "corner_radius": 3, "stroke": "#1f2937", "parts": []},
    ]
    for i in range(n_wheels):
        parts.append({"kind": "circle", "name": f"wheel-{i + 1}", "x": 20 + i * 20,
                      "y": 72, "width": 10, "height": 10, "stroke": "#1f2937",
                      "parts": []})
    return parts


def _group_payload(parts: list[dict[str, object]]) -> str:
    """A full LLM reply whose geometry is a group of named parts."""
    return json.dumps({
        "op_type": "create",
        "target_shape": "group",
        "target_node_id": None,
        "relation_to_node": None,
        "modifiers": [],
        "preference_signal": 0.0,
        "confidence": 0.9,
        "label": "car",
        "geometry": {"kind": "group", "x": 50, "y": 50, "width": 80, "height": 40,
                     "corner_radius": 0, "stroke": "#1f2937", "parts": parts},
        "patch": None,
        "solids": None,
    })


def _part_names(payload: _LLMPayload | None) -> list[str | None]:
    assert payload is not None
    geom = payload.geometry
    assert geom is not None and geom.kind is ShapeKind.GROUP
    return [p.name for p in geom.parts]


def test_seg2_truncated_mid_parts_salvages_complete_prefix() -> None:
    # Cut mid part 5 (inside wheel-3's dict) — the live failure shape.
    raw = _group_payload(_car_parts())
    truncated = raw[: raw.index('"wheel-3"')]
    payload = _parse_and_repair(truncated)
    assert payload is not None
    assert _part_names(payload) == ["body", "cabin", "wheel-1", "wheel-2"]
    op = payload_to_op(payload, speaker_id="p", utterance_id="u",
                       raw_text="a car with four wheels")
    assert op.geometry is not None and op.geometry.kind is ShapeKind.GROUP
    assert len(op.geometry.parts) == 4  # a 4-part car beats a NOOP


def test_seg2_truncated_inside_nth_part_recovers_n_minus_one() -> None:
    raw = _group_payload(_car_parts())
    # Truncating inside wheel-k keeps body+cabin+the k-1 complete wheels.
    for k in (1, 2, 3, 4):
        payload = _parse_and_repair(raw[: raw.index(f'"wheel-{k}"')])
        assert payload is not None, k
        assert len(_part_names(payload)) == 2 + (k - 1), k
    # Truncating inside the FIRST part leaves nothing complete: no fabricated
    # empty scene — parse fails so the corrective retry still runs.
    assert _parse_and_repair(raw[: raw.index('"body"')]) is None


def test_seg2_wellformed_payload_is_untouched() -> None:
    # No accidental part loss: a payload that already parses keeps every part.
    raw = _group_payload(_car_parts())
    payload = _parse_and_repair(raw)
    assert payload is not None
    assert _part_names(payload) == [
        "body", "cabin", "wheel-1", "wheel-2", "wheel-3", "wheel-4",
    ]


def test_seg2_truncated_solids_list_recovers_complete_solids() -> None:
    solids: list[dict[str, object]] = [
        {"shape": "sphere", "x": 5 + i * 25, "y": 0, "z": 20, "w": 20, "d": 20,
         "h": 20, "color": "#e5e7eb", "name": f"sphere-{i + 1}"}
        for i in range(4)
    ]
    raw = _solid_payload(solids)
    truncated = raw[: raw.index('"sphere-4"')]
    payload = _parse_and_repair(truncated)
    assert payload is not None
    assert payload.solids is not None
    assert [s.name for s in payload.solids] == ["sphere-1", "sphere-2", "sphere-3"]
    op = payload_to_op(payload, speaker_id="p", utterance_id="u",
                       raw_text="four spheres")
    assert op.geometry is not None and op.geometry.kind is ShapeKind.GROUP
    assert len(op.geometry.parts) >= 3


def test_seg2_truncated_inside_path_string_recovers_prior_parts() -> None:
    # The cut lands INSIDE a "d" string — string/escape scanning must not
    # mistake path data for structure.
    parts = _car_parts(2)
    parts.append({"kind": "path", "name": "outline", "x": 50, "y": 50, "width": 80,
                  "height": 40, "stroke": "#1f2937",
                  "d": "M 10 60 L 20 50 C 30 40 40 40 50 50 L 90 60", "parts": []})
    raw = _group_payload(parts)
    payload = _parse_and_repair(raw[: raw.index("C 30 40")])
    assert payload is not None
    assert _part_names(payload) == ["body", "cabin", "wheel-1", "wheel-2"]


def test_seg2_truncation_after_parts_keeps_all_parts() -> None:
    # Cut AFTER the geometry closed but before the payload's final members:
    # nothing inside parts is lost, the brackets just get closed.
    raw = _group_payload(_car_parts())
    payload = _parse_and_repair(raw[: raw.index(', "patch"')])
    assert payload is not None
    assert len(_part_names(payload)) == 6


def test_seg2_nested_group_parts_are_flattened() -> None:
    # Measured live ("a car with four wheels", 4096-token cap): the model nests
    # each wheel as a sub-GROUP of paths; the domain requires flat groups, so
    # the whole (salvaged) payload used to die on "no group inside parts".
    # The salvage pass now inlines sub-parts — coords are already absolute.
    parts = _car_parts(0)
    parts.append({
        "kind": "group", "name": "wheel-front", "x": 20, "y": 72, "width": 10,
        "height": 10, "stroke": "#1f2937",
        "parts": [
            {"kind": "circle", "name": "tyre", "x": 20, "y": 72, "width": 10,
             "height": 10, "stroke": "#1f2937", "parts": []},
            {"kind": "circle", "name": "hub", "x": 20, "y": 72, "width": 4,
             "height": 4, "stroke": "#1f2937", "parts": []},
        ],
    })
    raw = _group_payload(parts)
    payload = _parse_and_repair(raw)
    assert payload is not None
    assert _part_names(payload) == [
        "body", "cabin", "wheel-front-tyre", "wheel-front-hub",
    ]
    # And the same nesting inside a TRUNCATED payload still salvages.
    truncated = raw[: raw.index('"hub"')]
    payload2 = _parse_and_repair(truncated)
    assert payload2 is not None
    assert _part_names(payload2) == ["body", "cabin", "wheel-front-tyre"]


def test_seg2_salvage_is_conservative() -> None:
    # Not JSON at all → still None.
    assert _parse_and_repair("the model rambled instead of emitting JSON") is None
    # Root object CLOSED (trailing garbage, not truncation) → untouched → None.
    assert _parse_and_repair('{"op_type": "create"} trailing garbage') is None
    # Salvage that recovers no drawable content (geometry lost whole) → None,
    # so the corrective retry gets its chance instead of an empty CREATE.
    assert _parse_and_repair(
        '{"op_type": "create", "target_shape": "circle", "geometry": {"kind": "circ'
    ) is None


def test_seg1_invalid_target_shape_word_degrades_to_none() -> None:
    # ShapeKind has no "sphere"; the advisory target_shape must not sink the op.
    raw = _solid_payload(
        [{"shape": "sphere", "x": 50, "y": 0, "z": 50, "w": 40, "d": 40, "h": 40,
          "color": "#9ca3af", "name": "ball"}],
        target_shape="sphere",
    )
    payload = _parse_and_repair(raw)
    assert payload is not None
    assert payload.target_shape is None
    op = payload_to_op(payload, speaker_id="p", utterance_id="u", raw_text="a 3D sphere")
    assert op.geometry is not None and op.geometry.kind is ShapeKind.GROUP
