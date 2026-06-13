// IdeaTree — shared canvas laid out as a radial MIND-MAP (R6, plan.md §12).
// §15: canvas refactor — transform-based pan/zoom replaces the scrollTo follow effect.
// User intent: "make the mind map window bigger and adaptive, allow to zoom out, better following."
//
// DOM structure (matches CSS contract in styles.css):
//   .idea-scroll (position:relative; overflow:hidden; touch-action:none; cursor:grab)
//     .idea-viewport (position:absolute; transform-origin:0 0; will-change:transform)
//       .idea-canvas (position:relative; sized width×height)
//         svg.idea-edges
//         NodeCard[]
//     .zoom-controls (position:absolute; right:14px; bottom:14px — sibling of viewport, NOT inside canvas)
//
// Layout algorithm (pure fn, unchanged):
//   1. computeLeafCounts() — DAG-safe memoized leaf count per subtree.
//   2. Roots: cards with no visible parent. One root → canvas center.
//      Multiple roots → evenly spread on a circle of radius R.
//   3. Each node claims an angular sector; children are placed at (depth+1)*R.
//   4. Translate so min_x ≥ PAD, derive canvas size.

import { useEffect, useRef } from "react";
import { useStore } from "./store";
import { SketchNode } from "./SketchNode";
import type { NodeView } from "./protocol";
import { usePanZoom } from "./usePanZoom";
import { ZoomControls } from "./ZoomControls";

const PAD = 40; // canvas padding (px)

interface Placed {
  node: NodeView;
  x: number; // card top-left (post-PAD-translate)
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
 * Radial mind-map layout (pure fn — no side effects).
 * Returns placed map (card top-left px), canvas width, canvas height.
 *
 * Coordinate origin: top-left of .idea-canvas.
 * All placed.x/placed.y values are post-PAD-translate — pass them directly
 * to usePanZoom.recenterOn, which does: tx = vw/2 - (placed.x + cw/2)*scale.
 */
function layout(
  cards: NodeView[],
  cw: number,
  ch: number,
): { placed: Map<string, Placed>; width: number; height: number } {
  if (cards.length === 0) return { placed: new Map(), width: 0, height: 0 };

  const byId = new Map(cards.map((n) => [n.id, n]));

  const childrenOf = new Map<string, NodeView[]>(cards.map((n) => [n.id, []]));
  for (const n of cards) {
    for (const pid of n.parent_ids) {
      if (byId.has(pid)) {
        childrenOf.get(pid)!.push(n);
      }
    }
  }
  for (const kids of childrenOf.values()) kids.sort(byNumericId);

  const roots = cards.filter((n) => n.parent_ids.every((p) => !byId.has(p)));
  roots.sort(byNumericId);

  const leafCounts = computeLeafCounts(cards, childrenOf);

  // Ring radius step: one card + a tight, comfortable gap. UNIFORM per hop —
  // every parent→child edge is the same length regardless of depth, so an
  // iteration chain reads as evenly-spaced beads, not exploding gaps.
  const R = Math.max(cw, ch) + 60;

  // Centers in centered coordinate space (before PAD translate).
  const centers = new Map<string, [number, number]>();

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

    let angleCursor = minAngle;
    for (const kid of kids) {
      const leafShare = (leafCounts.get(kid.id) ?? 1) / totalLeaves;
      const kidSector = sectorSize * leafShare;
      const kidAngle = angleCursor + kidSector / 2;
      // Constant step from the PARENT — a child sits exactly one ring outward.
      // (Was childDepth*R, which compounded: chains landed at 0,R,3R,7R… so each
      //  successive hop was longer than the last — the "line across is too big" bug.)
      const kidRadius = R;
      const kidCx = cx + kidRadius * Math.cos(kidAngle);
      const kidCy = cy + kidRadius * Math.sin(kidAngle);
      place(kid.id, kidCx, kidCy, angleCursor, angleCursor + kidSector, seen);
      angleCursor += kidSector;
    }
  }

  if (roots.length === 1) {
    place(roots[0].id, 0, 0, -Math.PI, Math.PI, new Set());
  } else {
    const rootAngleStep = (2 * Math.PI) / roots.length;
    roots.forEach((root, i) => {
      const rootAngle = i * rootAngleStep - Math.PI / 2;
      const rcx = R * Math.cos(rootAngle);
      const rcy = R * Math.sin(rootAngle);
      const sectorCenter = rootAngle;
      const sectorHalf = Math.PI * (1 / roots.length + 0.1);
      place(root.id, rcx, rcy, sectorCenter - sectorHalf, sectorCenter + sectorHalf, new Set());
    });
  }

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [cx, cy] of centers.values()) {
    minX = Math.min(minX, cx - cw / 2);
    minY = Math.min(minY, cy - ch / 2);
    maxX = Math.max(maxX, cx + cw / 2);
    maxY = Math.max(maxY, cy + ch / 2);
  }

  const dx = PAD - minX;
  const dy = PAD - minY;

  const placed = new Map<string, Placed>();
  for (const [id, [cx, cy]] of centers) {
    const node = byId.get(id)!;
    // placed.x/placed.y = post-PAD top-left. These are what recenterOn consumes.
    placed.set(id, { node, x: cx + dx - cw / 2, y: cy + dy - ch / 2 });
  }

  const width = maxX - minX + PAD * 2;
  const height = maxY - minY + PAD * 2;
  return { placed, width, height };
}

function NodeCard({
  placed,
  focused,
  sketching,
  cw,
  ch,
}: {
  placed: Placed;
  focused: boolean;
  sketching: boolean;
  cw: number;
  ch: number;
}) {
  const { node, x, y } = placed;
  return (
    <div
      className={[
        "node-card",
        focused ? "focused" : "",
        node.status === "pruned" ? "pruned" : "",
        sketching ? "sketching" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={{ left: x, top: y, width: cw, height: ch }}
    >
      {sketching && focused && (
        <div className="sketch-badge">sketching…</div>
      )}
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
  const pipelineStatus = useStore((s) => s.status);
  const room = useStore((s) => s.room);

  const cw = big ? 240 : 190;
  const ch = big ? 240 : 190;

  const all = Object.values(nodes);
  // Display hides pruned branches; participants see them faded.
  const visible = all.filter((n) => n.status !== "pruned" || !big);
  const cards = visible.filter((n) => n.geometry.kind !== "edge");
  const connectors = visible.filter((n) => n.geometry.kind === "edge");

  const { placed, width, height } = layout(cards, cw, ch);

  // scrollRef: attached to .idea-scroll — the usePanZoom container.
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const {
    view,
    viewportRef,
    fit,
    recenterOn,
    zoomAboutPoint,
    resetUserAdjusted,
    isGesturing,
    follow,
    setFollow,
    userAdjusted,
  } = usePanZoom(scrollRef, { w: width, h: height, cardCount: cards.length });

  // FOLLOW: when focusNodeId changes and user hasn't manually adjusted (or follow is on),
  // animate to center the focused card. Separated from auto-fit (risk #31, #38).
  const focusPlaced = focusNodeId ? placed.get(focusNodeId) : undefined;
  const focusX = focusPlaced?.x ?? null;
  const focusY = focusPlaced?.y ?? null;

  useEffect(() => {
    if (isGesturing) return;
    // Follow toggle is the sole gate here: when off, never auto-recenter on focus changes
    // regardless of whether the user has dragged (findings 2/7). The userAdjusted guard
    // belongs only to the AUTO-FIT effect in usePanZoom.ts.
    if (!follow) return;
    if (focusX !== null && focusY !== null && focusNodeId !== null) {
      recenterOn(focusX, focusY, cw, ch);
    } else if (!userAdjusted && focusNodeId === null && cards.length > 0) {
      // focus cleared (e.g. undo clears focus) — fall back to fit (risk #12, #38).
      fit();
    }
  }, [focusNodeId, focusX, focusY, follow, isGesturing, userAdjusted, cw, ch, recenterOn, fit, cards.length]);

  // ROOM RESET: when room changes, reset userAdjusted so the new room auto-fits (risk #13).
  const prevRoomRef = useRef(room);
  useEffect(() => {
    if (room !== prevRoomRef.current) {
      prevRoomRef.current = room;
      resetUserAdjusted();
    }
  }, [room, resetUserAdjusted]);

  // Apply the view transform to .idea-viewport via the ref (no extra re-render).
  // On first mount and whenever view changes from state, sync the element style.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    // order matters: translate in screen-space then scale about origin 0 0
    vp.style.transform = `translate(${view.tx}px,${view.ty}px) scale(${view.scale})`;
  }, [view, viewportRef]);

  const sketching = pipelineStatus !== "idle";

  const center = (id: string): [number, number] | null => {
    const p = placed.get(id);
    return p ? [p.x + cw / 2, p.y + ch / 2] : null;
  };

  // Derivation edges.
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

  // Zoom control handlers — zoom about viewport center.
  // Delegates to usePanZoom.zoomAboutPoint which calls commitView + setUserAdjusted,
  // keeping React state, viewRef, and the DOM transform all in sync (findings 1/3/6).
  const zoomAboutCenter = (factor: number) => {
    const vw = scrollRef.current?.clientWidth ?? 0;
    const vh = scrollRef.current?.clientHeight ?? 0;
    zoomAboutPoint(vw / 2, vh / 2, factor);
  };

  const handleFit = () => {
    resetUserAdjusted();
    fit();
  };

  const handleRecenter = () => {
    if (focusX !== null && focusY !== null) {
      recenterOn(focusX, focusY, cw, ch);
    } else {
      fit();
    }
  };

  // Always render .idea-scroll (even empty state) so the ref and ResizeObserver
  // always have a DOM target (risk #10, #22, #39).
  return (
    <div className="idea-scroll" ref={scrollRef}>
      {cards.length === 0 ? (
        // Empty state centered within the full scroll container (risk #22).
        <div className="empty">
          <p>No ideas yet.</p>
          <p className="hint">Speak a shape — "a rectangle with a fillet" — to begin.</p>
        </div>
      ) : (
        // .idea-viewport wraps .idea-canvas and receives the CSS transform.
        // transform-origin:0 0 is set in CSS; inline transform set here and in usePanZoom.
        <div
          className="idea-viewport"
          ref={viewportRef}
          style={{
            // order matters: translate in screen-space then scale about origin 0 0
            transform: `translate(${view.tx}px,${view.ty}px) scale(${view.scale})`,
          }}
        >
          <div className="idea-canvas" style={{ width, height }}>
            {/* svg.idea-edges is first child of .idea-canvas — same coordinate space as NodeCards (risk #37). */}
            <svg className="idea-edges" width={width} height={height}>
              {derivations.map(({ from, to, dimmed }) => {
                const x0 = from.x + cw / 2;
                const y0 = from.y + ch / 2;
                const x1 = to.x + cw / 2;
                const y1 = to.y + ch / 2;
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
                sketching={sketching && p.node.id === focusNodeId}
                cw={cw}
                ch={ch}
              />
            ))}
          </div>
        </div>
      )}
      {/* ZoomControls is a sibling of .idea-viewport inside .idea-scroll,
          so it stays pinned in screen space and is never scaled (risk #15). */}
      <ZoomControls
        scale={view.scale}
        follow={follow}
        onZoomOut={() => zoomAboutCenter(0.8)}
        onZoomIn={() => zoomAboutCenter(1.25)}
        onFit={handleFit}
        onRecenter={handleRecenter}
        onToggleFollow={() => setFollow(!follow)}
      />
    </div>
  );
}
