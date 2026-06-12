"""Iteration-as-branch tests for the Design State Engine (plan.md §12 R1).

Every MODIFY that effects a real geometry change must create a child node
rather than mutating in place, so the mind-map trunk stays visible.
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import DesignOp, OpType
from quorum.domain.tree import NodeStatus
from quorum.engine import DesignStateEngine
from quorum.engine.clock import FixedClock


def _engine() -> DesignStateEngine:
    return DesignStateEngine(room="t", clock=FixedClock())


def _create(
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


def _modify(
    target_id: str,
    modifiers: list[str] | None = None,
    geometry: GeometrySpec | None = None,
    label: str | None = None,
    utterance_id: str = "u2",
) -> DesignOp:
    return DesignOp(
        op_type=OpType.MODIFY,
        target_node_id=target_id,
        modifiers=modifiers or [],
        geometry=geometry,
        label=label,
        speaker_id="alice",
        utterance_id=utterance_id,
    )


# --------------------------------------------------------------------------- #
# 1) Basic child creation                                                      #
# --------------------------------------------------------------------------- #

def test_modify_creates_child_not_mutation() -> None:
    """Core invariant: MODIFY with a real change creates a child, not an in-place
    mutation. Parent geometry must be intact; focus moves to child."""
    eng = _engine()
    parent_id = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    parent_snap_before = next(n for n in eng.snapshot().nodes if n.id == parent_id)
    orig_geom = parent_snap_before.geometry

    diff = eng.apply(_modify(parent_id, modifiers=["fillet"]))
    # diff contains both child and parent views.
    ids_in_diff = {v.id for v in diff.upserted}
    assert parent_id in ids_in_diff, "parent must be in diff (children_ids changed)"

    child_view = diff.upserted[0]  # child is first (returned by _modify)
    assert child_view.id != parent_id, "child must be a NEW node"
    assert child_view.geometry.corner_radius >= 12.0, "child carries the fillet"

    # Parent geometry is unchanged.
    snap = {n.id: n for n in eng.snapshot().nodes}
    assert snap[parent_id].geometry == orig_geom, "parent geometry must be intact"

    # Parent's children_ids now includes the child (white-box via _nodes).
    assert child_view.id in eng._nodes[parent_id].children_ids

    # Focus moved to child; parent downgraded.
    assert eng.focus_node_id == child_view.id
    assert snap[child_view.id].status == NodeStatus.FOCUSED
    assert snap[parent_id].status == NodeStatus.ACTIVE


def test_modify_child_parent_ids() -> None:
    """Child's parent_ids must point to the target node."""
    eng = _engine()
    parent_id = eng.apply(_create(ShapeKind.CIRCLE)).upserted[0].id
    diff = eng.apply(_modify(parent_id, modifiers=["bigger"]))
    child_view = diff.upserted[0]
    snap = {n.id: n for n in eng.snapshot().nodes}
    assert snap[child_view.id].parent_ids == [parent_id]


# --------------------------------------------------------------------------- #
# 2) Chained modifies — label inheritance through a 3-node chain              #
# --------------------------------------------------------------------------- #

def test_chained_modifies_build_chain() -> None:
    """Three nodes: create → modify → modify. Each link must point to the previous.
    Labels inherit unless an op provides one explicitly."""
    eng = _engine()

    # Create with label "cat".
    root_id = eng.apply(_create(ShapeKind.CIRCLE, label="cat")).upserted[0].id

    # First iteration — no explicit label; should inherit "cat".
    diff1 = eng.apply(_modify(root_id, modifiers=["bigger"], utterance_id="u2"))
    mid_id = diff1.upserted[0].id

    # Second iteration — explicit label "fat cat" overrides.
    diff2 = eng.apply(_modify(mid_id, modifiers=["fillet"], label="fat cat", utterance_id="u3"))
    leaf_id = diff2.upserted[0].id

    snap = {n.id: n for n in eng.snapshot().nodes}

    # Chain structure.
    assert snap[mid_id].parent_ids == [root_id]
    assert snap[leaf_id].parent_ids == [mid_id]

    # Label inheritance.
    assert snap[root_id].label == "cat"
    assert snap[mid_id].label == "cat", "should inherit from parent when op has no label"
    assert snap[leaf_id].label == "fat cat", "explicit op label overrides inheritance"

    # Focus at leaf.
    assert eng.focus_node_id == leaf_id


def test_chained_modifies_without_explicit_label_all_inherit() -> None:
    """All iterations without explicit labels inherit from the original root label."""
    eng = _engine()
    root_id = eng.apply(_create(ShapeKind.RECTANGLE, label="cuboid")).upserted[0].id
    m1 = eng.apply(_modify(root_id, modifiers=["bigger"], utterance_id="u2")).upserted[0].id
    m2 = eng.apply(_modify(m1, modifiers=["fillet"], utterance_id="u3")).upserted[0].id

    snap = {n.id: n for n in eng.snapshot().nodes}
    assert snap[root_id].label == "cuboid"
    assert snap[m1].label == "cuboid"
    assert snap[m2].label == "cuboid"


# --------------------------------------------------------------------------- #
# 3) No-change MODIFY spawns nothing                                           #
# --------------------------------------------------------------------------- #

def test_no_change_modify_spawns_no_node() -> None:
    """A MODIFY with no modifiers and no replacement geometry is a no-op:
    no new node, no new event, focus unchanged."""
    eng = _engine()
    node_id = eng.apply(_create(ShapeKind.RECTANGLE)).upserted[0].id
    events_before = len(eng.events())
    nodes_before = len(eng.snapshot().nodes)

    diff = eng.apply(_modify(node_id, utterance_id="u2"))

    assert len(eng.snapshot().nodes) == nodes_before, "no new node must be created"
    # No new events (the no-change guard returns early before _record).
    assert len(eng.events()) == events_before, "no new events for a no-change MODIFY"
    assert eng.focus_node_id == node_id, "focus must stay on the original node"
    # The diff upserts the current node view (non-None return from _modify).
    assert any(v.id == node_id for v in diff.upserted)


# --------------------------------------------------------------------------- #
# 4) MODIFY with replacement geometry also branches                            #
# --------------------------------------------------------------------------- #

def test_modify_with_replacement_geometry_branches() -> None:
    """The LLM scene-extension path (op carries replacement geometry) also
    creates a child node, not an in-place replacement."""
    eng = _engine()
    original_scene = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[GeometrySpec(kind=ShapeKind.POLYGON, name="body",
                            points=[[10.0, 20.0], [10.0, 80.0], [90.0, 50.0]])],
    )
    parent_id = eng.apply(
        DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.GROUP,
            geometry=original_scene,
            speaker_id="alice",
            utterance_id="u1",
        )
    ).upserted[0].id

    extended_scene = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(kind=ShapeKind.POLYGON, name="body",
                         points=[[10.0, 20.0], [10.0, 80.0], [90.0, 50.0]]),
            GeometrySpec(kind=ShapeKind.RECTANGLE, name="thruster", x=8, y=50,
                         width=6, height=6),
        ],
    )
    diff = eng.apply(
        DesignOp(
            op_type=OpType.MODIFY,
            target_node_id=parent_id,
            geometry=extended_scene,
            speaker_id="alice",
            utterance_id="u2",
        )
    )
    child_view = diff.upserted[0]
    assert child_view.id != parent_id, "replacement geometry must also branch"
    assert [p.name for p in child_view.geometry.parts] == ["body", "thruster"]

    # Original parent geometry untouched.
    snap = {n.id: n for n in eng.snapshot().nodes}
    assert [p.name for p in snap[parent_id].geometry.parts] == ["body"]

    # Focus on child.
    assert eng.focus_node_id == child_view.id


# --------------------------------------------------------------------------- #
# 5) Ancestor-chain exemption from cap pruning                                 #
# --------------------------------------------------------------------------- #

def test_ancestor_chain_exempt_from_cap_prune() -> None:
    """A deep iteration chain (longer than what survives the cap) must not have
    any of its nodes pruned because the focus's ancestor chain is exempt."""
    eng = _engine()

    # Build an iteration chain of 5 nodes (create + 4 modifies).
    root_id = eng.apply(_create(ShapeKind.RECTANGLE, utterance_id="u1")).upserted[0].id
    chain: list[str] = [root_id]
    for i in range(4):
        uid = f"um{i}"
        prev_id = chain[-1]
        child_id = eng.apply(
            _modify(prev_id, modifiers=["bigger"], utterance_id=uid)
        ).upserted[0].id
        chain.append(child_id)

    # Now add many sideline (branch) nodes to push total above old cap (8) but
    # below new cap (16). All sideline nodes get negative affirmation to ensure
    # they are the ones pruned if pruning occurs; but the chain must stay.
    focus_id = chain[-1]  # leaf of the chain

    # Add 6 sideline branches off the root (separate from the iteration chain).
    for i in range(6):
        uid = f"ub{i}"
        eng.apply(
            DesignOp(
                op_type=OpType.BRANCH,
                target_node_id=root_id,
                geometry=GeometrySpec(kind=ShapeKind.CIRCLE),
                speaker_id="bob",
                utterance_id=uid,
                preference_signal=-0.5,
            )
        )

    snap = {n.id: n for n in eng.snapshot().nodes}
    # All chain nodes must still be present (not pruned).
    for nid in chain:
        assert snap[nid].status != NodeStatus.PRUNED, (
            f"chain node {nid} must not be pruned; it is on the focus ancestor path"
        )
    # Focus is still on the leaf.
    assert eng.focus_node_id == focus_id


# --------------------------------------------------------------------------- #
# 6) Replay equality                                                           #
# --------------------------------------------------------------------------- #

def test_replay_equals_live_after_iteration_chain() -> None:
    """Build create → modify → modify (3-node chain), then verify that
    from_events replay agrees with the live engine on every node's geometry,
    status, parent_ids, affirmation_score, focus, and seq."""
    eng = _engine()

    root_id = eng.apply(_create(ShapeKind.RECTANGLE, label="box")).upserted[0].id
    m1_id = eng.apply(
        _modify(root_id, modifiers=["fillet"], utterance_id="u2")
    ).upserted[0].id
    m2_id = eng.apply(
        _modify(m1_id, modifiers=["bigger"], utterance_id="u3")
    ).upserted[0].id

    replayed = DesignStateEngine.from_events("t", eng.events(), clock=FixedClock())

    assert replayed.focus_node_id == eng.focus_node_id
    assert replayed.seq == eng.seq

    live_snap = {n.id: n for n in eng.snapshot().nodes}
    replay_snap = {n.id: n for n in replayed.snapshot().nodes}

    assert live_snap.keys() == replay_snap.keys(), (
        f"live nodes {set(live_snap)} != replayed nodes {set(replay_snap)}"
    )

    for nid in live_snap:
        live_n = live_snap[nid]
        rep_n = replay_snap[nid]
        assert rep_n.geometry == live_n.geometry, f"geometry mismatch for {nid}"
        assert rep_n.status == live_n.status, f"status mismatch for {nid}"
        assert rep_n.parent_ids == live_n.parent_ids, f"parent_ids mismatch for {nid}"
        assert rep_n.affirmation_score == live_n.affirmation_score, (
            f"affirmation_score mismatch for {nid}"
        )
        assert rep_n.label == live_n.label, f"label mismatch for {nid}"

    # Confirm chain structure is preserved.
    assert replay_snap[m1_id].parent_ids == [root_id]
    assert replay_snap[m2_id].parent_ids == [m1_id]

    # New ids after replay must not collide with replayed ids.
    new_id = replayed._ids.next()
    assert new_id not in live_snap
