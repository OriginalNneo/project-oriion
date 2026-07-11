"""Keyless regression guards for the drawing-quality refinement loop.

The live adherence battery (:mod:`quorum.eval.battery`) is the loop's fitness
signal but needs a network + key, so it cannot run in the gate. These tests lock
the DETERMINISTIC facts each accepted refinement relies on — the "code disposes"
half of every fix — so a later segment cannot silently undo a gain. They are
pure/keyless and run in ``uv run pytest -q``.

Add one guard per accepted segment (name it ``test_seg<N>_...``).
"""

from __future__ import annotations

from quorum.domain.geometry import ShapeKind
from quorum.domain.isometric import Solid, project_solids
from quorum.eval.adherence import NAMED_COLORS
from quorum.eval.battery import ALL, HELDOUT, SETS, TUNING


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
