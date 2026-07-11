"""Multi-object / multi-sphere generation upgrades (2026-07-11).

Live weakness: "two spheres and a bigger sphere in the middle" came back as
flat 2D circles (never `solids`), the "bigger" sphere was SMALLER than its
neighbours, and one sphere sat half off-canvas. Root causes and the pins here:

  * the flat circle+equator 'sphere' TEMPLATE was fed to the LLM as a
    reference sketch, teaching it flat circles → reference suppression now
    keys on ``has_volumetric_intent`` (3D words OR sphere/hemisphere/orb);
  * the system prompt had no multi-object counting / relative-size /
    non-overlap guidance and no worked multi-sphere example → the MULTI-OBJECT
    rule + Example K (three spheres, middle genuinely bigger, gaps between
    world boxes);
  * the escalation tier (default OFF) routed on ``has_3d_intent`` only, so
    sphere prompts could never use the stronger-model lever → `_pick_tier`
    now routes on ``has_volumetric_intent``.
"""

from __future__ import annotations

import json
from itertools import pairwise

from quorum.config.settings import Backend
from quorum.domain.geometry import ShapeKind
from quorum.domain.op import ClassifierContext, OpType
from quorum.pipeline.intent import has_3d_intent, has_volumetric_intent
from quorum.pipeline.llm import _SYSTEM_PROMPT, LLMClassifier, _parse_and_repair, payload_to_op
from quorum.pipeline.renderer import SvgRenderer

_CTX = ClassifierContext()


# --------------------------------------------------------------------------- #
# has_volumetric_intent
# --------------------------------------------------------------------------- #
def test_volumetric_intent_fires_on_named_solids() -> None:
    assert has_volumetric_intent("two spheres and a bigger sphere in the middle")
    assert has_volumetric_intent("a sphere")
    assert has_volumetric_intent("a hemisphere on a box")
    assert has_volumetric_intent("a glowing orb")
    assert has_volumetric_intent("three spheres in a row")


def test_volumetric_intent_includes_plain_3d() -> None:
    assert has_volumetric_intent("an isometric cube")
    assert has_volumetric_intent("a 3d engine")


def test_volumetric_intent_negatives() -> None:
    # Flat shapes and ball-shaped DOODLES (baseball etc.) keep their references.
    assert not has_volumetric_intent("a red circle")
    assert not has_volumetric_intent("a baseball")
    assert not has_volumetric_intent("a snowman wearing a top hat")


def test_rules_stage_3d_signal_unchanged() -> None:
    """The rules stage's extrusion trigger must NOT widen: 'add a sphere to
    it' extruding the focused shape would be wrong. Only the LLM-side signal
    is wider."""
    assert not has_3d_intent("a sphere")
    assert not has_3d_intent("two spheres and a bigger sphere in the middle")


# --------------------------------------------------------------------------- #
# Reference-sketch suppression: flat 'sphere' template must not reach the LLM
# --------------------------------------------------------------------------- #
def test_sphere_prompt_suppresses_flat_reference_sketches() -> None:
    payload = json.loads(
        LLMClassifier._user_payload("two spheres and a bigger sphere in the middle", _CTX)
    )
    assert payload["context"]["reference_sketches"] is None, (
        "the flat circle+equator 'sphere' template must be suppressed — it "
        "teaches the model to emit flat circles instead of sphere solids"
    )


def test_flat_prompt_keeps_reference_sketches() -> None:
    payload = json.loads(LLMClassifier._user_payload("a snowman", _CTX))
    assert payload["context"]["reference_sketches"], (
        "non-volumetric prompts must keep their few-shot references"
    )


# --------------------------------------------------------------------------- #
# Escalation routing (default OFF — wiring unchanged, gate widened)
# --------------------------------------------------------------------------- #
def test_escalation_tier_serves_sphere_prompts() -> None:
    clf = LLMClassifier(
        backend=Backend.GROQ,
        model="fast-model",
        api_key="k",
        escalation_backend=Backend.OPENROUTER,
        escalation_model="strong-model",
        escalation_api_key="k2",
    )
    assert clf._pick_tier("two spheres and a bigger sphere in the middle").model == "strong-model"
    assert clf._pick_tier("an isometric cube").model == "strong-model"
    assert clf._pick_tier("a red circle").model == "fast-model"


def test_no_escalation_sphere_prompt_stays_fast() -> None:
    clf = LLMClassifier(backend=Backend.GROQ, model="fast-model", api_key="k")
    assert clf._pick_tier("two spheres and a bigger sphere in the middle") is clf._fast_tier


# --------------------------------------------------------------------------- #
# Prompt contract: the clauses the fix rides on must stay present
# --------------------------------------------------------------------------- #
def test_prompt_teaches_spheres_are_solids_not_circles() -> None:
    assert "ALWAYS a solid, NEVER a flat circle" in _SYSTEM_PROMPT
    assert "MULTI-OBJECT" in _SYSTEM_PROMPT
    assert "ALL IDENTICAL sizes" in _SYSTEM_PROMPT  # "three spheres in a row"
    assert "Example K" in _SYSTEM_PROMPT


def test_prompt_counts_arrangements_as_create() -> None:
    # "three spheres in a row" with a focus must not MODIFY the focused card.
    assert '"two spheres"' in _SYSTEM_PROMPT
    assert '"three boxes in a row"' in _SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# Example K semantics: parse it from the prompt, project it, check the claims
# --------------------------------------------------------------------------- #
def _example_k_payload() -> dict[str, object]:
    lines = [
        ln.strip()
        for ln in _SYSTEM_PROMPT.splitlines()
        if ln.strip().startswith('{"op_type"') and '"sphere-middle"' in ln
    ]
    assert len(lines) == 1, "Example K (three spheres) must appear exactly once"
    data: dict[str, object] = json.loads(lines[0])
    return data


def test_example_k_projects_bigger_middle_sphere() -> None:
    payload = _parse_and_repair(json.dumps(_example_k_payload()))
    assert payload is not None
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="three spheres")
    assert op.op_type is OpType.CREATE
    assert op.geometry is not None and op.geometry.kind is ShapeKind.GROUP

    bodies = {p.name: p for p in op.geometry.parts if p.name and p.name.endswith("-body")}
    assert {"sphere-left-body", "sphere-middle-body", "sphere-right-body"} <= set(bodies)
    mid = bodies["sphere-middle-body"].width
    left = bodies["sphere-left-body"].width
    right = bodies["sphere-right-body"].width
    assert left == right, "the two plain spheres are the same size"
    assert mid >= 1.4 * left, "'bigger' must be visibly bigger on screen (>= 1.4x)"

    # Renders like any other scene.
    svg = SvgRenderer().render(op.geometry)
    assert svg.startswith("<svg")


def test_example_k_world_boxes_do_not_overlap() -> None:
    data = _example_k_payload()
    solids = data["solids"]
    assert isinstance(solids, list) and len(solids) == 3
    spans = sorted((float(s["x"]), float(s["x"]) + float(s["w"])) for s in solids)
    for (_, end_a), (start_b, _) in pairwise(spans):
        assert end_a < start_b, "distinct spheres must have a gap along x"
