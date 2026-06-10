"""Intent classifier — Phase 0 stub + the seam for the Phase 1+ cascade.

Phase 0 has no audio/STT, so there is no text to classify yet. What we DO need is
the translation from a Phase-0 ``demo_op`` (a client asking for a known shape) and
from a plain typed utterance into a :class:`DesignOp`, so the rest of the loop
(engine -> render -> broadcast) is the real thing.

:func:`demo_op_to_designop` is the manual trigger. :class:`MockClassifier` is a
tiny rules-only classifier that already handles obvious shape/modifier/preference
words — it's the literal Phase-1 "rules" stage (cascade stage A), wired here so
the contract in :class:`~quorum.pipeline.interfaces.Classifier` is exercised from
day one. Phases will add embeddings (B) and the LLM (C) behind the same Protocol.
"""

from __future__ import annotations

import re

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.messages import DemoOpMessage
from quorum.domain.op import ClassifierContext, DesignOp, OpType

# Shape keyword table (cascade stage A — rules). Phase 1 grows this; Phase 4
# moves the long tail to embeddings/LLM.
_SHAPE_WORDS: dict[str, ShapeKind] = {
    "rectangle": ShapeKind.RECTANGLE,
    "rect": ShapeKind.RECTANGLE,
    "box": ShapeKind.RECTANGLE,
    "square": ShapeKind.RECTANGLE,
    "circle": ShapeKind.CIRCLE,
    "ellipse": ShapeKind.ELLIPSE,
    "oval": ShapeKind.ELLIPSE,
    "triangle": ShapeKind.TRIANGLE,
    "line": ShapeKind.LINE,
    "node": ShapeKind.NODE,
}

_MODIFIER_WORDS = {"fillet", "rounded", "bigger", "smaller"}

# Preference phrases -> signal strength (plan.md §10 taxonomy: "maybe" is weaker
# than "let's go with"). These feed FOCUS / affirmation.
_PREFERENCE_PHRASES: list[tuple[str, float]] = [
    ("let's go with", 1.0),
    ("lets go with", 1.0),
    ("i prefer", 0.9),
    ("go with the", 0.9),
    ("i like the", 0.7),
    ("prefer the", 0.8),
    ("actually the", 0.6),
    ("maybe the", 0.3),
    ("not the", -0.6),
]

_BRANCH_HINTS = ("instead", "how about", "what about", "variant", "version", "or a")


def demo_op_to_designop(msg: DemoOpMessage, utterance_id: str) -> DesignOp:
    """Phase 0: turn a hardcoded demo request into a real DesignOp."""
    geom = GeometrySpec(
        kind=msg.shape,
        corner_radius=12.0 if msg.fillet else 0.0,
    )
    if msg.focus:
        return DesignOp(
            op_type=OpType.FOCUS,
            target_node_id=msg.branch_from,
            preference_signal=1.0,
            speaker_id=msg.speaker_id,
            utterance_id=utterance_id,
            confidence=1.0,
            source_stage="mock",
        )
    op_type = OpType.BRANCH if msg.branch_from else OpType.CREATE
    return DesignOp(
        op_type=op_type,
        target_shape=msg.shape,
        target_node_id=msg.branch_from,
        modifiers=["fillet"] if msg.fillet else [],
        geometry=geom,
        speaker_id=msg.speaker_id,
        utterance_id=utterance_id,
        confidence=1.0,
        source_stage="mock",
    )


class MockClassifier:
    """Rules-only classifier (cascade stage A). Async to satisfy the Protocol."""

    async def classify(
        self,
        text: str,
        *,
        speaker_id: str,
        utterance_id: str,
        context: ClassifierContext,
    ) -> DesignOp:
        lowered = text.lower().strip()
        focus_node_id = context.focus_node_id

        # 1) preference signal -> FOCUS a node. If the utterance *names* a shape
        # ("go with the triangle"), resolve it against the candidate nodes;
        # otherwise re-affirm the current focus. (Harder relational references —
        # "the second one", "the one Bob suggested" — are stage-C/LLM territory.)
        for phrase, strength in _PREFERENCE_PHRASES:
            if phrase in lowered:
                named = self._find_shape(lowered)
                target = self._resolve_named(named, context) or focus_node_id
                return DesignOp(
                    op_type=OpType.FOCUS,
                    target_node_id=target,
                    preference_signal=strength,
                    speaker_id=speaker_id,
                    utterance_id=utterance_id,
                    confidence=0.8,
                    source_stage="rules",
                    raw_text=text,
                )

        # 2) shape word -> CREATE or BRANCH
        shape = self._find_shape(lowered)
        if shape is not None:
            modifiers = sorted(w for w in _MODIFIER_WORDS if w in lowered)
            radius = self._find_radius(lowered)
            if radius is not None:
                modifiers.append(f"radius:{radius}")
            is_branch = focus_node_id is not None and any(h in lowered for h in _BRANCH_HINTS)
            geom = GeometrySpec(
                kind=shape,
                corner_radius=12.0 if {"fillet", "rounded"} & set(modifiers) else 0.0,
            )
            return DesignOp(
                op_type=OpType.BRANCH if is_branch else OpType.CREATE,
                target_shape=shape,
                target_node_id=focus_node_id if is_branch else None,
                modifiers=modifiers,
                geometry=geom,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                confidence=0.85,
                source_stage="rules",
                raw_text=text,
            )

        # 3) bare modifier ("add a fillet") -> MODIFY the focus
        mods = sorted(w for w in _MODIFIER_WORDS if w in lowered)
        if mods and focus_node_id is not None:
            return DesignOp(
                op_type=OpType.MODIFY,
                target_node_id=focus_node_id,
                modifiers=mods,
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                confidence=0.7,
                source_stage="rules",
                raw_text=text,
            )

        # 4) nothing matched — low-confidence NOOP. Phase 4 escalates this to the
        # LLM instead of dropping it; the contract is unchanged.
        return DesignOp(
            op_type=OpType.NOOP,
            speaker_id=speaker_id,
            utterance_id=utterance_id,
            confidence=0.2,
            source_stage="rules",
            raw_text=text,
        )

    @staticmethod
    def _find_shape(text: str) -> ShapeKind | None:
        for word, kind in _SHAPE_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                return kind
        return None

    @staticmethod
    def _resolve_named(shape: ShapeKind | None, context: ClassifierContext) -> str | None:
        """Map a named shape to a candidate node id (newest match wins)."""
        if shape is None:
            return None
        match = [c.node_id for c in context.candidates if c.shape == shape]
        return match[-1] if match else None

    @staticmethod
    def _find_radius(text: str) -> float | None:
        m = re.search(r"radius\s*(?:of\s*)?(\d+(?:\.\d+)?)", text)
        return float(m.group(1)) if m else None
