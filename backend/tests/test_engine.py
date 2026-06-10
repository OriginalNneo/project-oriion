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
    eng = _engine()
    nid = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    mod = DesignOp(
        op_type=OpType.MODIFY,
        target_node_id=nid,
        modifiers=["fillet"],
        speaker_id="alice",
        utterance_id="u3",
    )
    out = eng.apply(mod).upserted[0]
    assert out.geometry.corner_radius >= 12.0


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


def test_prune_removes_and_reassigns_focus() -> None:
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
    assert a in diff.removed_ids
    assert eng.focus_node_id == b


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
