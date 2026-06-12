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
from quorum.domain.extrude import extrude
from quorum.domain.geometry import GeometrySpec, ShapeKind, apply_modifiers
from quorum.domain.messages import DemoOpMessage
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.domain.parts import apply_to_parts, resolve_parts
from quorum.domain.shapes import NAMED_SHAPES, named_shape
from quorum.observability.latency import stage_timer
from quorum.pipeline.intent import _3D_INTENT_RE
from quorum.pipeline.interfaces import Classifier

# The verb "extrude" also signals 3D intent but is not in the shared _3D_INTENT_RE
# (kept there for import-cycle reasons). Match it here locally.
_EXTRUDE_VERB_RE = re.compile(r"\bextrude\b", re.IGNORECASE)

# Determiners that introduce a definite reference (N1: this/that/my/our join "the").
_DEFINITE_DET_RE = re.compile(r"\b(?:the|this|that|my|our)\b")

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

# ---------------------------------------------------------------------------
# U2 — Undo / go-back meta-command (plan.md §14).
#
# These phrases are checked BEFORE all content branches and are EXEMPT from
# the hazy-confidence cap — the phrase IS the meaning; extra filler words
# must not reduce confidence.
#
# Word-boundary regex: fires only on bare go-back intent, NOT on content uses
# like "draw the back of the house" or "a clock going backwards".
# Group 1 captures the matched verb/phrase so the guard can decide quickly.
_UNDO_RE = re.compile(
    r"""
    \bundo\b                             # "undo"
    | \bgo\s+back\b                      # "go back" (bare)
    | \brevert\b                         # "revert"
    | \bscratch\s+that\b                 # "scratch that"
    | \bnever\s*mind\b                   # "never mind" / "nevermind"
    | \bzoom\s+(?:back\s+)?out\b         # "zoom out" / "zoom back out"
    | \b(?:go\s+back\s+to\s+the\s+)?
      previous\s+(?:one|version|situation|step|state)\b
                                         # "previous one/version/…"
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Phrases that ARE undo-like but contain a resolvable label/shape reference
# ("go back to the cat") — the guard below checks for these so we can fall
# through to existing FOCUS/label-resolution branches.  The guard fires only
# when a definite reference word (after "to the …") matches a candidate node.
_UNDO_TO_RE = re.compile(
    r"\bgo\s+back\s+to\s+(?:the|this|that)\b",
    re.IGNORECASE,
)

_BRANCH_HINTS = ("instead", "how about", "what about", "variant", "version", "or a", "another")
_PRUNE_RE = re.compile(r"\b(remove|delete|scrap|discard|prune)\b|get rid of")
_CONNECT_RE = re.compile(r"\b(connect|link|attach)\b")
_DEICTIC_RE = re.compile(r"\b(that|this|it)\b")  # "scrap that" -> the focus

# Words the rules vocabulary "explains": grammar/filler plus every word the
# tables above can act on. Anything else in an utterance ("funnel",
# "thrusters", "snowman") is meaning the rules stage CANNOT express — two or
# more such words and a matched op is emitted *below* the cascade threshold,
# so the LLM stage takes over while the rules result stays as the fallback.
_STOPWORDS = frozenset(
    """
    a an the and or but with of to for from into onto by at as is are was be
    it its that this these those there here one ones two three four five six
    seven eight nine ten i we you they he she us our my your me him her them
    want wants wanted like need needs maybe please okay ok lets let go going
    make makes making turn turned turning put puts putting draw draws drawing
    add adds added adding give gives have has had how what which who when
    where why side sides top bottom left right middle center over under above
    below beneath underneath inside within next then also just really very
    kind sort bit little big small new old again more less so if can could
    would should shall will do does did not no yes don dont up down out off
    front back around about instead version variant another get rid
    """.split()
)
_KNOWN_WORDS: frozenset[str] = frozenset(
    _STOPWORDS
    | set(_SHAPE_WORDS)
    | _MODIFIER_WORDS
    | set(_COLOR_WORDS)
    | {w for phrase, _ in _PREFERENCE_PHRASES for w in phrase.replace("'", " ").split()}
    | {"remove", "delete", "scrap", "discard", "prune", "connect", "link", "attach", "radius"}
    | {"undo", "revert", "scratch", "nevermind", "previous", "situation", "step", "state", "zoom"}
    | set(NAMED_SHAPES)          # R4: named-shape words are known vocabulary
    | {w + "s" for w in NAMED_SHAPES}   # R4: plurals ("hexagons", "arrows", …)
    | {"some"}  # common quantifier often paired with shape words
)

# Regex that matches any named-shape word (R4 named-geometry tier).
_NAMED_SHAPE_WORDS = sorted(NAMED_SHAPES, key=len, reverse=True)
_NAMED_SHAPE_RE = re.compile(
    rf"\b({'|'.join(map(re.escape, _NAMED_SHAPE_WORDS))})\b"
)
# Confidence for a matched-but-hazy op: below the default escalation threshold
# (0.55) so the cascade asks the LLM, yet non-zero so a dead LLM still falls
# back to this op instead of dropping the utterance.
_HAZY_CONFIDENCE = 0.5

# Geometric-relation vocabulary ("a line TANGENT to the circle"). One such word
# is enough to outweigh any shape-word match: the relation IS the meaning, and
# rules can only place shapes side-by-side — exact relations are LLM work.
_RELATION_RE = re.compile(
    r"\b(tangent\w*|tangential|perpendicular|parallel|concentric|inscribed|"
    r"circumscribed|intersect\w*|bisect\w*|touch\w*|midpoint|diagonal\w*|"
    r"degrees?|angle[ds]?|symmetri\w+|mirror\w*|align\w*|equidistant)\b"
)

# Spatial relations for composing a multi-shape SCENE in one node
# ("a circle with a square on top" is one idea, not two).
_STACK_RE = re.compile(r"\bon top\b|\babove\b|\bover\b")
_BELOW_RE = re.compile(r"\bbelow\b|\bunder(?:neath)?\b|\bbeneath\b")
_INSIDE_RE = re.compile(r"\binside\b|\bwithin\b|\bin the (?:middle|center)\b")

# Scene-extension intent ("add a red sphere inside"): an ADD verb or a
# containment/placement word while a focus exists means "compose INTO the
# current scene". Rules can only fold modifiers (branch 7) or open a separate
# card (branch 6) — extension is LLM work, so such a match goes out hazy.
_EXTEND_RE = re.compile(
    r"\b(add|put|place|insert|attach|stick|mount|embed)\b"
    r"|\b(inside|into|within|onto|on top of|in front of|behind)\b"
)


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

        # 0) U2 meta-command: undo / go-back — checked BEFORE all content
        # branches and EXEMPT from the hazy-confidence cap. The phrase IS the
        # meaning; extra filler words ("I don't really like it, never mind") must
        # not reduce confidence.
        #
        # GUARD: if the utterance contains "go back to the <X>" where <X>
        # resolves to a known label or shape, fall through so the existing
        # FOCUS/label-resolution branches handle it ("go back to the cat" is a
        # FOCUS, not an UNDO).
        if _UNDO_RE.search(lowered):
            # Run the guard: does this look like "go back to a specific node"?
            is_directed = False
            if _UNDO_TO_RE.search(lowered):
                # Check whether a label or shape word after "to the" resolves.
                if self._resolve_by_label(lowered, context) is not None:
                    is_directed = True
                elif self._resolve_named(self._find_shape(lowered), context) is not None:
                    is_directed = True
            if not is_directed:
                return op(op_type=OpType.UNDO, confidence=0.9)

        # 1) preference signal -> FOCUS (positive) or disaffirm (negative). If
        # the utterance *names* a shape ("go with the triangle"), resolve it
        # against the candidate nodes; otherwise re-affirm the current focus.
        # (Harder relational references — "the second one", "the one Bob
        # suggested" — are stage-C/LLM territory.)
        for phrase, strength in _PREFERENCE_PHRASES:
            if phrase in lowered:
                named = self._find_shape(lowered)
                target = self._resolve_named(named, context)
                # R3: also try label-based resolution ("go with the cat" when
                # no rule-shape word matches but a node is labelled "cat").
                if target is None:
                    target = self._resolve_by_label(lowered, context)
                target = target or focus_node_id
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
        # R3: count tokens that are explained by candidate labels — they reduce
        # the unexplained-word count so "i want the cube to be red" (where
        # "cube" resolves a node labelled "cuboid") doesn't inflate hazy.
        label_explained = self._label_explained_words(lowered, context)
        # ≥2 content words the rules can't express ("rocket … thrusters") means
        # a matched shape word is probably one PART of a richer intent; a single
        # geometric-relation word ("tangent", "perpendicular") means it outright.
        # Either way: emit the match below the cascade threshold so the LLM
        # stage handles it (and the rules op stays as the dead-LLM fallback).
        unexplained = [w for w in self._unexplained_words(lowered) if w not in label_explained]
        has_3d = (
            _3D_INTENT_RE.search(lowered) is not None
            or _EXTRUDE_VERB_RE.search(lowered) is not None
        )
        hazy = (
            len(unexplained) >= 2
            or _RELATION_RE.search(lowered) is not None
            or has_3d
            or (focus_node_id is not None and _EXTEND_RE.search(lowered) is not None)
        )

        # N4-A) 3D-intent + reference to an EXISTING node that IS the focus.
        # "make this hexagon three dimensional" / "make it 3d" / "extrude this".
        # Only fires when focus_geometry is available (we need the shape data).
        # "make the left eye 3d" (part-scoped) stays hazy — left/right qualifiers
        # together with 3D intent are out of scope in v1.
        if has_3d and focus_node_id is not None and context.focus_geometry is not None:
            # Resolve whether the utterance is aimed at the focus or at a
            # different named node.  A bare deictic ("it", "this", "that") with
            # no other named reference counts as targeting the focus.
            named_target = self._resolve_named(
                self._find_definite_shape(lowered), context
            )
            if named_target is None:
                named_target = self._resolve_by_label(
                    lowered, context, definite_only=True
                )
            target_is_focus = named_target is None or named_target == focus_node_id
            # Guard: if a part-qualifier word is present together with 3D intent,
            # punt to LLM (part-scoped 3D is out of scope in v1).
            has_part_qualifier = bool(
                re.search(r"\b(left|right|top|bottom|biggest|smallest|eye|nose|ear)\b", lowered)
            )
            if target_is_focus and not has_part_qualifier:
                extruded = extrude(context.focus_geometry)
                if extruded is not None:
                    return op(
                        op_type=OpType.MODIFY,
                        target_node_id=focus_node_id,
                        modifiers=modifiers,
                        geometry=extruded,
                        confidence=0.8,
                    )
                # extrude returned None (multi-part group or unsupported kind) →
                # fall through to hazy escalation below.

        # 4) modify a *named existing* node ("make the circle bigger/red").
        # N1: _find_definite_shape and _resolve_by_label now accept this/that/my/our
        # as definite determiners — "turn this hexagon pink" resolves correctly.
        # Branch ORDER guarantee: when modifiers exist AND a determiner+shape/label
        # word resolves to an existing node, this MODIFY branch wins over branch 6b
        # CREATE (the named-shape tier) — so "turn this hexagon pink" MODIFIES the
        # focused hexagon node, it does NOT create a new one.
        if modifiers:
            named = self._find_definite_shape(lowered)
            target = self._resolve_named(named, context)
            # R3 / N1 label fallback: "the cube" / "this hexagon" can match a
            # node labelled "cuboid" / "hexagon".
            if target is None:
                target = self._resolve_by_label(lowered, context, definite_only=True)
            if target is not None:
                return op(
                    op_type=OpType.MODIFY,
                    target_node_id=target,
                    modifiers=modifiers,
                    confidence=_HAZY_CONFIDENCE if hazy else 0.75,
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
                confidence=_HAZY_CONFIDENCE if hazy else 0.75,
            )

        # 6) shape word -> CREATE or BRANCH (branch when a variant is implied
        # and there is a focus to branch from).
        # N4-B NOTE: basic _SHAPE_WORDS (rectangle/box/circle/etc.) are NOT
        # given the extrusion CREATE freebie here.  The D1 contract (pinned in
        # test_d1_routing.py) requires that 3D-flagged basic-shape utterances
        # ("a 3D box", "a three dimensional circle") always emit hazy (0.5) so
        # the cascade can escalate to the template stage (which maps them to
        # isometric equivalents like "cuboid").  The extrusion freebie only fires
        # for NAMED_SHAPES (hexagon, star, etc.) in branch 6b below.
        shape = self._find_shape(lowered)
        if shape is not None:
            is_branch = focus_node_id is not None and any(h in lowered for h in _BRANCH_HINTS)
            geom = apply_modifiers(GeometrySpec(kind=shape), modifiers)
            # R3: stamp the matched spoken word as the label.
            m = _SHAPE_RE.search(lowered)
            shape_label = m.group(1) if m else None
            return op(
                op_type=OpType.BRANCH if is_branch else OpType.CREATE,
                target_shape=shape,
                target_node_id=focus_node_id if is_branch else None,
                modifiers=modifiers,
                geometry=geom,
                label=shape_label,
                confidence=_HAZY_CONFIDENCE if hazy else 0.85,
            )

        # 6b) R4 named-geometry tier: exact polygon/path generators for
        # math-named shapes (rhombus, hexagon, star, etc.) that have no
        # ShapeKind entry.  CREATE conf 0.85 (or hazy-capped as usual).
        # N4-B: same CREATE freebie as branch 6 for named shapes.
        nm = _NAMED_SHAPE_RE.search(lowered)
        if nm is not None:
            word = nm.group(1)
            spec = named_shape(word)
            if spec is not None:
                is_branch = focus_node_id is not None and any(h in lowered for h in _BRANCH_HINTS)
                # N4-B CREATE freebie: 3D + no existing ref → extrude named shape.
                if has_3d and not is_branch:
                    named_ref = self._resolve_named(
                        self._find_definite_shape(lowered), context
                    )
                    if named_ref is None:
                        named_ref = self._resolve_by_label(
                            lowered, context, definite_only=True
                        )
                    if named_ref is None:
                        extruded = extrude(spec)
                        if extruded is not None:
                            return op(
                                op_type=OpType.CREATE,
                                target_shape=ShapeKind.GROUP,
                                modifiers=modifiers,
                                geometry=apply_modifiers(extruded, modifiers),
                                label=word,
                                confidence=0.8,
                            )
                geom = apply_modifiers(spec, modifiers)
                return op(
                    op_type=OpType.BRANCH if is_branch else OpType.CREATE,
                    target_shape=spec.kind,
                    target_node_id=focus_node_id if is_branch else None,
                    modifiers=modifiers,
                    geometry=geom,
                    label=word,
                    confidence=_HAZY_CONFIDENCE if hazy else 0.85,
                )

        # 6c) N2 — part-scoped fast path: focus exists, focus_geometry is set,
        # modifiers are non-empty, and the utterance resolves ≥ 1 part names.
        # "make the left eye bigger" / "turn the eyes red".
        # This is placed BEFORE branch 7 so a resolvable part reference wins over
        # the bare-modifier whole-scene fold.
        if modifiers and focus_node_id is not None and context.focus_geometry is not None:
            part_names = resolve_parts(context.focus_geometry, lowered)
            if part_names:
                # Part tokens that matched count as explained — compute after
                # resolving so we subtract them from the unexplained set.
                patched = apply_to_parts(context.focus_geometry, part_names, modifiers)
                # modifiers are already BAKED into the geometry — the engine
                # folds op.modifiers onto replacement geometry, so passing them
                # through would double-apply (live: the whole mouse grew x1.3
                # and the eye x1.69 on "make one eye bigger").
                return op(
                    op_type=OpType.MODIFY,
                    target_node_id=focus_node_id,
                    modifiers=[],
                    geometry=patched,
                    confidence=0.75,
                )

        # 7) bare modifier ("make it bigger") -> MODIFY the focus. A color word
        # inside a rich utterance ("a snowman with a red scarf") is NOT a bare
        # modifier — the hazy cap sends those to the LLM stage. Here even ONE
        # unexplained word ("add a red SPHERE") means the utterance asks for
        # more than a modifier fold can express — that too is LLM work.
        #
        # N2 Fallback inversion: when the utterance contains a determiner
        # (the/this/that/my/our/one) followed within 2 words by an unexplained
        # word, the user referenced something we cannot resolve (e.g. "the nose",
        # "the whiskers").  Folding the modifier onto the whole scene would be
        # WRONG — e.g. "make the left eye bigger" scaling the whole mouse.
        # In this case emit NOOP conf 0.5 so the cascade escalates; if the LLM
        # is dead, NOTHING happens (never a wrong whole-scene MODIFY).
        # "make it bigger" (no determiner + unexplained word) remains fast 0.7.
        if modifiers and focus_node_id is not None:
            extra = [w for w in self._unexplained_words(lowered) if w not in label_explained]
            hazy_modify = hazy or len(extra) >= 1
            # N2 inversion: detect an unresolvable part-ish reference.
            has_unresolvable_ref = self._has_unresolvable_reference(lowered, context)
            if has_unresolvable_ref:
                # Emit NOOP so the cascade escalates; a dead LLM does nothing
                # rather than clobbering the whole scene with the wrong modifier.
                return op(op_type=OpType.NOOP, confidence=_HAZY_CONFIDENCE)
            return op(
                op_type=OpType.MODIFY,
                target_node_id=focus_node_id,
                modifiers=modifiers,
                confidence=_HAZY_CONFIDENCE if hazy_modify else 0.7,
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
    def _part(word: str, kind: ShapeKind, x: float, y: float, w: float, h: float) -> GeometrySpec:
        """One positioned primitive of a scene. 'square' keeps equal sides."""
        if word == "square":
            w = h = min(w, h)
        return GeometrySpec(kind=kind, x=x, y=y, width=w, height=h)

    def _compose_scene(self, text: str, mentions: list[tuple[int, str, ShapeKind]]) -> GeometrySpec:
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
    def _unexplained_words(text: str) -> list[str]:
        """Content words the rules vocabulary cannot account for."""
        return [t for t in re.findall(r"[a-z]+", text) if len(t) > 2 and t not in _KNOWN_WORDS]

    @staticmethod
    def _find_definite_shape(text: str) -> ShapeKind | None:
        """A shape referred to with a definite/demonstrative article.

        N1: accepts 'the', 'this', 'that', 'my', 'our' as definite determiners
        so "turn this hexagon pink" and "make that circle red" correctly resolve
        to MODIFY of an existing node rather than CREATEing a new one.
        """
        for word, kind in _SHAPE_WORDS.items():
            pat = rf"\b(?:the|this|that|my|our)\s+(?:\w+\s+){{0,2}}?{re.escape(word)}\b"
            if re.search(pat, text):
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

    @staticmethod
    def _label_match(word: str, label: str) -> bool:
        """Return True if *word* is a reasonable reference to *label*.

        Match rules (R3):
        - exact (case-insensitive)
        - plural-s: word == label + "s"  or  label == word + "s"
        - common-prefix ≥ 4 chars: "cube" ↔ "cuboid", "cat" ↔ "cats"
        """
        w, lab = word.lower(), label.lower()
        if w == lab:
            return True
        if w == lab + "s" or lab == w + "s":
            return True
        # Common-stem prefix (plan.md §12 R3): if the reference word is ≥ 4 chars
        # and the label is ≥ 4 chars, they are considered a match when they share
        # a common leading stem of at least min(len(shorter), 4) - 1 = 3 chars.
        # This deliberately catches "cube" ↔ "cuboid" (share "cub", 3 chars) while
        # blocking short accidental matches like "box" ↔ "boxing" (< 4 chars).
        if len(w) >= 4 and len(lab) >= 4:
            stem = min(len(w), len(lab), 4) - 1  # 3 chars when either is 4 chars
            if stem >= 3 and w[:stem] == lab[:stem]:
                return True
        return False

    @staticmethod
    def _resolve_by_label(
        text: str,
        context: ClassifierContext,
        *,
        definite_only: bool = False,
    ) -> str | None:
        """Resolve a word in *text* to a candidate node via its label.

        When *definite_only* is True, only words preceded by a definite
        article ("the") are considered — used for branch 4 (MODIFY) so
        that "a hexagon" doesn't accidentally target an existing hexagon
        node instead of creating a new one.

        Newest candidate wins (last match in the list).
        """
        if not context.candidates:
            return None
        candidates_with_labels = [c for c in context.candidates if c.label]
        if not candidates_with_labels:
            return None

        words = re.findall(r"[a-z]+", text.lower())
        best: str | None = None
        for word in words:
            if len(word) < 3:
                continue
            if definite_only:
                # N1: accept this/that/my/our as well as "the" for definite refs.
                # Matches _find_definite_shape style (up to 2 adjectives between).
                pattern = rf"\b(?:the|this|that|my|our)\s+(?:\w+\s+){{0,2}}?{re.escape(word)}\b"
                if not re.search(pattern, text.lower()):
                    continue
            for c in candidates_with_labels:
                assert c.label is not None  # narrowed above
                if RulesClassifier._label_match(word, c.label):
                    best = c.node_id  # newest wins: keep overwriting
        return best

    @staticmethod
    def _has_unresolvable_reference(text: str, context: ClassifierContext) -> bool:
        """Return True when the utterance contains a determiner followed by a word
        that cannot be resolved to a candidate label or a shape/known word.

        This is the N2 fallback-inversion guard: "the nose" when there is no
        'nose' part or label means the user referenced something we cannot find.
        Folding the modifier onto the whole scene would be wrong; better to NOOP
        and let the LLM handle it (or do nothing on quota death).

        Rule: a determiner (the/this/that/my/our/one) followed within 2 words by
        an unexplained word (not in _KNOWN_WORDS, not a candidate label) counts as
        an unresolvable reference.

        "make it bigger" (no determiner before "bigger") → returns False.
        "make the left eye bigger" (eye not in known words, preceded by "the") →
        returns True when no part or label resolves it.
        """
        # Build the label-explained set.
        label_expl = RulesClassifier._label_explained_words(text, context)

        lowered = text.lower()
        words = re.findall(r"[a-z]+", lowered)

        # Determiners that can precede a reference.
        determiners = frozenset({"the", "this", "that", "my", "our", "one"})

        for i, word in enumerate(words):
            if word not in determiners:
                continue
            # Look at the next 1-2 words after the determiner.
            for offset in (1, 2):
                j = i + offset
                if j >= len(words):
                    break
                candidate = words[j]
                if len(candidate) <= 2:
                    continue
                if candidate in _KNOWN_WORDS:
                    continue
                if candidate in label_expl:
                    continue
                # Found an unexplained word after a determiner → unresolvable ref.
                return True
        return False

    @staticmethod
    def _label_explained_words(text: str, context: ClassifierContext) -> frozenset[str]:
        """Return tokens in *text* that are EXPLAINED by matching a candidate label.

        These words are subtracted from the unexplained-word count before the
        hazy threshold check, so "i want the cube to be red" (where "cube"
        matches a node labelled "cuboid") doesn't inflate hazy.
        """
        if not context.candidates:
            return frozenset()
        candidates_with_labels = [c for c in context.candidates if c.label]
        if not candidates_with_labels:
            return frozenset()
        explained: set[str] = set()
        for word in re.findall(r"[a-z]+", text.lower()):
            if len(word) < 3:
                continue
            for c in candidates_with_labels:
                assert c.label is not None
                if RulesClassifier._label_match(word, c.label):
                    explained.add(word)
                    break
        return frozenset(explained)


# Backwards-compatible alias: Phase 0 called the rules stage "MockClassifier";
# it was always the real stage A, so it now carries its real name.
MockClassifier = RulesClassifier


class CascadeClassifier:
    """Stage A always; stage B (templates) when A is unsure; stage C only when
    both are (plan.md §3.3/§5).

    The escalation threshold is the latency/accuracy lever from RULES.md §6:
    higher = fewer LLM calls = lower median latency. The LLM's failure mode is
    a zero-confidence NOOP, in which case the fast result stands — a dead LLM
    degrades quality, never availability. The template stage is also free to
    decline (zero-confidence NOOP), in which case the LLM is asked.
    """

    def __init__(
        self,
        fast: Classifier,
        llm: Classifier,
        *,
        template: Classifier | None = None,
        threshold: float = 0.55,
    ) -> None:
        self.fast = fast
        self.llm = llm
        self.template = template
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
        if self.template is not None:
            template_op = await self.template.classify(
                text, speaker_id=speaker_id, utterance_id=utterance_id, context=context
            )
            if (
                template_op.op_type is not OpType.NOOP
                and template_op.confidence >= self.threshold
            ):
                return template_op  # known concept, answered for free
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
    from quorum.pipeline.templates import TemplateClassifier

    settings = get_settings()
    rules = RulesClassifier()
    if settings.llm_backend is Backend.MOCK:
        return rules
    return CascadeClassifier(
        rules,
        LLMClassifier.from_settings(settings),
        template=TemplateClassifier(),
        threshold=settings.llm_escalation_threshold,
    )
