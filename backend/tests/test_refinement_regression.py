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
from quorum.pipeline.llm import _normalize_solid_shape, _parse_and_repair, payload_to_op


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
