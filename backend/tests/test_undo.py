"""U1 + U2 tests: voice undo / go-back (plan.md §14).

Covers:
  - Classifier (U2): each vocabulary phrasing → UNDO @ 0.9, guard cases,
    non-firing content phrases, long natural sentences.
  - Engine (U1): focus moves to parent; abandoned child stays ACTIVE; root
    no-op; repeated UNDO walks a chain; diff upserts both ends.
  - Integration: undo then a new MODIFY creates a SIBLING, not a grandchild.
  - Replay: from_events reproduces the same focus after an undo.
"""

from __future__ import annotations

import pytest

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, NodeRef, OpType
from quorum.domain.tree import NodeStatus
from quorum.engine import DesignStateEngine
from quorum.engine.clock import FixedClock
from quorum.pipeline.classify import RulesClassifier

# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                           #
# --------------------------------------------------------------------------- #


@pytest.fixture
def clf() -> RulesClassifier:
    return RulesClassifier()


def _engine() -> DesignStateEngine:
    return DesignStateEngine(room="t", clock=FixedClock())


def _no_ctx() -> ClassifierContext:
    return ClassifierContext(focus_node_id=None, candidates=[])


def _ctx(focus: str | None = None, candidates: list[NodeRef] | None = None) -> ClassifierContext:
    return ClassifierContext(focus_node_id=focus, candidates=candidates or [])


async def _classify(
    clf: RulesClassifier,
    text: str,
    focus: str | None = None,
    candidates: list[NodeRef] | None = None,
) -> DesignOp:
    ctx = _ctx(focus=focus, candidates=candidates)
    return await clf.classify(text, speaker_id="alice", utterance_id="u1", context=ctx)


def _create_op(
    shape: ShapeKind = ShapeKind.RECTANGLE,
    label: str | None = None,
    utterance_id: str = "u1",
) -> DesignOp:
    return DesignOp(
        op_type=OpType.CREATE,
        target_shape=shape,
        geometry=GeometrySpec(kind=shape),
        label=label,
        speaker_id="alice",
        utterance_id=utterance_id,
        confidence=1.0,
    )


def _modify_op(
    target_id: str,
    modifiers: list[str] | None = None,
    utterance_id: str = "u2",
) -> DesignOp:
    return DesignOp(
        op_type=OpType.MODIFY,
        target_node_id=target_id,
        modifiers=modifiers or ["bigger"],
        speaker_id="alice",
        utterance_id=utterance_id,
        confidence=1.0,
    )


def _undo_op(utterance_id: str = "ux") -> DesignOp:
    return DesignOp(
        op_type=OpType.UNDO,
        speaker_id="alice",
        utterance_id=utterance_id,
        confidence=0.9,
    )


# =========================================================================== #
# Part 1: Classifier (U2)                                                      #
# =========================================================================== #


class TestUndoClassifier:
    """Vocabulary phrasing → UNDO @ 0.9; guard / non-firing cases."""

    @pytest.mark.parametrize(
        "text",
        [
            "undo",
            "go back",
            "revert",
            "scratch that",
            "never mind",
            "nevermind",
            "zoom out",
            "zoom back out",
            "previous one",
            "previous version",
            "previous situation",
            "previous step",
            "previous state",
            "go back to the previous situation",
            "go back to the previous one",
            "go back to the previous step",
        ],
    )
    async def test_undo_vocabulary_fires(self, clf: RulesClassifier, text: str) -> None:
        op = await _classify(clf, text)
        assert op.op_type == OpType.UNDO, f"expected UNDO for '{text}', got {op.op_type}"
        assert op.confidence == 0.9

    async def test_undo_source_is_rules(self, clf: RulesClassifier) -> None:
        op = await _classify(clf, "never mind")
        assert op.source_stage == "rules"

    async def test_long_natural_sentence_is_undo(self, clf: RulesClassifier) -> None:
        """Extra filler words must NOT reduce confidence or suppress UNDO."""
        op = await _classify(
            clf, "I don't really like it, never mind, go back to the previous situation"
        )
        assert op.op_type == OpType.UNDO
        assert op.confidence == 0.9

    async def test_undo_fires_before_content_branch(self, clf: RulesClassifier) -> None:
        """UNDO must be checked before shape/modifier branches."""
        # "undo" alone, focus exists — must still be UNDO, not NOOP or MODIFY.
        op = await _classify(clf, "undo", focus="n1")
        assert op.op_type == OpType.UNDO

    # ----------------------------------------------------------------------- #
    # Guard: "go back to the <label>" → NOT UNDO, fall through to FOCUS       #
    # ----------------------------------------------------------------------- #

    async def test_go_back_to_label_is_not_undo(self, clf: RulesClassifier) -> None:
        """go back to the cat → FOCUS/label-resolution, not UNDO."""
        candidates = [NodeRef(node_id="n1", label="cat", is_focus=False)]
        op = await _classify(clf, "go back to the cat", focus="n2", candidates=candidates)
        assert op.op_type != OpType.UNDO, (
            "go back to a resolvable label must NOT emit UNDO"
        )

    async def test_go_back_to_shape_is_not_undo(self, clf: RulesClassifier) -> None:
        """go back to the circle → FOCUS, not UNDO."""
        candidates = [NodeRef(node_id="n3", shape=ShapeKind.CIRCLE, is_focus=False)]
        op = await _classify(clf, "go back to the circle", focus="n2", candidates=candidates)
        assert op.op_type != OpType.UNDO

    async def test_go_back_to_hexagon_with_no_candidate_is_undo(
        self, clf: RulesClassifier
    ) -> None:
        """go back to the hexagon when there is no hexagon node → UNDO fires."""
        # No candidates at all — the guard finds nothing to resolve.
        op = await _classify(clf, "go back to the hexagon")
        assert op.op_type == OpType.UNDO

    # ----------------------------------------------------------------------- #
    # Non-firing content phrases — undo must NOT fire on these                 #
    # ----------------------------------------------------------------------- #

    @pytest.mark.parametrize(
        "text",
        [
            "draw the back of the house",
            "a clock going backwards",
            "the previous design had a window",
            "go forward with this idea",
            "step it up",
        ],
    )
    async def test_content_phrase_does_not_fire_undo(
        self, clf: RulesClassifier, text: str
    ) -> None:
        op = await _classify(clf, text)
        assert op.op_type != OpType.UNDO, (
            f"content phrase '{text}' must NOT fire UNDO, got {op.op_type}"
        )


# =========================================================================== #
# Part 2: Engine (U1)                                                          #
# =========================================================================== #


class TestUndoEngine:
    """UNDO op behaviour inside DesignStateEngine."""

    def test_undo_moves_focus_to_parent(self) -> None:
        """Core invariant: UNDO with a parent → focus moves to that parent."""
        eng = _engine()
        parent_id = eng.apply(_create_op()).upserted[0].id
        child_id = eng.apply(_modify_op(parent_id, utterance_id="u2")).upserted[0].id
        assert eng.focus_node_id == child_id

        eng.apply(_undo_op())

        assert eng.focus_node_id == parent_id

    def test_undo_abandoned_child_stays_active(self) -> None:
        """The node we 'left' must stay ACTIVE (not pruned, not focused)."""
        eng = _engine()
        parent_id = eng.apply(_create_op()).upserted[0].id
        child_id = eng.apply(_modify_op(parent_id, utterance_id="u2")).upserted[0].id

        eng.apply(_undo_op())

        snap = {n.id: n for n in eng.snapshot().nodes}
        assert snap[child_id].status == NodeStatus.ACTIVE, (
            "abandoned child must be ACTIVE, not pruned"
        )

    def test_undo_at_root_is_noop_no_event(self) -> None:
        """At the root (no parent), UNDO must be a no-op: no new event."""
        eng = _engine()
        root_id = eng.apply(_create_op()).upserted[0].id
        events_before = len(eng.events())

        eng.apply(_undo_op())

        # Still focused on root.
        assert eng.focus_node_id == root_id
        # No FOCUS_CHANGED event was appended (events_before counts all events
        # including the initial CREATE + FOCUS_CHANGED from _create).
        assert len(eng.events()) == events_before, (
            "UNDO at root must append NO new events"
        )

    def test_undo_at_root_returns_current_view(self) -> None:
        """At root the diff must still be valid (non-empty is fine; empty is fine
        too as long as focus stays the same). The key invariant is no crash."""
        eng = _engine()
        eng.apply(_create_op())
        diff = eng.apply(_undo_op())
        assert diff is not None
        assert diff.focus_node_id == eng.focus_node_id

    def test_repeated_undo_walks_chain(self) -> None:
        """A → B → C: two UNDOs bring focus back from C to A, one step at a time."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        b_id = eng.apply(_modify_op(a_id, utterance_id="u2")).upserted[0].id
        c_id = eng.apply(_modify_op(b_id, utterance_id="u3")).upserted[0].id
        assert eng.focus_node_id == c_id

        eng.apply(_undo_op(utterance_id="ux1"))
        assert eng.focus_node_id == b_id

        eng.apply(_undo_op(utterance_id="ux2"))
        assert eng.focus_node_id == a_id

    def test_undo_diff_upserts_both_ends(self) -> None:
        """StateDiff from an UNDO must contain both the old focus and the new focus."""
        eng = _engine()
        parent_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        child_id = eng.apply(_modify_op(parent_id, utterance_id="u2")).upserted[0].id

        diff = eng.apply(_undo_op())

        ids_in_diff = {v.id for v in diff.upserted}
        assert child_id in ids_in_diff, "old focus (child) must be in the diff"
        assert parent_id in ids_in_diff, "new focus (parent) must be in the diff"

    def test_undo_parent_becomes_focused(self) -> None:
        """After UNDO the parent's status must be FOCUSED."""
        eng = _engine()
        parent_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        eng.apply(_modify_op(parent_id, utterance_id="u2"))

        eng.apply(_undo_op())

        snap = {n.id: n for n in eng.snapshot().nodes}
        assert snap[parent_id].status == NodeStatus.FOCUSED


# =========================================================================== #
# Part 3: Integration — undo then modify creates a SIBLING                    #
# =========================================================================== #


class TestUndoIntegration:
    """classifier + engine: the §14 user story end to end."""

    def test_undo_then_modify_creates_sibling(self) -> None:
        """User flow: create hexagon → turn pink (child A) → undo → make blue
        → NEW child B must be a sibling of A (both children of the hexagon root),
        NOT a child of A.
        """
        eng = _engine()

        # 1) Create the root hexagon.
        root_id = eng.apply(_create_op(ShapeKind.RECTANGLE, label="hexagon")).upserted[0].id
        # 2) Turn it pink: creates child A.
        child_a_id = eng.apply(
            _modify_op(root_id, modifiers=["color:#db2777"], utterance_id="u2")
        ).upserted[0].id
        assert eng.focus_node_id == child_a_id

        # 3) Undo: focus returns to root; child A stays ACTIVE.
        eng.apply(_undo_op(utterance_id="ux"))
        assert eng.focus_node_id == root_id
        snap = {n.id: n for n in eng.snapshot().nodes}
        assert snap[child_a_id].status == NodeStatus.ACTIVE

        # 4) Make it blue: must create a SIBLING of child A, not a child of A.
        diff = eng.apply(
            _modify_op(root_id, modifiers=["color:#2563eb"], utterance_id="u3")
        )
        child_b_id = diff.upserted[0].id

        assert child_b_id != child_a_id, "must be a NEW node"
        assert child_b_id != root_id, "must not be the root"

        snap = {n.id: n for n in eng.snapshot().nodes}
        # Both A and B are children of the root (siblings of each other).
        assert snap[child_b_id].parent_ids == [root_id], (
            "child B must be a direct child of root, not of child A"
        )
        assert snap[child_a_id].parent_ids == [root_id], (
            "child A still points to root"
        )
        # Focus moved to child B.
        assert eng.focus_node_id == child_b_id

    async def test_classifier_plus_engine_undo_roundtrip(self, clf: RulesClassifier) -> None:
        """Classify 'never mind' → apply the UNDO op → verify focus moved."""
        eng = _engine()
        root_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        child_id = eng.apply(_modify_op(root_id, utterance_id="u2")).upserted[0].id
        assert eng.focus_node_id == child_id

        # Build classifier context from engine state.
        ctx = eng.classifier_context()
        op = await clf.classify(
            "never mind", speaker_id="alice", utterance_id="ux", context=ctx
        )
        assert op.op_type == OpType.UNDO

        eng.apply(op)
        assert eng.focus_node_id == root_id


# =========================================================================== #
# Part 4: Replay                                                               #
# =========================================================================== #


class TestUndoReplay:
    """from_events must reproduce the same focus after an undo."""

    def test_replay_after_undo_matches_live(self) -> None:
        """create → modify → undo: from_events lands on the same focus."""
        eng = _engine()
        root_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        eng.apply(_modify_op(root_id, utterance_id="u2"))
        eng.apply(_undo_op(utterance_id="ux"))

        assert eng.focus_node_id == root_id

        replayed = DesignStateEngine.from_events("t", eng.events(), clock=FixedClock())
        assert replayed.focus_node_id == root_id, (
            f"replayed focus {replayed.focus_node_id!r} != live {root_id!r}"
        )
        assert replayed.seq == eng.seq

    def test_replay_preserves_both_nodes_active(self) -> None:
        """After replay both root (focused) and child (active) must exist."""
        eng = _engine()
        root_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        child_id = eng.apply(_modify_op(root_id, utterance_id="u2")).upserted[0].id
        eng.apply(_undo_op(utterance_id="ux"))

        replayed = DesignStateEngine.from_events("t", eng.events(), clock=FixedClock())
        snap = {n.id: n for n in replayed.snapshot().nodes}

        assert snap[root_id].status == NodeStatus.FOCUSED
        assert snap[child_id].status == NodeStatus.ACTIVE, (
            "child must stay ACTIVE after replay of an undo"
        )

    def test_replay_deep_undo_chain(self) -> None:
        """A → B → C, undo twice → focus A; replay agrees."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        b_id = eng.apply(_modify_op(a_id, utterance_id="u2")).upserted[0].id
        eng.apply(_modify_op(b_id, utterance_id="u3"))
        eng.apply(_undo_op(utterance_id="ux1"))
        eng.apply(_undo_op(utterance_id="ux2"))

        assert eng.focus_node_id == a_id

        replayed = DesignStateEngine.from_events("t", eng.events(), clock=FixedClock())
        assert replayed.focus_node_id == a_id


# =========================================================================== #
# Part 5: "go back to the previous iteration" — the live-complaint regression #
# suite (classify vocabulary widening + focus-history undo at root nodes).    #
# =========================================================================== #


class TestUndoVocabularyWidened:
    """New §14 phrasings: iteration/last/prior + verb-less 'back to the …'."""

    @pytest.mark.parametrize(
        "text",
        [
            "go back to the previous iteration",
            "previous iteration",
            "the previous iteration",
            "last iteration",
            "the last iteration",
            "back to the last one",
            "back to the previous version",
            "back to the prior state",
            "the last version",
            "prior version",
            "the previous step",
            "the previous state",
            "go back to the last one",
        ],
    )
    async def test_widened_vocabulary_fires_undo(
        self, clf: RulesClassifier, text: str
    ) -> None:
        op = await _classify(clf, text, focus="n2")
        assert op.op_type == OpType.UNDO, f"expected UNDO for '{text}', got {op.op_type}"
        assert op.confidence == 0.9

    @pytest.mark.parametrize(
        "text",
        [
            "draw the back of the house",
            "a clock going backwards",
            "the previous design had a window",
            "the last circle was better",  # names a shape, not a history position
            "add a door at the back",
        ],
    )
    async def test_content_uses_still_do_not_fire(
        self, clf: RulesClassifier, text: str
    ) -> None:
        op = await _classify(clf, text)
        assert op.op_type != OpType.UNDO, f"'{text}' must NOT fire UNDO, got {op.op_type}"

    @pytest.mark.parametrize(
        "text",
        [
            "delete the last one",
            "remove the previous version",
            "scrap the last iteration",
        ],
    )
    async def test_prune_verb_suppresses_nav_noun_undo(
        self, clf: RulesClassifier, text: str
    ) -> None:
        """'delete the last one' is a deletion, not a go-back."""
        op = await _classify(clf, text, focus="n1")
        assert op.op_type != OpType.UNDO, f"'{text}' must NOT fire UNDO, got {op.op_type}"

    async def test_directed_go_back_emits_focus_on_resolved_node(
        self, clf: RulesClassifier
    ) -> None:
        """'go back to the hexagon' with a hexagon node → FOCUS that node
        (previously fell through and CREATEd a brand-new hexagon)."""
        candidates = [
            NodeRef(node_id="n1", label="hexagon", is_focus=False),
            NodeRef(node_id="n2", label="circle", is_focus=True),
        ]
        op = await _classify(clf, "go back to the hexagon", focus="n2", candidates=candidates)
        assert op.op_type == OpType.FOCUS
        assert op.target_node_id == "n1"

    async def test_nav_word_stem_collision_stays_undo(self, clf: RulesClassifier) -> None:
        """'go back to the previous state' with a node labelled 'star' must be
        UNDO — the nav word 'state' must not stem-match the 'star' label."""
        candidates = [NodeRef(node_id="n1", label="star", is_focus=True)]
        op = await _classify(
            clf, "go back to the previous state", focus="n1", candidates=candidates
        )
        assert op.op_type == OpType.UNDO

    async def test_directed_go_back_with_modifier_falls_through(
        self, clf: RulesClassifier
    ) -> None:
        """'go back to the circle and make it red' keeps the pre-fix path:
        the MODIFY branches handle it (modifier must not be dropped)."""
        candidates = [NodeRef(node_id="n1", shape=ShapeKind.CIRCLE, is_focus=False)]
        op = await _classify(
            clf, "go back to the circle and make it red", focus="n2", candidates=candidates
        )
        assert op.op_type == OpType.MODIFY
        assert op.target_node_id == "n1"


class TestUndoFocusHistoryFallback:
    """UNDO at a ROOT node (every CREATE is a root) walks the focus history —
    the fix for 'go back … still says on the same iteration'."""

    def test_full_create_modify_modify_undo_undo_walk(self) -> None:
        """create → modify → modify → undo → undo: focus walks C → B → A and
        every diff broadcasts the new focus + both ends of the move."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        b_id = eng.apply(_modify_op(a_id, utterance_id="u2")).upserted[0].id
        c_id = eng.apply(_modify_op(b_id, modifiers=["color:#dc2626"], utterance_id="u3")).upserted[
            0
        ].id
        assert eng.focus_node_id == c_id

        d1 = eng.apply(_undo_op(utterance_id="ux1"))
        assert d1.focus_node_id == b_id, "first undo must walk back one iteration"
        assert {c_id, b_id} <= {v.id for v in d1.upserted}

        d2 = eng.apply(_undo_op(utterance_id="ux2"))
        assert d2.focus_node_id == a_id, "second undo must chain another step back"
        assert {b_id, a_id} <= {v.id for v in d2.upserted}

    def test_undo_after_new_create_returns_to_previous_chain(self) -> None:
        """create A → modify (A2) → create B (a fresh ROOT takes focus) →
        undo must return to A2, NOT stay stuck on B (the live complaint)."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        a2_id = eng.apply(_modify_op(a_id, utterance_id="u2")).upserted[0].id
        b_id = eng.apply(
            _create_op(ShapeKind.CIRCLE, label="circle", utterance_id="u3")
        ).upserted[0].id
        assert eng.focus_node_id == b_id

        diff = eng.apply(_undo_op(utterance_id="ux1"))
        assert diff.focus_node_id == a2_id, (
            "undo at a root CREATE must step back to the previously focused node"
        )
        assert {b_id, a2_id} <= {v.id for v in diff.upserted}, (
            "both ends of the focus move must be broadcast"
        )
        # And it keeps chaining: next undo walks A2's parent chain to A.
        diff = eng.apply(_undo_op(utterance_id="ux2"))
        assert diff.focus_node_id == a_id

    def test_undo_across_multiple_roots(self) -> None:
        """create A, B, C (three roots): undo → B, undo → A, undo → no-op."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        b_id = eng.apply(_create_op(ShapeKind.CIRCLE, utterance_id="u2")).upserted[0].id
        eng.apply(_create_op(ShapeKind.TRIANGLE, utterance_id="u3"))

        eng.apply(_undo_op(utterance_id="ux1"))
        assert eng.focus_node_id == b_id
        eng.apply(_undo_op(utterance_id="ux2"))
        assert eng.focus_node_id == a_id
        events_before = len(eng.events())
        eng.apply(_undo_op(utterance_id="ux3"))
        assert eng.focus_node_id == a_id, "history exhausted → no-op"
        assert len(eng.events()) == events_before, "exhausted undo appends NO event"

    def test_undo_does_not_bounce_back(self) -> None:
        """A → B → undo (→ A): a second undo must NOT return to B."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        eng.apply(_create_op(ShapeKind.CIRCLE, utterance_id="u2"))
        eng.apply(_undo_op(utterance_id="ux1"))
        assert eng.focus_node_id == a_id
        eng.apply(_undo_op(utterance_id="ux2"))
        assert eng.focus_node_id == a_id, "undo must never bounce forward again"

    def test_undo_skips_pruned_history_entries(self) -> None:
        """A, B, C roots; B pruned → undo at C skips B, lands on A."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        b_id = eng.apply(_create_op(ShapeKind.CIRCLE, utterance_id="u2")).upserted[0].id
        c_id = eng.apply(_create_op(ShapeKind.TRIANGLE, utterance_id="u3")).upserted[0].id
        assert eng.focus_node_id == c_id
        eng.apply(
            DesignOp(
                op_type=OpType.PRUNE,
                target_node_id=b_id,
                speaker_id="alice",
                utterance_id="u4",
                confidence=1.0,
            )
        )
        eng.apply(_undo_op(utterance_id="ux1"))
        assert eng.focus_node_id == a_id, "pruned node must be skipped by the fallback"

    def test_single_root_undo_still_noop(self) -> None:
        """One CREATE only: no history → undo stays a no-op (no event)."""
        eng = _engine()
        root_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        events_before = len(eng.events())
        eng.apply(_undo_op(utterance_id="ux"))
        assert eng.focus_node_id == root_id
        assert len(eng.events()) == events_before

    def test_replay_rebuilds_focus_history(self) -> None:
        """The focus-history stack must survive from_events: replay a
        create/create/undo log, then a FURTHER undo on the replayed engine
        must walk back exactly like the live engine does."""
        eng = _engine()
        a_id = eng.apply(_create_op(utterance_id="u1")).upserted[0].id
        b_id = eng.apply(_create_op(ShapeKind.CIRCLE, utterance_id="u2")).upserted[0].id
        eng.apply(_create_op(ShapeKind.TRIANGLE, utterance_id="u3"))
        eng.apply(_undo_op(utterance_id="ux1"))
        assert eng.focus_node_id == b_id

        replayed = DesignStateEngine.from_events("t", eng.events(), clock=FixedClock())
        assert replayed.focus_node_id == b_id

        eng.apply(_undo_op(utterance_id="ux2"))
        replayed.apply(_undo_op(utterance_id="ux2"))
        assert eng.focus_node_id == a_id
        assert replayed.focus_node_id == a_id, (
            "replayed engine must chain undo exactly like the live one"
        )

    async def test_live_complaint_end_to_end(self, clf: RulesClassifier) -> None:
        """The exact user flow: build a scene, iterate, say the exact phrase
        'go back to the previous iteration' — focus must actually move."""
        eng = _engine()
        a_id = eng.apply(_create_op(label="snowman", utterance_id="u1")).upserted[0].id
        a2_id = eng.apply(_modify_op(a_id, utterance_id="u2")).upserted[0].id
        assert eng.focus_node_id == a2_id

        op = await clf.classify(
            "go back to the previous iteration",
            speaker_id="alice",
            utterance_id="ux",
            context=eng.classifier_context(),
        )
        assert op.op_type == OpType.UNDO
        diff = eng.apply(op)
        assert diff.focus_node_id == a_id, "the iteration must actually change"
