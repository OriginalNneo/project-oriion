"""DesignStateEngine — applies DesignOps to one session's idea-tree DAG.

This is the heart of the state model. It:
  * holds the per-session tree (a DAG of IdeaNodes) + focus + event log,
  * is the ONLY thing that mutates that state (RULES.md §5),
  * appends an immutable :class:`DesignEvent` for every change (event sourcing),
  * renders each node's SVG via the injected Renderer (cached, deterministic),
  * returns a :class:`StateDiff` describing exactly what changed, for broadcast.

It does NOT do I/O and does NOT know about WebSockets — that is the gateway's
job. This keeps the engine a pure, synchronous, unit-testable core. (The gateway
calls it from the event loop; engine ops are fast and non-blocking.)

Phase 0 exercises CREATE / BRANCH / FOCUS. MODIFY / PRUNE / CONNECT are
implemented against the same contract so Phase 2 turns them on without reshaping
the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quorum.domain.events import DesignEvent, EventType
from quorum.domain.geometry import GeometrySpec, ShapeKind, apply_modifiers
from quorum.domain.messages import NodeView, StateDiff, TreeSnapshot, node_to_view
from quorum.domain.op import ClassifierContext, DesignOp, NodeRef, OpType
from quorum.domain.tree import IdeaNode, NodeStatus, Provenance
from quorum.engine.clock import Clock, MonotonicCounter, SystemClock
from quorum.observability import get_logger
from quorum.observability.latency import stage_timer_sync
from quorum.pipeline.interfaces import Renderer
from quorum.pipeline.renderer import get_renderer

_log = get_logger("engine")

# Tunable layout / pruning constants (plan.md §4). Surfaced here, not magic
# numbers scattered in methods.
_SIBLING_DX = 22.0  # abstract-unit horizontal offset between sibling variants
_FOCUS_BUMP = 0.6  # affirmation added when a node is explicitly focused
_PRUNE_THRESHOLD = -0.8  # below this affirmation, a branch auto-prunes
# Raised from 8 to 16: iteration chains consume budget faster now that MODIFY
# creates a child node per change (plan.md §12 R1).
_MAX_ACTIVE_BRANCHES = 16  # cap on the idea cloud before pruning the weakest


@dataclass
class DesignStateEngine:
    """Authoritative state for ONE room/session."""

    room: str
    renderer: Renderer = field(default_factory=get_renderer)
    clock: Clock = field(default_factory=SystemClock)

    # --- internal state (the fold over the event log) ---
    _nodes: dict[str, IdeaNode] = field(default_factory=dict)
    _events: list[DesignEvent] = field(default_factory=list)
    _ids: MonotonicCounter = field(default_factory=MonotonicCounter)
    _focus_id: str | None = None
    _seq: int = 0
    # Chronological stack of PREVIOUS focus ids (§14 undo fallback). Maintained
    # by _set_focus with a rule that is a pure function of the FOCUS_CHANGED
    # event (op type + old/new focus), so from_events re-derives the identical
    # stack — replay parity holds without new event types.
    _focus_history: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Read API (no mutation)                                             #
    # ------------------------------------------------------------------ #
    @property
    def focus_node_id(self) -> str | None:
        return self._focus_id

    @property
    def seq(self) -> int:
        return self._seq

    def events(self) -> list[DesignEvent]:
        """The append-only log (a copy of the reference list)."""
        return list(self._events)

    def snapshot(self) -> TreeSnapshot:
        return TreeSnapshot(
            room=self.room,
            nodes=[node_to_view(n) for n in self._nodes.values()],
            focus_node_id=self._focus_id,
            seq=self._seq,
        )

    def classifier_context(self) -> ClassifierContext:
        """The minimal, read-only tree view the classifier needs to resolve a
        named/relational reference (e.g. "the triangle"). The engine stays the
        sole state owner; the classifier only reads ids + shapes (plus the
        focused node's geometry, so the LLM stage can extend a scene)."""
        focus = self._nodes.get(self._focus_id) if self._focus_id else None
        if focus is not None and focus.status == NodeStatus.PRUNED:
            focus = None
        return ClassifierContext(
            focus_node_id=self._focus_id,
            focus_geometry=focus.geometry if focus else None,
            candidates=[
                NodeRef(
                    node_id=n.id,
                    shape=n.geometry.kind,
                    label=n.label,
                    is_focus=(n.id == self._focus_id),
                )
                for n in self._nodes.values()
                if n.status != NodeStatus.PRUNED
            ],
        )

    # ------------------------------------------------------------------ #
    # Write API — the ONLY mutator. Returns the diff to broadcast.       #
    # ------------------------------------------------------------------ #
    def apply(self, op: DesignOp) -> StateDiff:
        """Apply a DesignOp; append events; return a StateDiff. Never raises on a
        well-formed op — unknown/unsupported intents degrade to a no-op diff so a
        single weird utterance can't take the loop down (plan.md §9 fault tolerance).

        Pruned nodes are *upserted* with status ``pruned`` (they fade client-side
        and stay in the snapshot for late joiners); ``removed_ids`` is reserved
        for hard deletes, which don't exist yet.
        """
        with stage_timer_sync("engine", utterance_id=op.utterance_id):
            upserted: list[NodeView] = []
            focus_before = self._focus_id

            if op.op_type == OpType.CREATE:
                upserted.append(self._create(op))
            elif op.op_type == OpType.BRANCH:
                upserted.append(self._branch(op))
            elif op.op_type == OpType.MODIFY:
                node = self._modify(op)
                if node:
                    upserted.append(node)
            elif op.op_type == OpType.FOCUS:
                upserted.extend(self._focus(op))
            elif op.op_type == OpType.PRUNE:
                upserted.extend(self._prune(op))
            elif op.op_type == OpType.CONNECT:
                node = self._connect(op)
                if node:
                    upserted.append(node)
            elif op.op_type == OpType.NOOP:
                _log.debug("noop_op", utterance_id=op.utterance_id)
            elif op.op_type == OpType.UNDO:
                upserted.extend(self._undo(op))
            else:  # pragma: no cover - exhaustive guard
                _log.warning("unknown_op_type", op_type=op.op_type)

            # Auto-prune to keep the idea cloud bounded (plan.md §4).
            upserted.extend(self._enforce_caps())

            # If focus moved (explicitly or via prune-reassignment), both ends of
            # the move must reach clients, or they render a stale status.
            if self._focus_id != focus_before:
                touched = {v.id for v in upserted}
                for nid in (focus_before, self._focus_id):
                    if nid and nid not in touched and nid in self._nodes:
                        upserted.append(node_to_view(self._nodes[nid]))

            # One entry per node, reflecting post-apply state (handlers may have
            # touched the same node more than once, e.g. prune then refocus).
            order: dict[str, None] = {}
            for view in upserted:
                order.setdefault(view.id, None)
            final_upserts = [node_to_view(self._nodes[nid]) for nid in order if nid in self._nodes]

            return StateDiff(
                room=self.room,
                seq=self._seq,
                upserted=final_upserts,
                removed_ids=[],
                focus_node_id=self._focus_id,
            )

    # ------------------------------------------------------------------ #
    # Op handlers                                                        #
    # ------------------------------------------------------------------ #
    def _create(self, op: DesignOp) -> NodeView:
        geom = self._resolve_geometry(op, parent=None)
        node = self._new_node(op, geom, parent_ids=[])
        # A new idea ALWAYS takes focus, so follow-ups ("make it bigger", "turn
        # it red") apply to the shape just created — not a stale earlier one.
        # (Before: only the FIRST create ever focused, so every later create left
        # focus on the old node — the "it keeps editing the old shape" bug.) The
        # previous focus steps back to ACTIVE; the demotion is an in-memory status
        # mutation (not an event) exactly as _modify does — replay re-derives all
        # statuses from the final focus, and FOCUS_CHANGED keeps that in the log.
        # Status is set before the event is recorded so the snapshot is accurate.
        previous = self._nodes.get(self._focus_id) if self._focus_id else None
        node.status = NodeStatus.FOCUSED
        self._nodes[node.id] = node
        self._record(EventType.NODE_CREATED, op, node)
        if previous is not None and previous.status == NodeStatus.FOCUSED:
            previous.status = NodeStatus.ACTIVE
        self._set_focus(node.id, op)
        return node_to_view(node)

    def _branch(self, op: DesignOp) -> NodeView:
        parent_id = op.target_node_id or self._focus_id
        parent = self._nodes.get(parent_id) if parent_id else None
        geom = self._resolve_geometry(op, parent=parent)
        parents = [parent.id] if parent else []
        node = self._new_node(op, geom, parent_ids=parents)
        self._nodes[node.id] = node
        if parent:
            parent.children_ids = [*parent.children_ids, node.id]
        self._record(EventType.NODE_BRANCHED, op, node)
        return node_to_view(node)

    def _modify(self, op: DesignOp) -> NodeView | None:
        target_id = op.target_node_id or self._focus_id
        node = self._nodes.get(target_id) if target_id else None
        if node is None:
            _log.debug("modify_no_target", utterance_id=op.utterance_id)
            return None
        # An op may carry replacement geometry (the LLM stage re-emits the full
        # scene to extend it — "add five thrusters"); textual modifiers still
        # fold on top.
        base_geom = op.geometry if op.geometry is not None else node.geometry
        new_geom = self._apply_modifiers(base_geom, op)

        # No-change guard: if the geometry didn't actually change, do nothing.
        # This avoids spawning empty iteration nodes for bare MODIFY ops with no
        # effective modifiers (plan.md §12 R1).
        if new_geom == node.geometry:
            return node_to_view(node)

        # Iteration-as-branch (plan.md §12 R1): a real change creates a CHILD
        # node so the mind-map trunk stays visible. The parent's geometry is
        # preserved intact; focus moves to the child for chaining follow-ups.
        child = self._new_node(op, new_geom, parent_ids=[node.id])
        # Inherit the parent's label when the op didn't supply one explicitly.
        if child.label is None:
            child.label = node.label
        # Link the child into the parent's children list.
        node.children_ids = [*node.children_ids, child.id]
        self._nodes[child.id] = child

        # NODE_MODIFIED carries the CHILD's snapshot. Because replay is
        # snapshot-driven (from_events upserts each node by id from ev.node),
        # a new node id in a NODE_MODIFIED event folds correctly — the child is
        # registered and the parent's children_ids are re-derived from parent_ids.
        self._record(EventType.NODE_MODIFIED, op, child)

        # Move focus to the child; FOCUS_CHANGED enters the log so replay lands
        # on the same focus the live session had.
        child.status = NodeStatus.FOCUSED
        if node.status == NodeStatus.FOCUSED:
            node.status = NodeStatus.ACTIVE
        self._set_focus(child.id, op)

        # Return both the child (the main change) and the parent (children_ids
        # changed). apply()'s dedup pass keeps only the final per-node view.
        return node_to_view(child)

    def _focus(self, op: DesignOp) -> list[NodeView]:
        target_id = op.target_node_id or self._focus_id
        node = self._nodes.get(target_id) if target_id else None
        if node is None or node.status == NodeStatus.PRUNED:
            return []

        # Negative preference ("not the triangle") DISAFFIRMS the target: lower
        # its score without moving focus. _enforce_caps prunes it if it sinks
        # past the floor. Focusing a node someone just rejected would be wrong.
        if op.preference_signal < 0:
            node.affirmation_score += op.preference_signal
            self._record(EventType.AFFIRMATION_CHANGED, op, node)
            return [node_to_view(node)]

        changed: list[NodeView] = []
        previous = self._focus_id
        self._set_focus(target_id, op)
        node.status = NodeStatus.FOCUSED
        node.affirmation_score += _FOCUS_BUMP + op.preference_signal
        self._record(EventType.AFFIRMATION_CHANGED, op, node)
        changed.append(node_to_view(node))
        # De-emphasize the old focus.
        if previous and previous != target_id:
            prev = self._nodes.get(previous)
            if prev is not None and prev.status == NodeStatus.FOCUSED:
                prev.status = NodeStatus.ACTIVE
                changed.append(node_to_view(prev))
        return changed

    def _prune(self, op: DesignOp) -> list[NodeView]:
        target_id = op.target_node_id
        if target_id is None or target_id not in self._nodes:
            return []
        return self._prune_node(target_id, op)

    def _connect(self, op: DesignOp) -> NodeView | None:
        a, b = op.target_node_id, op.relation_to_node
        if not a or not b or a == b or a not in self._nodes or b not in self._nodes:
            return None
        na, nb = self._nodes[a], self._nodes[b]
        geom = GeometrySpec(
            kind=ShapeKind.EDGE,
            x=(na.geometry.x + nb.geometry.x) / 2,
            y=(na.geometry.y + nb.geometry.y) / 2,
            width=max(8.0, abs(na.geometry.x - nb.geometry.x)),
            height=2.0,
        )
        edge = self._new_node(op, geom, parent_ids=[a, b])
        edge.label = op.modifiers[0] if op.modifiers else None
        self._nodes[edge.id] = edge
        # Keep children_ids the exact inverse of parent_ids — replay re-derives
        # it from parent_ids, so the live fold must match.
        for endpoint in (na, nb):
            endpoint.children_ids = [*endpoint.children_ids, edge.id]
        self._record(EventType.NODES_CONNECTED, op, edge)
        return node_to_view(edge)

    def _undo(self, op: DesignOp) -> list[NodeView]:
        """Move focus one step back (§14 "go back to the previous iteration").

        Two-tier resolution:
          1. Parent chain — if the focused node has a parent (it is an
             iteration child), focus returns to that parent. This walks a
             modify chain back one step at a time.
          2. Focus history — if the focused node is a ROOT (every CREATE is a
             root: a fresh "draw X" starts a new chain), there is no parent to
             walk to, so focus steps back to the most recent previously
             focused node that still exists and isn't pruned. Without this
             fallback, "go back" after any new CREATE was a silent no-op — the
             "still on the same iteration" bug.

        The abandoned node is NOT pruned — it stays ACTIVE and visible
        (user-confirmed design: "never mind, go back" keeps the child so the
        mind-map trunk remains intact). If there is nowhere to go back to
        (root focus + no usable history), this is a no-op: no event appended.
        """
        focus_node = self._nodes.get(self._focus_id) if self._focus_id else None
        if focus_node is None:
            return []

        target_id: str | None = None
        if focus_node.parent_ids:
            # Tier 1: the first parent (iteration chains are linear).
            target_id = focus_node.parent_ids[0]
        else:
            # Tier 2: newest usable entry in the focus history (scan only —
            # the stack itself is mutated by _set_focus's undo rule so replay
            # applies the identical mutation).
            for prev_id in reversed(self._focus_history):
                prev = self._nodes.get(prev_id)
                if (
                    prev is not None
                    and prev.status != NodeStatus.PRUNED
                    and prev_id != self._focus_id
                ):
                    target_id = prev_id
                    break

        target = self._nodes.get(target_id) if target_id else None
        if target is None:
            _log.debug("undo_nowhere_to_go", utterance_id=op.utterance_id)
            return []

        # Move focus — _set_focus appends FOCUS_CHANGED so replay lands on the
        # correct focus, and (op_type UNDO) pops the history through the target.
        self._set_focus(target_id, op)

        # Update statuses so clients render the correct highlight state.
        # The old focus node stays ACTIVE (not pruned, not faded).
        focus_node.status = NodeStatus.ACTIVE
        target.status = NodeStatus.FOCUSED

        # Both ends of the focus move must reach clients.
        return [node_to_view(focus_node), node_to_view(target)]

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _render(self, geom: GeometrySpec, utterance_id: str) -> str:
        """Render via the injected renderer, timed as the 'render' pipeline stage."""
        with stage_timer_sync("render", utterance_id=utterance_id):
            return self.renderer.render(geom)

    def _new_node(self, op: DesignOp, geom: GeometrySpec, *, parent_ids: list[str]) -> IdeaNode:
        # op.label wins over geom.label so an explicit human concept name
        # ("cat", "cuboid") is preserved through iteration children (plan.md §12 R1/R3).
        node = IdeaNode(
            id=self._ids.next(),
            geometry=geom,
            svg=self._render(geom, op.utterance_id),
            parent_ids=parent_ids,
            provenance=Provenance(
                speaker_id=op.speaker_id,
                utterance_id=op.utterance_id,
                created_ts=self.clock.now(),
                raw_text=op.raw_text,
            ),
            affirmation_score=max(0.0, op.preference_signal),
            status=NodeStatus.ACTIVE,
            label=op.label or geom.label,
        )
        return node

    def _resolve_geometry(self, op: DesignOp, *, parent: IdeaNode | None) -> GeometrySpec:
        """Decide the geometry for a new node.

        If the classifier already resolved one (rules path often does), trust it
        but place a branch next to its parent so siblings don't overlap.
        """
        if op.geometry is not None:
            base = op.geometry
        else:
            base = GeometrySpec(kind=op.target_shape or ShapeKind.RECTANGLE)
            base = self._apply_modifiers(base, op)
        if parent is not None:
            # Place the sibling to the right of the parent, clamped to the box.
            new_x = min(95.0, max(5.0, parent.geometry.x + _SIBLING_DX))
            base = base.model_copy(update={"x": new_x, "y": parent.geometry.y})
        return base

    @staticmethod
    def _apply_modifiers(geom: GeometrySpec, op: DesignOp) -> GeometrySpec:
        """Fold textual modifiers into the geometry (shared domain vocabulary)."""
        return apply_modifiers(geom, op.modifiers)

    def _set_focus(self, node_id: str | None, op: DesignOp | None) -> None:
        previous = self._focus_id
        self._focus_id = node_id
        self._fold_focus_history(
            new_focus=node_id,
            previous=previous,
            is_undo=op is not None and op.op_type == OpType.UNDO,
        )
        self._record(
            EventType.FOCUS_CHANGED,
            op,
            None,
            payload={"focus_node_id": node_id, "previous": previous},
        )

    def _fold_focus_history(
        self, *, new_focus: str | None, previous: str | None, is_undo: bool
    ) -> None:
        """Maintain the §14 focus-history stack for ONE focus change.

        The rule is a pure function of the FOCUS_CHANGED event so the live
        session and from_events replay derive the identical stack:
          * non-UNDO move: push the previous focus (a place to come back to).
          * UNDO move to X: pop everything above and including the topmost X
            (going back consumes the history — no bounce-back loops), and do
            NOT push the abandoned focus.
        """
        if is_undo:
            if new_focus is not None and new_focus in self._focus_history:
                idx = len(self._focus_history) - 1 - self._focus_history[::-1].index(new_focus)
                del self._focus_history[idx:]
            return
        if previous is not None and previous != new_focus:
            self._focus_history.append(previous)

    def _prune_node(self, node_id: str, op: DesignOp | None) -> list[NodeView]:
        node = self._nodes.get(node_id)
        if node is None or node.status == NodeStatus.PRUNED:
            return []
        node.status = NodeStatus.PRUNED
        self._record(EventType.NODE_PRUNED, op, node)
        views = [node_to_view(node)]
        if self._focus_id == node_id:
            # Reassign focus through _set_focus so the move is in the event log —
            # replay must land on the same focus the live session had.
            new_focus = self._pick_new_focus()
            self._set_focus(new_focus, None)
            if new_focus is not None:
                views.append(node_to_view(self._nodes[new_focus]))
        return views

    def _pick_new_focus(self) -> str | None:
        candidates = [n for n in self._nodes.values() if n.status != NodeStatus.PRUNED]
        if not candidates:
            return None
        best = max(candidates, key=lambda n: n.affirmation_score)
        best.status = NodeStatus.FOCUSED
        return best.id

    def _ancestor_ids(self) -> set[str]:
        """Return the set of node ids on the focus's ancestor chain (cycle-safe).

        These nodes form the mind-map trunk and must never be auto-pruned
        (plan.md §12 R1 — the trunk must stay visible).
        """
        exempt: set[str] = set()
        if self._focus_id is None:
            return exempt
        queue = [self._focus_id]
        while queue:
            nid = queue.pop()
            if nid in exempt:
                continue
            exempt.add(nid)
            node = self._nodes.get(nid)
            if node is not None:
                queue.extend(node.parent_ids)
        return exempt

    def _enforce_caps(self) -> list[NodeView]:
        """Auto-prune to keep the idea cloud bounded (plan.md §4).

        Nodes on the focus's ancestor chain (the mind-map trunk) are exempt from
        both the affirmation-floor prune and the max-active-cap prune so the full
        iteration history stays visible (plan.md §12 R1).
        """
        exempt = self._ancestor_ids()
        active = [n for n in self._nodes.values() if n.status != NodeStatus.PRUNED]
        pruned: list[NodeView] = []
        # 1) prune anything below the negative-affirmation floor
        for n in active:
            if n.affirmation_score <= _PRUNE_THRESHOLD and n.id not in exempt:
                pruned.extend(self._prune_node(n.id, None))
        # 2) enforce the max-active cap, pruning weakest (never exempt nodes)
        active = [n for n in self._nodes.values() if n.status != NodeStatus.PRUNED]
        if len(active) > _MAX_ACTIVE_BRANCHES:
            weakest = sorted(
                (n for n in active if n.id not in exempt),
                key=lambda n: n.affirmation_score,
            )
            overflow = len(active) - _MAX_ACTIVE_BRANCHES
            for n in weakest[:overflow]:
                pruned.extend(self._prune_node(n.id, None))
        return pruned

    # ------------------------------------------------------------------ #
    # Replay — state is a fold over the event log                        #
    # ------------------------------------------------------------------ #
    @classmethod
    def from_events(
        cls,
        room: str,
        events: list[DesignEvent],
        *,
        renderer: Renderer | None = None,
        clock: Clock | None = None,
    ) -> DesignStateEngine:
        """Rebuild an engine by folding an append-only event log.

        This is the event-sourcing guarantee made executable: a live session and
        its replay must agree on nodes, focus, and seq (tested). Node snapshots
        carry per-node state; FOCUS_CHANGED carries the focus; children_ids and
        active/focused statuses are derived, so they're re-derived here.
        """
        eng = cls(
            room=room,
            renderer=renderer or get_renderer(),
            clock=clock or SystemClock(),
        )
        for ev in events:
            if ev.node is not None:
                eng._nodes[ev.node.id] = ev.node.model_copy(deep=True)
            if ev.type is EventType.FOCUS_CHANGED:
                focus = ev.payload.get("focus_node_id")
                previous = ev.payload.get("previous")
                new_focus = focus if isinstance(focus, str) else None
                # Re-derive the §14 focus-history stack with the SAME pure rule
                # the live _set_focus applied, so undo behaves identically
                # after a replay.
                eng._fold_focus_history(
                    new_focus=new_focus,
                    previous=previous if isinstance(previous, str) else None,
                    is_undo=ev.op is not None and ev.op.op_type == OpType.UNDO,
                )
                eng._focus_id = new_focus
            eng._seq = max(eng._seq, ev.seq)
            eng._events.append(ev)

        # children_ids is the inverse of parent_ids — re-derive it.
        for node in eng._nodes.values():
            node.children_ids = []
        for node in eng._nodes.values():
            for pid in node.parent_ids:
                parent = eng._nodes.get(pid)
                if parent is not None and node.id not in parent.children_ids:
                    parent.children_ids = [*parent.children_ids, node.id]

        # Statuses other than PRUNED follow the focus, which may have moved
        # after a node's last snapshot was recorded.
        for node in eng._nodes.values():
            if node.status != NodeStatus.PRUNED:
                node.status = NodeStatus.FOCUSED if node.id == eng._focus_id else NodeStatus.ACTIVE

        # Resume the id counter past every replayed id so new ids never collide.
        max_i = 0
        for nid in eng._nodes:
            if nid.startswith("n") and nid[1:].isdigit():
                max_i = max(max_i, int(nid[1:]))
        eng._ids = MonotonicCounter(start=max_i)
        return eng

    def _record(
        self,
        etype: EventType,
        op: DesignOp | None,
        node: IdeaNode | None,
        payload: dict[str, str | float | None] | None = None,
    ) -> None:
        self._seq += 1
        self._events.append(
            DesignEvent(
                seq=self._seq,
                type=etype,
                ts=self.clock.now(),
                op=op,
                node=node.model_copy(deep=True) if node else None,
                payload=payload or {},
            )
        )
