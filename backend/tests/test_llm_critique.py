"""Render→critique→repair pass for stage-C scenes (QUORUM_LLM_CRITIQUE).

After the LLM produces a CREATE scene, the classifier can score it with the
keyless adherence scorer against expectations parsed from the utterance; below
the threshold it fires ONE repair call carrying the scorer's failure notes and
keeps whichever attempt scores higher. These tests pin, without any network:

  * critique OFF (the default) → exactly one LLM call, first answer kept;
  * critique ON + low first score → exactly one extra call, better attempt wins;
  * critique ON + high first score → no extra call;
  * trivial single-part results and non-CREATE ops skip the pass;
  * an invalid/worse repair keeps the first attempt (degrade, never regress);
  * the repair prompt carries previous_attempt + critique notes + instruction;
  * Settings wiring: env-driven flags reach the classifier via from_settings.

Plus unit tests for the conservative utterance→Expectation parser the live
pass relies on (quorum/eval/expectations.py).
"""

from __future__ import annotations

import json

from quorum.config.settings import Backend, Settings
from quorum.domain.op import ClassifierContext, OpType
from quorum.eval.expectations import parse_expectation
from quorum.pipeline.llm import LLMClassifier

_CTX = ClassifierContext()

# An "exploded snowman": three disjoint gray islands, none red/blue — coherence
# 0 and both named colors absent, so it scores well below the 0.8 threshold.
_BAD_SNOWMAN = json.dumps(
    {
        "op_type": "create",
        "target_shape": "group",
        "confidence": 0.9,
        "label": "snowman",
        "geometry": {
            "kind": "group",
            "parts": [
                {"kind": "circle", "name": "body", "x": 10, "y": 10, "width": 8, "height": 8},
                {"kind": "circle", "name": "head", "x": 50, "y": 50, "width": 8, "height": 8},
                {"kind": "circle", "name": "arm", "x": 90, "y": 90, "width": 8, "height": 8},
            ],
        },
    }
)

# A coherent snowman: overlapping stack with a red scarf and a blue hat —
# colors present, one connected body → overall 1.0.
_GOOD_SNOWMAN = json.dumps(
    {
        "op_type": "create",
        "target_shape": "group",
        "confidence": 0.9,
        "label": "snowman",
        "geometry": {
            "kind": "group",
            "parts": [
                {"kind": "circle", "name": "body", "x": 50, "y": 70, "width": 30, "height": 30},
                {"kind": "circle", "name": "head", "x": 50, "y": 45, "width": 20, "height": 20},
                {
                    "kind": "rectangle",
                    "name": "scarf",
                    "x": 50,
                    "y": 56,
                    "width": 14,
                    "height": 5,
                    "fill": "#dc2626",
                    "fill_style": "solid",
                },
                {
                    "kind": "rectangle",
                    "name": "hat",
                    "x": 50,
                    "y": 32,
                    "width": 14,
                    "height": 6,
                    "fill": "#2563eb",
                    "fill_style": "solid",
                },
            ],
        },
    }
)

# A lone rectangle — valid but trivial (single part): never worth a critique call.
_TRIVIAL = json.dumps(
    {
        "op_type": "create",
        "target_shape": "rectangle",
        "confidence": 0.9,
        "geometry": {"kind": "rectangle", "x": 50, "y": 50, "width": 30, "height": 20},
    }
)

_UTTERANCE = "a snowman wearing a red scarf and a blue hat"


class ScriptedLLM(LLMClassifier):
    """Stage C with `_send` replaced by a reply script — counts calls and
    captures every message list so tests can assert the repair prompt."""

    def __init__(self, replies: list[str], **kwargs: object) -> None:
        super().__init__(backend=Backend.GROQ, model="m", api_key="k", **kwargs)  # type: ignore[arg-type]
        self._replies = list(replies)
        self.calls = 0
        self.sent: list[list[dict[str, str]]] = []

    async def _send(self, messages: list[dict[str, str]], *, tier: object = None) -> str:
        self.calls += 1
        self.sent.append(messages)
        self.last_tier = tier
        return self._replies.pop(0)


# --------------------------------------------------------------------------- #
# Call-count contract
# --------------------------------------------------------------------------- #
async def test_critique_off_makes_no_extra_call() -> None:
    clf = ScriptedLLM([_BAD_SNOWMAN])  # critique defaults OFF
    op = await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 1
    assert op.op_type is OpType.CREATE
    assert op.geometry is not None
    assert [p.name for p in op.geometry.parts] == ["body", "head", "arm"]  # first kept


async def test_critique_on_low_score_repairs_and_better_attempt_wins() -> None:
    clf = ScriptedLLM([_BAD_SNOWMAN, _GOOD_SNOWMAN], critique=True)
    op = await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 2  # exactly ONE extra call
    assert op.geometry is not None
    names = [p.name for p in op.geometry.parts]
    assert "scarf" in names and "hat" in names  # the repaired attempt won


async def test_critique_on_high_score_makes_no_extra_call() -> None:
    clf = ScriptedLLM([_GOOD_SNOWMAN], critique=True)
    op = await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 1  # already above threshold — no repair spent
    assert op.geometry is not None


async def test_trivial_single_part_result_skips_critique() -> None:
    clf = ScriptedLLM([_TRIVIAL], critique=True)
    op = await clf.classify("a rectangle please", speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 1
    assert op.geometry is not None


async def test_non_create_ops_skip_critique() -> None:
    noop = json.dumps({"op_type": "noop", "confidence": 0.1})
    clf = ScriptedLLM([noop], critique=True)
    op = await clf.classify("hmm interesting", speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 1
    assert op.op_type is OpType.NOOP


# --------------------------------------------------------------------------- #
# Degradation: the repair may never make the answer worse.
# --------------------------------------------------------------------------- #
async def test_invalid_repair_keeps_first_attempt() -> None:
    clf = ScriptedLLM([_BAD_SNOWMAN, "this is not json"], critique=True)
    op = await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 2
    assert op.geometry is not None
    assert [p.name for p in op.geometry.parts] == ["body", "head", "arm"]


async def test_equal_or_worse_repair_keeps_first_attempt() -> None:
    """Ties keep the FIRST attempt — the repair must be strictly better."""
    clf = ScriptedLLM([_BAD_SNOWMAN, _BAD_SNOWMAN], critique=True)
    op = await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 2
    assert op.geometry is not None
    assert [p.name for p in op.geometry.parts] == ["body", "head", "arm"]


async def test_failing_repair_call_degrades_to_first_attempt() -> None:
    class ExplodingSecondCall(ScriptedLLM):
        async def _send(self, messages: list[dict[str, str]], *, tier: object = None) -> str:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("boom")
            return self._replies.pop(0)

    clf = ExplodingSecondCall([_BAD_SNOWMAN], critique=True)
    op = await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 2
    assert op.op_type is OpType.CREATE  # never degraded to NOOP by the critique
    assert op.geometry is not None


# --------------------------------------------------------------------------- #
# The repair prompt itself.
# --------------------------------------------------------------------------- #
async def test_repair_prompt_carries_previous_attempt_and_critique() -> None:
    clf = ScriptedLLM([_BAD_SNOWMAN, _GOOD_SNOWMAN], critique=True)
    await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    repair_messages = clf.sent[1]
    assert repair_messages[0]["role"] == "system"  # same system prompt reused
    body = json.loads(repair_messages[-1]["content"])
    assert body["utterance"] == _UTTERANCE  # the original user payload, extended
    assert body["previous_attempt"]["geometry"]["parts"][0]["name"] == "body"
    assert any("color[red]" in note for note in body["critique"])
    assert any("coherence" in note for note in body["critique"])
    assert "Fix these issues" in body["instruction"]


async def test_threshold_is_configurable() -> None:
    """With the threshold at 0, even the exploded scene passes — no repair."""
    clf = ScriptedLLM([_BAD_SNOWMAN], critique=True, critique_threshold=0.0)
    await clf.classify(_UTTERANCE, speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.calls == 1


# --------------------------------------------------------------------------- #
# Settings wiring (12-factor: env → Settings → classifier).
# --------------------------------------------------------------------------- #
def test_settings_defaults_keep_critique_off() -> None:
    s = Settings(_env_file=None)
    assert s.llm_critique is False
    assert s.llm_critique_threshold == 0.8
    assert s.max_scene_parts == 60


def test_from_settings_passes_critique_flags() -> None:
    s = Settings(_env_file=None, llm_critique=True, llm_critique_threshold=0.6, max_scene_parts=80)
    clf = LLMClassifier.from_settings(s)
    assert clf._critique is True
    assert clf._critique_threshold == 0.6
    assert clf._max_parts == 80


# --------------------------------------------------------------------------- #
# Utterance → Expectation parser (conservative by design).
# --------------------------------------------------------------------------- #
def test_parse_expectation_colors_and_colored_in() -> None:
    e = parse_expectation("a simple car, colored in blue")
    assert e.colors == ("blue",)
    assert e.colored_in is True
    plain = parse_expectation("a blue circle")
    assert plain.colors == ("blue",)
    assert plain.colored_in is False


def test_parse_expectation_counts() -> None:
    e = parse_expectation("a house with a door and two windows")
    assert dict(e.counts) == {"window": 2}
    e2 = parse_expectation("a 3D engine with three pistons")
    assert dict(e2.counts) == {"piston": 3}
    assert e2.expect_3d is True
    # "three dimensional" is intent, not a countable part
    e3 = parse_expectation("a three dimensional cube")
    assert dict(e3.counts) == {}
    assert e3.expect_3d is True


def test_parse_expectation_relations() -> None:
    e = parse_expectation("a blue circle inside a red square")
    assert len(e.relations) == 1
    rel = e.relations[0]
    assert (rel.kind, rel.inner, rel.outer) == ("inside", "circle", "square")
    above = parse_expectation("a star above the house").relations
    assert above and above[0].kind == "above"


def test_parse_expectation_plain_utterance_is_mostly_empty() -> None:
    e = parse_expectation("a coffee mug with steam")
    assert not e.counts and not e.colors and not e.relations
    assert e.colored_in is False and e.expect_3d is False
