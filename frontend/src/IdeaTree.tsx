// IdeaTree — the shared canvas of the idea cloud, laid out as an actual tree.
// Columns are derivation generations (roots left, variants to the right), and
// an SVG underlay draws the derivation edges parent -> child, so "triangle
// fillet derived from rectangle fillet" is *visible* (plan.md §4). Workflow
// `edge` nodes render as dashed connector lines between their two endpoints,
// not as cards. Both the Participant and Display views render this (one
// codebase, RULES.md §4).

import { useStore } from "./store";
import { SketchNode } from "./SketchNode";
import type { NodeView } from "./protocol";

const GAP_X = 64;
const GAP_Y = 28;
const PAD = 16;

interface Placed {
  node: NodeView;
  x: number;
  y: number;
}

function byNumericId(a: NodeView, b: NodeView): number {
  return a.id.localeCompare(b.id, undefined, { numeric: true });
}

/** Column = longest derivation chain from a visible root (cycle-safe). */
function computeDepths(cards: NodeView[]): Map<string, number> {
  const byId = new Map(cards.map((n) => [n.id, n]));
  const memo = new Map<string, number>();
  const depth = (id: string, seen: Set<string>): number => {
    const cached = memo.get(id);
    if (cached !== undefined) return cached;
    if (seen.has(id)) return 0; // DAG guard; cycles shouldn't happen
    seen.add(id);
    const node = byId.get(id);
    const parents = (node?.parent_ids ?? []).filter((p) => byId.has(p));
    const d = parents.length === 0 ? 0 : 1 + Math.max(...parents.map((p) => depth(p, seen)));
    memo.set(id, d);
    return d;
  };
  for (const n of cards) depth(n.id, new Set());
  return memo;
}

function layout(cards: NodeView[], cw: number, ch: number) {
  const depths = computeDepths(cards);
  const columns = new Map<number, NodeView[]>();
  for (const n of cards) {
    const d = depths.get(n.id) ?? 0;
    const col = columns.get(d) ?? [];
    col.push(n);
    columns.set(d, col);
  }
  const placed = new Map<string, Placed>();
  let maxRows = 1;
  for (const [d, col] of columns) {
    col.sort(byNumericId);
    maxRows = Math.max(maxRows, col.length);
    col.forEach((n, row) => {
      placed.set(n.id, {
        node: n,
        x: PAD + d * (cw + GAP_X),
        y: PAD + row * (ch + GAP_Y),
      });
    });
  }
  const colCount = columns.size === 0 ? 1 : Math.max(...columns.keys()) + 1;
  const width = PAD * 2 + colCount * cw + (colCount - 1) * GAP_X;
  const height = PAD * 2 + maxRows * ch + (maxRows - 1) * GAP_Y;
  return { placed, width, height };
}

function NodeCard({
  placed,
  focused,
  cw,
  ch,
}: {
  placed: Placed;
  focused: boolean;
  cw: number;
  ch: number;
}) {
  const { node, x, y } = placed;
  return (
    <div
      className={`node-card${focused ? " focused" : ""}${node.status === "pruned" ? " pruned" : ""}`}
      style={{ left: x, top: y, width: cw, height: ch }}
    >
      <div className="node-canvas">
        <SketchNode spec={node.geometry} status={node.status} />
      </div>
      <div className="node-meta">
        {node.suggested_by && <span className="chip">suggested by {node.suggested_by}</span>}
        {node.affirmation_score > 0.01 && (
          <span className="chip score">★ {node.affirmation_score.toFixed(1)}</span>
        )}
        {node.affirmation_score < -0.01 && (
          <span className="chip score">▽ {node.affirmation_score.toFixed(1)}</span>
        )}
      </div>
    </div>
  );
}

export function IdeaTree({ big = false }: { big?: boolean }) {
  const nodes = useStore((s) => s.nodes);
  const focusNodeId = useStore((s) => s.focusNodeId);

  const cw = big ? 240 : 190;
  const ch = big ? 240 : 190;

  const all = Object.values(nodes);
  // The display hides pruned branches entirely; participants see them faded.
  const visible = all.filter((n) => n.status !== "pruned" || !big);
  const cards = visible.filter((n) => n.geometry.kind !== "edge");
  const connectors = visible.filter((n) => n.geometry.kind === "edge");

  if (cards.length === 0) {
    return (
      <div className="empty">
        <p>No ideas yet.</p>
        <p className="hint">Speak a shape — “a rectangle with a fillet” — to begin.</p>
      </div>
    );
  }

  const { placed, width, height } = layout(cards, cw, ch);
  const center = (id: string): [number, number] | null => {
    const p = placed.get(id);
    return p ? [p.x + cw / 2, p.y + ch / 2] : null;
  };

  // Derivation edges: parent right edge -> child left edge.
  const derivations: { from: Placed; to: Placed }[] = [];
  for (const p of placed.values()) {
    for (const pid of p.node.parent_ids) {
      const from = placed.get(pid);
      if (from) derivations.push({ from, to: p });
    }
  }

  return (
    <div className="idea-scroll">
      <div className="idea-canvas" style={{ width, height }}>
        <svg className="idea-edges" width={width} height={height}>
          {derivations.map(({ from, to }) => {
            const x0 = from.x + cw;
            const y0 = from.y + ch / 2;
            const x1 = to.x;
            const y1 = to.y + ch / 2;
            const mx = (x0 + x1) / 2;
            const dim = to.node.status === "pruned" || from.node.status === "pruned";
            return (
              <path
                key={`${from.node.id}->${to.node.id}`}
                d={`M ${x0} ${y0} C ${mx} ${y0}, ${mx} ${y1}, ${x1} ${y1}`}
                fill="none"
                stroke={dim ? "#334155" : "#64748b"}
                strokeWidth={2}
                strokeDasharray={dim ? "4 6" : undefined}
              />
            );
          })}
          {connectors.map((e) => {
            const [aId, bId] = e.parent_ids;
            const a = center(aId);
            const b = center(bId);
            if (!a || !b) return null;
            return (
              <g key={e.id}>
                <line
                  x1={a[0]}
                  y1={a[1]}
                  x2={b[0]}
                  y2={b[1]}
                  stroke="#38bdf8"
                  strokeWidth={2}
                  strokeDasharray="8 6"
                />
                {e.label && (
                  <text
                    x={(a[0] + b[0]) / 2}
                    y={(a[1] + b[1]) / 2 - 6}
                    textAnchor="middle"
                    fill="#38bdf8"
                    fontSize={13}
                  >
                    {e.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        {[...placed.values()].map((p) => (
          <NodeCard
            key={p.node.id}
            placed={p}
            focused={p.node.id === focusNodeId}
            cw={cw}
            ch={ch}
          />
        ))}
      </div>
    </div>
  );
}
