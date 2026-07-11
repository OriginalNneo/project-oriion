"""Two-tier model routing (D4 part 2 — QUORUM_LLM_ESCALATION_*).

The fast tier serves every utterance; an optional escalation tier — a stronger
model — serves only ones flagged intricate/3D (the ``has_3d_intent`` gate the
rules stage already uses to force stage-C escalation). These tests pin the
routing without any network:

  * no escalation configured (the default) → every utterance uses the fast tier,
    so behavior is byte-identical to the single-tier pipeline;
  * escalation configured → 3D/intricate utterances route to the escalation
    model, flat shapes stay on the fast model;
  * one utterance uses ONE consistent tier across all its calls (initial +
    corrective retry + critique repair);
  * from_settings wiring: env-driven escalation flags reach the classifier and
    resolve the correct API key.
"""

from __future__ import annotations

import json

from quorum.config.settings import Backend, Settings
from quorum.domain.op import ClassifierContext
from quorum.pipeline.llm import LLMClassifier

_CTX = ClassifierContext()

# A minimal valid CREATE the parser accepts, so classify() runs to completion.
_CIRCLE = json.dumps(
    {
        "op_type": "create",
        "target_shape": "circle",
        "confidence": 0.9,
        "label": "circle",
        "geometry": {"kind": "circle", "x": 50, "y": 50, "width": 30, "height": 30},
    }
)


class TierSpyLLM(LLMClassifier):
    """Records the model of the tier every ``_send`` used — no network."""

    def __init__(self, replies: list[str], **kwargs: object) -> None:
        super().__init__(backend=Backend.GROQ, model="fast-model", api_key="k", **kwargs)  # type: ignore[arg-type]
        self._replies = list(replies)
        self.models_used: list[str] = []

    async def _send(self, messages: list[dict[str, str]], *, tier: object = None) -> str:
        from quorum.pipeline.llm import _Tier

        assert isinstance(tier, _Tier)
        self.models_used.append(tier.model)
        return self._replies.pop(0)


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
async def test_no_escalation_flat_shape_uses_fast_tier() -> None:
    clf = TierSpyLLM([_CIRCLE])
    await clf.classify("a red circle", speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.models_used == ["fast-model"]


async def test_no_escalation_3d_still_uses_fast_tier() -> None:
    # Without an escalation tier configured, even 3D prompts stay fast — the
    # default is byte-identical to the single-tier pipeline.
    clf = TierSpyLLM([_CIRCLE])
    await clf.classify("a 3D engine with pistons", speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.models_used == ["fast-model"]


async def test_escalation_routes_3d_to_strong_model() -> None:
    clf = TierSpyLLM(
        [_CIRCLE],
        escalation_backend=Backend.OPENROUTER,
        escalation_model="strong-model",
        escalation_api_key="k2",
    )
    await clf.classify("an isometric cube", speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.models_used == ["strong-model"]


async def test_escalation_keeps_flat_shape_on_fast_model() -> None:
    clf = TierSpyLLM(
        [_CIRCLE],
        escalation_backend=Backend.OPENROUTER,
        escalation_model="strong-model",
        escalation_api_key="k2",
    )
    await clf.classify("a red circle", speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.models_used == ["fast-model"]


async def test_corrective_retry_stays_on_the_same_tier() -> None:
    # First reply is irreparable JSON → classify() spends a corrective retry.
    # Both calls must use the SAME (escalation) tier for a 3D utterance.
    clf = TierSpyLLM(
        ["not json at all", _CIRCLE],
        escalation_backend=Backend.OPENROUTER,
        escalation_model="strong-model",
        escalation_api_key="k2",
    )
    await clf.classify("a 3D engine with pistons", speaker_id="a", utterance_id="u1", context=_CTX)
    assert clf.models_used == ["strong-model", "strong-model"]


# --------------------------------------------------------------------------- #
# Settings wiring
# --------------------------------------------------------------------------- #
def test_from_settings_no_escalation_by_default() -> None:
    clf = LLMClassifier.from_settings(Settings(llm_backend="mock"))
    assert clf._escalation_tier is None
    assert clf._pick_tier("a 3D engine with pistons") is clf._fast_tier


def test_from_settings_wires_escalation_tier_and_key() -> None:
    clf = LLMClassifier.from_settings(
        Settings(
            llm_backend="mock",
            llm_escalation_backend="openrouter",
            llm_escalation_model="strong-model",
            openrouter_api_key="secret-key",
        )
    )
    assert clf._escalation_tier is not None
    assert clf._escalation_tier.backend is Backend.OPENROUTER
    assert clf._escalation_tier.model == "strong-model"
    assert clf._escalation_tier.api_key == "secret-key"
    # The gate routes by intent.
    assert clf._pick_tier("a red circle") is clf._fast_tier
    assert clf._pick_tier("an isometric cube") is clf._escalation_tier
