"""Intent classifier — the rules stage (cascade stage A) + Phase-0 demo translator.

This is the literal "rules" stage of the plan.md §3.3 cascade, wired from day
one so the :class:`~quorum.pipeline.interfaces.Classifier` contract is exercised
by the real loop. It must catch the obvious majority cheaply:

  * create/branch  — "a rectangle", "how about a triangle instead"
  * modify         — "make it bigger", "make the circle red" (named target)
  * focus/affirm   — "let's go with the triangle", "not the triangle" (negative)
  * prune          — "scrap the circle", "get rid of that"
  * connect        — "connect the box to the circle" (workflow mode)

Anything it can't handle returns a low-confidence NOOP; Phase 4 escalates those
to the embedding/LLM stages behind the same Protocol instead of dropping them.

:func:`demo_op_to_designop` is the Phase-0 manual trigger (a client asking for a
known shape) so the tail of the loop is testable without any speech at all.
"""

from __future__ import annotations

import re
from typing import Any

from quorum.config.settings import Backend
from quorum.domain.geometry import GeometrySpec, ShapeKind, apply_modifiers
from quorum.domain.messages import DemoOpMessage
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.observability.latency import stage_timer
from quorum.pipeline.interfaces import Classifier

# Shape keyword table. Phase 4 moves the long tail to embeddings/LLM.
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
_SHAPE_RE = re.compile(rf"\b({'|'.join(map(re.escape, _SHAPE_WORDS))})\b")

_MODIFIER_WORDS = {"fillet", "rounded", "bigger", "smaller"}

# Spoken colors -> stroke. A "color:<hex>" modifier flows through the shared
# domain apply_modifiers() into the spec, so both renderers honour it.
_COLOR_WORDS: dict[str, str] = {
    "red": "#dc2626",
    "blue": "#2563eb",
    "green": "#16a34a",
    "orange": "#ea580c",
    "purple": "#9333ea",
    "yellow": "#ca8a04",
    "pink": "#db2777",
    "black": "#1f2937",
}

# Preference phrases -> signal strength (plan.md §10 taxonomy: "maybe" is weaker
# than "let's go with"). Negative strengths DISAFFIRM (the engine lowers the
# target's score instead of focusing it). First match wins, so the stronger,
# more specific phrases come first.
_PREFERENCE_PHRASES: list[tuple[str, float]] = [
    ("let's go with", 1.0),
    ("lets go with", 1.0),
    ("i prefer", 0.9),
    ("go with the", 0.9),
    ("prefer the", 0.8),
    ("i like the", 0.7),
    ("actually the", 0.6),
    ("maybe the", 0.3),
    ("not the", -0.6),
    ("don't like the", -0.6),
    ("dont like the", -0.6),
]

_BRANCH_HINTS = ("instead", "how about", "what about", "variant", "version", "or a", "another")
_PRUNE_RE = re.compile(r"\b(remove|delete|scrap|discard|prune)\b|get rid of")
_CONNECT_RE = re.compile(r"\b(connect|link|attach)\b")
_DEICTIC_RE = re.compile(r"\b(that|this|it)\b")  # "scrap that" -> the focus

# Spatial relations for composing a multi-shape SCENE in one node
# ("a circle with a square on top" is one idea, not two).
_STACK_RE = re.compile(r"\bon top\b|\babove\b|\bover\b")
_BELOW_RE = re.compile(r"\bbelow\b|\bunder(?:neath)?\b|\bbeneath\b")
_INSIDE_RE = re.compile(r"\binside\b|\bwithin\b|\bin the (?:middle|center)\b")


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


class RulesClassifier:
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

        def op(**kwargs: Any) -> DesignOp:
            return DesignOp(
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                source_stage="rules",
                raw_text=text,
                **kwargs,
            )

        # 1) preference signal -> FOCUS (positive) or disaffirm (negative). If
        # the utterance *names* a shape ("go with the triangle"), resolve it
        # against the candidate nodes; otherwise re-affirm the current focus.
        # (Harder relational references — "the second one", "the one Bob
        # suggested" — are stage-C/LLM territory.)
        for phrase, strength in _PREFERENCE_PHRASES:
            if phrase in lowered:
                named = self._find_shape(lowered)
                target = self._resolve_named(named, context) or focus_node_id
                return op(
                    op_type=OpType.FOCUS,
                    target_node_id=target,
                    preference_signal=strength,
                    confidence=0.8,
                )

        # 2) connect ("connect the box to the circle") — needs two named nodes.
        if _CONNECT_RE.search(lowered):
            shapes = self._find_shapes(lowered)
            resolved: list[str] = []
            for kind in shapes:
                nid = self._resolve_named(kind, context)
                if nid is not None and nid not in resolved:
                    resolved.append(nid)
            if len(resolved) >= 2:
                return op(
                    op_type=OpType.CONNECT,
                    target_node_id=resolved[0],
                    relation_to_node=resolved[1],
                    confidence=0.75,
                )

        # 3) prune ("scrap the circle", "get rid of that").
        if _PRUNE_RE.search(lowered):
            named = self._find_shape(lowered)
            target = self._resolve_named(named, context)
            if target is None and _DEICTIC_RE.search(lowered):
                target = focus_node_id
            if target is not None:
                return op(op_type=OpType.PRUNE, target_node_id=target, confidence=0.8)

        modifiers = self._find_modifiers(lowered)

        # 4) modify a *named existing* node ("make the circle bigger/red").
        # The definite article is the discriminator: "the circle" refers to an
        # existing node; "a circle" asks for a new one.
        if modifiers:
            named = self._find_definite_shape(lowered)
            target = self._resolve_named(named, context)
            if target is not None:
                return op(
                    op_type=OpType.MODIFY,
                    target_node_id=target,
                    modifiers=modifiers,
                    confidence=0.75,
                )

        # 5) two or more shapes -> compose ONE scene node (group geometry).
        # "a circle with a square on top" must not collapse to a single shape.
        mentions = self._find_shape_mentions(lowered)
        if len(mentions) >= 2 and not _CONNECT_RE.search(lowered):
            scene = self._compose_scene(lowered, mentions)
            is_branch = focus_node_id is not None and any(h in lowered for h in _BRANCH_HINTS)
            return op(
                op_type=OpType.BRANCH if is_branch else OpType.CREATE,
                target_shape=ShapeKind.GROUP,
                target_node_id=focus_node_id if is_branch else None,
                modifiers=modifiers,
                geometry=apply_modifiers(scene, modifiers),
                confidence=0.75,
            )

        # 6) shape word -> CREATE or BRANCH (branch when a variant is implied
        # and there is a focus to branch from).
        shape = self._find_shape(lowered)
        if shape is not None:
            is_branch = focus_node_id is not None and any(h in lowered for h in _BRANCH_HINTS)
            geom = apply_modifiers(GeometrySpec(kind=shape), modifiers)
            return op(
                op_type=OpType.BRANCH if is_branch else OpType.CREATE,
                target_shape=shape,
                target_node_id=focus_node_id if is_branch else None,
                modifiers=modifiers,
                geometry=geom,
                confidence=0.85,
            )

        # 7) bare modifier ("make it bigger") -> MODIFY the focus
        if modifiers and focus_node_id is not None:
            return op(
                op_type=OpType.MODIFY,
                target_node_id=focus_node_id,
                modifiers=modifiers,
                confidence=0.7,
            )

        # 8) nothing matched — low-confidence NOOP. The cascade escalates this
        # to the LLM stage when one is configured; the contract is unchanged.
        return op(op_type=OpType.NOOP, confidence=0.2)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _find_shape(text: str) -> ShapeKind | None:
        m = _SHAPE_RE.search(text)
        return _SHAPE_WORDS[m.group(1)] if m else None

    @staticmethod
    def _find_shapes(text: str) -> list[ShapeKind]:
        """All shape mentions, in spoken order (for CONNECT's two endpoints)."""
        return [_SHAPE_WORDS[m.group(1)] for m in _SHAPE_RE.finditer(text)]

    @staticmethod
    def _find_shape_mentions(text: str) -> list[tuple[int, str, ShapeKind]]:
        """All shape mentions with their text position and the spoken word."""
        return [(m.start(), m.group(1), _SHAPE_WORDS[m.group(1)]) for m in _SHAPE_RE.finditer(text)]

    @staticmethod
    def _part(
        word: str, kind: ShapeKind, x: float, y: float, w: float, h: float
    ) -> GeometrySpec:
        """One positioned primitive of a scene. 'square' keeps equal sides."""
        if word == "square":
            w = h = min(w, h)
        return GeometrySpec(kind=kind, x=x, y=y, width=w, height=h)

    def _compose_scene(
        self, text: str, mentions: list[tuple[int, str, ShapeKind]]
    ) -> GeometrySpec:
        """Compose 2+ shape mentions into one GROUP scene.

        Rules-level spatial vocabulary only: stacked ("on top of"/"above"),
        "below"/"under", "inside", else side-by-side in spoken order. Richer
        arrangements are the LLM stage's job (it emits the same group spec).
        """
        stacked = _STACK_RE.search(text)
        below = _BELOW_RE.search(text)
        inside = _INSIDE_RE.search(text)

        def nearest_before(pos: int) -> int:
            """Index of the mention closest before `pos` (else first mention)."""
            best = 0
            for i, (start, _, _) in enumerate(mentions):
                if start < pos:
                    best = i
            return best

        if len(mentions) == 2 and (stacked or below or inside):
            a, b = mentions
            if inside:
                # "a circle inside the square" — the shape named before the
                # preposition is the inner one.
                inner, outer = (a, b) if nearest_before(inside.start()) == 0 else (b, a)
                return GeometrySpec(
                    kind=ShapeKind.GROUP,
                    parts=[
                        self._part(outer[1], outer[2], 50, 52, 46, 36),
                        self._part(inner[1], inner[2], 50, 52, 16, 13),
                    ],
                )
            if stacked:
                # "a square on top of a circle" / "a circle with a square on
                # top" — the shape named just before the preposition goes on top.
                top, bottom = (a, b) if nearest_before(stacked.start()) == 0 else (b, a)
            else:
                assert below is not None
                # "a square below the circle" — named-before goes to the bottom.
                bottom, top = (a, b) if nearest_before(below.start()) == 0 else (b, a)
            return GeometrySpec(
                kind=ShapeKind.GROUP,
                parts=[
                    self._part(bottom[1], bottom[2], 50, 66, 38, 28),
                    self._part(top[1], top[2], 50, 32, 26, 22),
                ],
            )

        # Default: spread left-to-right in spoken order ("a circle and a square").
        n = len(mentions)
        xs = [20 + (60 * i) / max(1, n - 1) for i in range(n)] if n > 1 else [50.0]
        return GeometrySpec(
            kind=ShapeKind.GROUP,
            parts=[
                self._part(word, kind, xs[i], 52, 26, 22)
                for i, (_, word, kind) in enumerate(mentions)
            ],
        )

    @staticmethod
    def _find_definite_shape(text: str) -> ShapeKind | None:
        """A shape referred to with a definite article: 'the (red) circle'."""
        for word, kind in _SHAPE_WORDS.items():
            if re.search(rf"\bthe\s+(?:\w+\s+){{0,2}}?{re.escape(word)}\b", text):
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
    def _find_modifiers(text: str) -> list[str]:
        """Collect size/fillet/radius/color modifiers as canonical strings."""
        mods = sorted(w for w in _MODIFIER_WORDS if re.search(rf"\b{w}\b", text))
        m = re.search(r"radius\s*(?:of\s*)?(\d+(?:\.\d+)?)", text)
        if m:
            mods.append(f"radius:{float(m.group(1))}")
        for word, hex_color in _COLOR_WORDS.items():
            if re.search(rf"\b{word}\b", text):
                mods.append(f"color:{hex_color}")
                break
        return mods


# Backwards-compatible alias: Phase 0 called the rules stage "MockClassifier";
# it was always the real stage A, so it now carries its real name.
MockClassifier = RulesClassifier


class CascadeClassifier:
    """Stage A always; stage C only when A is unsure (plan.md §3.3/§5).

    The escalation threshold is the latency/accuracy lever from RULES.md §6:
    higher = fewer LLM calls = lower median latency. The LLM's failure mode is
    a zero-confidence NOOP, in which case the fast result stands — a dead LLM
    degrades quality, never availability.
    """

    def __init__(self, fast: Classifier, llm: Classifier, *, threshold: float = 0.55) -> None:
        self.fast = fast
        self.llm = llm
        self.threshold = threshold

    async def classify(
        self,
        text: str,
        *,
        speaker_id: str,
        utterance_id: str,
        context: ClassifierContext,
    ) -> DesignOp:
        fast_op = await self.fast.classify(
            text, speaker_id=speaker_id, utterance_id=utterance_id, context=context
        )
        if fast_op.op_type is not OpType.NOOP and fast_op.confidence >= self.threshold:
            return fast_op
        async with stage_timer("classify_llm", utterance_id=utterance_id):
            llm_op = await self.llm.classify(
                text, speaker_id=speaker_id, utterance_id=utterance_id, context=context
            )
        if llm_op.op_type is OpType.NOOP and llm_op.confidence == 0.0:
            return fast_op  # LLM failed/unsure — the fast path stands
        return llm_op


def build_classifier() -> Classifier:
    """Config-driven factory (RULES.md §5: stages chosen by env, never hardcoded).

    ``QUORUM_LLM_BACKEND=mock`` (default) -> rules only.
    ``groq``/``local``                    -> rules + LLM cascade.
    """
    from quorum.config import get_settings
    from quorum.pipeline.llm import LLMClassifier

    settings = get_settings()
    rules = RulesClassifier()
    if settings.llm_backend is Backend.MOCK:
        return rules
    return CascadeClassifier(
        rules,
        LLMClassifier.from_settings(settings),
        threshold=settings.llm_escalation_threshold,
    )
