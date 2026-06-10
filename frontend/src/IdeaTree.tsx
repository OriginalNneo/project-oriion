// IdeaTree — the shared canvas of the idea cloud. Lays out each node as a card,
// emphasizes the focused one, fades pruned ones, and shows provenance. Both the
// Participant and Display views render this (one codebase, RULES.md §4).

import { useStore } from "./store";
import { SketchNode } from "./SketchNode";
import type { NodeView } from "./protocol";

function NodeCard({ node, focused, big }: { node: NodeView; focused: boolean; big: boolean }) {
  return (
    <div
      className={`node-card${focused ? " focused" : ""}${node.status === "pruned" ? " pruned" : ""}`}
      style={{
        width: big ? 260 : 200,
        height: big ? 260 : 200,
      }}
    >
      <div className="node-canvas">
        <SketchNode spec={node.geometry} status={node.status} />
      </div>
      <div className="node-meta">
        {node.suggested_by && <span className="chip">suggested by {node.suggested_by}</span>}
        {node.affirmation_score > 0.01 && (
          <span className="chip score">★ {node.affirmation_score.toFixed(1)}</span>
        )}
      </div>
    </div>
  );
}

export function IdeaTree({ big = false }: { big?: boolean }) {
  const nodes = useStore((s) => s.nodes);
  const focusNodeId = useStore((s) => s.focusNodeId);

  const list = Object.values(nodes).filter((n) => n.status !== "pruned" || !big);
  // Focused node first, then by id for stable ordering.
  list.sort((a, b) => {
    if (a.id === focusNodeId) return -1;
    if (b.id === focusNodeId) return 1;
    return a.id.localeCompare(b.id, undefined, { numeric: true });
  });

  if (list.length === 0) {
    return (
      <div className="empty">
        <p>No ideas yet.</p>
        <p className="hint">Speak a shape — or tap a shape button — to begin.</p>
      </div>
    );
  }

  return (
    <div className="idea-tree">
      {list.map((n) => (
        <NodeCard key={n.id} node={n} focused={n.id === focusNodeId} big={big} />
      ))}
    </div>
  );
}
