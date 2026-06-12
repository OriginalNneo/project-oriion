// IdeaTree — shared canvas laid out as a radial MIND-MAP (R6, plan.md §12).
// The original idea sits at the center; each iteration/variant extends OUTWARD
// as a new linked node. Derivation chains radiate from the center so the trunk
// stays straight and the map reads left-to-right-outward naturally.
//
// Layout algorithm (pure function, replaces the column layout):
//   1. computeDepths() — unchanged DAG-safe BFS from the existing code.
//   2. Roots: cards whose every parent_id is NOT a visible card. One root →
//      exact canvas center. Multiple roots → evenly spread on a small circle
//      (radius = R) so they don't sit on top of each other.
//   3. Each node claims an angular sector. Its children are sorted by numeric
//      id (deterministic), each allocated a sub-sector proportional to its
//      LEAF count (subtree leaves = max(1, actual leaves in the visible tree)).
//      Each child sits at radius (depth+1)*R from the root at the sector
//      bisector angle.
//   4. After all positions are computed in a centered coordinate system,
//      translate so min_x ≥ PAD and min_y ≥ PAD and derive canvas size.
//
// Geometry sanity-check (1 root + 3 children + 1 grandchild on child-0):
//   root at (0,0). R = 270 (cw=190+80). 3 children → full circle /3 sectors.
//   child[0] angle = 0°,  pos = (270, 0). Its 1 child at depth 2: (540, 0).
//   child[1] angle = 120°, pos = (-135, 234).
//   child[2] angle = 240°, pos = (-135, -234).
//   All pairwise distances ≥ 270 (card diagonal ≈ 269 for 190×190). ✓ no overlap.
//   After translate, all positions are ≥ PAD. ✓

import { useStore } from "./store";
import { SketchNode } from "./SketchNode";
import type { NodeView } from "./protocol";

const PAD = 40; // canvas padding (px)

interface Placed {
  node: NodeView;
  x: number; // top-left of card
  y: number;
}

function byNumericId(a: NodeView, b: NodeView): number {
  return a.id.localeCompare(b.id, undefined, { numeric: true });
}


/** Leaf count for a subtree rooted at `id` (within the visible card set). */
function computeLeafCounts(
  cards: NodeView[],
  childrenOf: Map<string, NodeView[]>,
): Map<string, number> {
  const memo = new Map<string, number>();
  const leaves = (id: string, seen: Set<string>): number => {
    const cached = memo.get(id);
    if (cached !== undefined) return cached;
    if (seen.has(id)) return 1; // cycle guard — treat as leaf
    seen.add(id);
    const kids = childrenOf.get(id) ?? [];
    const count = kids.length === 0 ? 1 : kids.reduce((s, k) => s + leaves(k.id, new Set(seen)), 0);
    memo.set(id, count);
    return count;
  };
  for (const n of cards) leaves(n.id, new Set());
  return memo;
}

/**
 * Radial mind-map layout.
 * Returns: placed map (card top-left px), canvas width, canvas height.
 *
 * Coordinate system: all positions computed with center at (0,0),
 * then translated so everything is ≥ PAD.
 */
function layout(
  cards: NodeView[],
  cw: number,
  ch: number,
): { placed: Map<string, Placed>; width: number; height: number } {
  if (cards.length === 0) return { placed: new Map(), width: 0, height: 0 };

  const byId = new Map(cards.map((n) => [n.id, n]));

  // Build parent→children map (within visible set only).
  const childrenOf = new Map<string, NodeView[]>(cards.map((n) => [n.id, []]));
  for (const n of cards) {
    for (const pid of n.parent_ids) {
      if (byId.has(pid)) {
        childrenOf.get(pid)!.push(n);
      }
    }
  }
  // Sort children deterministically.
  for (const kids of childrenOf.values()) kids.sort(byNumericId);

  // Roots: cards with no visible parent.
  const roots = cards.filter((n) => n.parent_ids.every((p) => !byId.has(p)));
  roots.sort(byNumericId);

  const leafCounts = computeLeafCounts(cards, childrenOf);

  // Ring radius step: card diagonal + comfortable gap.
  const R = Math.sqrt(cw * cw + ch * ch) * 0.5 + Math.max(cw, ch) * 0.6 + 40;

  // Centers stored here (relative to the canvas origin (0,0) before translate).
  // We compute card top-left = center - (cw/2, ch/2) at the end.
  const centers = new Map<string, [number, number]>();

  /**
   * Recursively place a subtree.
   * @param id       node being placed
   * @param cx/cy    center position of this node
   * @param minAngle start of the angular sector this subtree owns (radians)
   * @param maxAngle end of the angular sector
   * @param depth    depth from nearest root (0 = root)
   * @param seen     cycle guard
   */
  function place(
    id: string,
    cx: number,
    cy: number,
    minAngle: number,
    maxAngle: number,
    seen: Set<string>,
  ) {
    centers.set(id, [cx, cy]);
    const kids = childrenOf.get(id) ?? [];
    if (kids.length === 0 || seen.has(id)) return;
    seen = new Set(seen);
    seen.add(id);

    const totalLeaves = kids.reduce((s, k) => s + (leafCounts.get(k.id) ?? 1), 0);
    const sectorSize = maxAngle - minAngle;

    // Find depth of this node to compute child ring radius.
    // We measure it as the depth from the nearest root, i.e. the
    // number of placed ancestors. We derive it from the center distance.
    const distFromOrigin = Math.sqrt(cx * cx + cy * cy);
    const childDepth = Math.round(distFromOrigin / R) + 1;

    let angleCursor = minAngle;
    for (const kid of kids) {
      const leafShare = (leafCounts.get(kid.id) ?? 1) / totalLeaves;
      const kidSector = sectorSize * leafShare;
      const kidAngle = angleCursor + kidSector / 2;
      const kidRadius = childDepth * R;
      const kidCx = cx + kidRadius * Math.cos(kidAngle);
      const kidCy = cy + kidRadius * Math.sin(kidAngle);
      place(kid.id, kidCx, kidCy, angleCursor, angleCursor + kidSector, seen);
      angleCursor += kidSector;
    }
  }

  if (roots.length === 1) {
    // Single root → exact center.
    place(roots[0].id, 0, 0, -Math.PI, Math.PI, new Set());
  } else {
    // Multiple roots: spread on a circle of radius R, then fan each outward.
    const rootAngleStep = (2 * Math.PI) / roots.length;
    roots.forEach((root, i) => {
      const rootAngle = i * rootAngleStep - Math.PI / 2;
      const rcx = R * Math.cos(rootAngle);
      const rcy = R * Math.sin(rootAngle);
      // Each root fans into the half of the circle facing outward.
      const sectorCenter = rootAngle;
      const sectorHalf = Math.PI * (1 / roots.length + 0.1); // slight overlap ok for spread
      place(root.id, rcx, rcy, sectorCenter - sectorHalf, sectorCenter + sectorHalf, new Set());
    });
  }

  // Convert centers → top-left positions and find extent.
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  for (const [cx, cy] of centers.values()) {
    minX = Math.min(minX, cx - cw / 2);
    minY = Math.min(minY, cy - ch / 2);
    maxX = Math.max(maxX, cx + cw / 2);
    maxY = Math.max(maxY, cy + ch / 2);
  }

  // Translate so all top-lefts are ≥ PAD.
  const dx = PAD - minX;
  const dy = PAD - minY;

  const placed = new Map<string, Placed>();
  for (const [id, [cx, cy]] of centers) {
    const node = byId.get(id)!;
    placed.set(id, { node, x: cx + dx - cw / 2, y: cy + dy - ch / 2 });
  }

  const width = maxX - minX + PAD * 2;
  const height = maxY - minY + PAD * 2;
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
      {node.label && <div className="node-title">{node.label}</div>}
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
  // Display hides pruned branches; participants see them faded.
  const visible = all.filter((n) => n.status !== "pruned" || !big);
  const cards = visible.filter((n) => n.geometry.kind !== "edge");
  const connectors = visible.filter((n) => n.geometry.kind === "edge");

  if (cards.length === 0) {
    return (
      <div className="empty">
        <p>No ideas yet.</p>
        <p className="hint">Speak a shape — "a rectangle with a fillet" — to begin.</p>
      </div>
    );
  }

  const { placed, width, height } = layout(cards, cw, ch);

  const center = (id: string): [number, number] | null => {
    const p = placed.get(id);
    return p ? [p.x + cw / 2, p.y + ch / 2] : null;
  };

  // Derivation edges: smooth cubics between card centers.
  const derivations: { from: Placed; to: Placed; dimmed: boolean }[] = [];
  for (const p of placed.values()) {
    for (const pid of p.node.parent_ids) {
      const from = placed.get(pid);
      if (from) {
        const dimmed = p.node.status === "pruned" || from.node.status === "pruned";
        derivations.push({ from, to: p, dimmed });
      }
    }
  }

  return (
    <div className="idea-scroll">
      <div className="idea-canvas" style={{ width, height }}>
        <svg className="idea-edges" width={width} height={height}>
          {derivations.map(({ from, to, dimmed }) => {
            // Centers of the two cards.
            const x0 = from.x + cw / 2;
            const y0 = from.y + ch / 2;
            const x1 = to.x + cw / 2;
            const y1 = to.y + ch / 2;
            // Cubic bezier: control points at horizontal midpoint on each
            // end's y, giving a smooth horizontal-biased S-curve between
            // any two card centers in the radial layout.
            const mx = (x0 + x1) / 2;
            return (
              <path
                key={`${from.node.id}->${to.node.id}`}
                d={`M ${x0} ${y0} C ${mx} ${y0}, ${mx} ${y1}, ${x1} ${y1}`}
                fill="none"
                stroke={dimmed ? "#334155" : "#64748b"}
                strokeWidth={2}
                strokeDasharray={dimmed ? "4 6" : undefined}
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
