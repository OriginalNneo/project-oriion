"""Design State Engine unit tests.

Uses a FixedClock so timestamps and ids are deterministic. Covers the op set the
engine supports and the invariants the architecture leans on: event log is
append-only, the first node auto-focuses, branches link as siblings, focus bumps
affirmation, prune reassigns focus.
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import DesignOp, OpType
from quorum.domain.tree import NodeStatus
from quorum.engine import DesignStateEngine
from quorum.engine.clock import FixedClock


def _engine() -> DesignStateEngine:
    return DesignStateEngine(room="t", clock=FixedClock())


def _create(shape: ShapeKind = ShapeKind.RECTANGLE, utterance_id: str = "u1") -> DesignOp:
    return DesignOp(
        op_type=OpType.CREATE,
        target_shape=shape,
        geometry=GeometrySpec(kind=shape),
        speaker_id="alice",
        utterance_id=utterance_id,
        confidence=1.0,
    )


def test_create_makes_node_and_autofocuses() -> None:
    eng = _engine()
    diff = eng.apply(_create())
    assert len(diff.upserted) == 1
    node = diff.upserted[0]
    assert node.geometry.kind == ShapeKind.RECTANGLE
    assert node.svg and node.svg.startswith("<svg")
    # first node becomes focus
    assert eng.focus_node_id == node.id
    assert eng.snapshot().focus_node_id == node.id


def test_branch_links_as_sibling_and_offsets() -> None:
    eng = _engine()
    parent_id = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    branch = DesignOp(
        op_type=OpType.BRANCH,
        target_shape=ShapeKind.TRIANGLE,
        target_node_id=parent_id,
        geometry=GeometrySpec(kind=ShapeKind.TRIANGLE),
        speaker_id="bob",
        utterance_id="u2",
    )
    child = eng.apply(branch).upserted[0]
    assert child.parent_ids == [parent_id]
    # sibling is offset horizontally so it doesn't overlap the parent
    parent = eng.snapshot().nodes
    px = next(n.geometry.x for n in parent if n.id == parent_id)
    assert child.geometry.x != px


def test_modify_applies_fillet_to_focus() -> None:
    """MODIFY creates a child node (iteration-as-branch). The child carries the
    new geometry; the parent is untouched. Focus moves to the child."""
    eng = _engine()
    nid = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    orig_radius = 0.0  # default rectangle has no fillet
    mod = DesignOp(
        op_type=OpType.MODIFY,
        target_node_id=nid,
        modifiers=["fillet"],
        speaker_id="alice",
        utterance_id="u3",
    )
    diff = eng.apply(mod)
    # First upserted node is the new child.
    child = diff.upserted[0]
    assert child.geometry.corner_radius >= 12.0
    assert child.id != nid
    # Parent geometry unchanged.
    snap = {n.id: n for n in eng.snapshot().nodes}
    assert snap[nid].geometry.corner_radius == orig_radius
    # Focus moved to child.
    assert eng.focus_node_id == child.id


def test_focus_bumps_affirmation_and_marks_status() -> None:
    eng = _engine()
    a = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    b = (
        eng.apply(
            DesignOp(
                op_type=OpType.BRANCH,
                target_node_id=a,
                geometry=GeometrySpec(kind=ShapeKind.TRIANGLE),
                speaker_id="bob",
                utterance_id="u2",
            )
        )
        .upserted[0]
        .id
    )

    focus_op = DesignOp(
        op_type=OpType.FOCUS,
        target_node_id=b,
        preference_signal=1.0,
        speaker_id="cara",
        utterance_id="u4",
    )
    eng.apply(focus_op)
    assert eng.focus_node_id == b
    snap = {n.id: n for n in eng.snapshot().nodes}
    assert snap[b].status == NodeStatus.FOCUSED
    assert snap[b].affirmation_score > 1.0  # FOCUS_BUMP + preference
    assert snap[a].status == NodeStatus.ACTIVE  # old focus de-emphasized


def test_prune_fades_node_and_reassigns_focus() -> None:
    eng = _engine()
    a = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    b = (
        eng.apply(
            DesignOp(
                op_type=OpType.BRANCH,
                target_node_id=a,
                geometry=GeometrySpec(kind=ShapeKind.CIRCLE),
                speaker_id="bob",
                utterance_id="u2",
            )
        )
        .upserted[0]
        .id
    )
    # a is the focus (first node). Prune it -> focus must move to b.
    prune = DesignOp(op_type=OpType.PRUNE, target_node_id=a, speaker_id="x", utterance_id="u5")
    diff = eng.apply(prune)
    views = {v.id: v for v in diff.upserted}
    # prune is an upsert (faded), not a removal — diffs must match snapshots
    assert diff.removed_ids == []
    assert views[a].status == NodeStatus.PRUNED
    # the newly focused node's view is in the same diff (clients see the move)
    assert views[b].status == NodeStatus.FOCUSED
    assert eng.focus_node_id == b
    assert diff.focus_node_id == b


def test_negative_preference_disaffirms_without_moving_focus() -> None:
    eng = _engine()
    a = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    b = (
        eng.apply(
            DesignOp(
                op_type=OpType.BRANCH,
                target_node_id=a,
                geometry=GeometrySpec(kind=ShapeKind.TRIANGLE),
                speaker_id="bob",
                utterance_id="u2",
            )
        )
        .upserted[0]
        .id
    )
    # "not the triangle" — focus must NOT move to b; b's score must drop.
    reject = DesignOp(
        op_type=OpType.FOCUS,
        target_node_id=b,
        preference_signal=-0.6,
        speaker_id="cara",
        utterance_id="u3",
    )
    diff = eng.apply(reject)
    assert eng.focus_node_id == a
    rejected = next(v for v in diff.upserted if v.id == b)
    assert rejected.affirmation_score < 0
    # a second rejection sinks it past the prune floor -> auto-pruned
    diff2 = eng.apply(reject.model_copy(update={"utterance_id": "u4"}))
    assert next(v for v in diff2.upserted if v.id == b).status == NodeStatus.PRUNED


def test_replay_reproduces_live_state() -> None:
    eng = _engine()
    a = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    b = (
        eng.apply(
            DesignOp(
                op_type=OpType.BRANCH,
                target_node_id=a,
                target_shape=ShapeKind.TRIANGLE,
                geometry=GeometrySpec(kind=ShapeKind.TRIANGLE),
                speaker_id="bob",
                utterance_id="u2",
            )
        )
        .upserted[0]
        .id
    )
    eng.apply(
        DesignOp(
            op_type=OpType.MODIFY,
            target_node_id=a,
            modifiers=["fillet", "bigger"],
            speaker_id="alice",
            utterance_id="u3",
        )
    )
    eng.apply(
        DesignOp(
            op_type=OpType.FOCUS,
            target_node_id=b,
            preference_signal=0.9,
            speaker_id="cara",
            utterance_id="u4",
        )
    )
    eng.apply(DesignOp(op_type=OpType.PRUNE, target_node_id=a, speaker_id="x", utterance_id="u5"))

    replayed = DesignStateEngine.from_events("t", eng.events(), clock=FixedClock())
    assert replayed.focus_node_id == eng.focus_node_id
    assert replayed.seq == eng.seq
    live = {n.id: n for n in eng.snapshot().nodes}
    back = {n.id: n for n in replayed.snapshot().nodes}
    assert live.keys() == back.keys()
    for nid, node in live.items():
        assert back[nid].status == node.status, nid
        assert back[nid].geometry == node.geometry, nid
        assert back[nid].affirmation_score == node.affirmation_score, nid
        assert back[nid].parent_ids == node.parent_ids, nid
    # new ids after replay never collide with replayed ones
    new_id = replayed._ids.next()  # white-box: counter resumed past replayed ids
    assert new_id not in live


def test_event_log_is_append_only_and_ordered() -> None:
    eng = _engine()
    eng.apply(_create(ShapeKind.RECTANGLE))
    eng.apply(_create(ShapeKind.CIRCLE, utterance_id="u2"))
    events = eng.events()
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # strictly increasing, unique
    # the returned list is a copy — mutating it doesn't corrupt the engine
    events.clear()
    assert len(eng.events()) > 0


def test_noop_is_safe() -> None:
    eng = _engine()
    diff = eng.apply(DesignOp(op_type=OpType.NOOP, speaker_id="a", utterance_id="u1"))
    assert diff.upserted == [] and diff.removed_ids == []
