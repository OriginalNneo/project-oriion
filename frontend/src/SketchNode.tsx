// SketchNode — renders one idea-tree node as a hand-drawn (rough.js) sketch.
// The low-fi look is deliberate (plan.md §7): sketchy output says "draft, keep
// iterating", which serves the alignment goal. Geometry is the same 0..100
// abstract box the server uses, mapped here into an SVG viewBox.

import { useEffect, useRef } from "react";
import rough from "roughjs";
import { transform } from "./pathdata";
import type { GeometrySpec, NodeStatus } from "./protocol";

const VIEW = 400;
const MARGIN = 28;
const SPAN = VIEW - 2 * MARGIN;
// Abstract text units → px, matched to the server renderer (4 ≈ 15px).
const FONT_PX_PER_UNIT = 15 / 4;

const sx = (x: number) => MARGIN + (x / 100) * SPAN;
const sy = (y: number) => MARGIN + (y / 100) * SPAN;
const SVG_NS = "http://www.w3.org/2000/svg";

function textEl(x: number, y: number, content: string, color: string, sizePx: number): SVGTextElement {
  const t = document.createElementNS(SVG_NS, "text");
  t.setAttribute("x", String(x));
  t.setAttribute("y", String(y + sizePx / 4)); // nudge baseline so text reads centered
  t.setAttribute("text-anchor", "middle");
  t.setAttribute("font-size", String(sizePx));
  t.setAttribute("font-family", "'Architects Daughter', 'Comic Sans MS', cursive");
  t.setAttribute("fill", color);
  t.textContent = content;
  return t;
}

// Stroke comes from the spec (spoken colors land there via the classifier);
// pruned nodes fade regardless. Focus emphasis is the card outline's job.
function strokeFor(spec: GeometrySpec, status: NodeStatus): string {
  return status === "pruned" ? "#cbd5e1" : spec.stroke || "#334155";
}

function drawShape(
  rc: ReturnType<typeof rough.svg>,
  spec: GeometrySpec,
  color: string,
): SVGElement | null {
  const cx = sx(spec.x);
  const cy = sy(spec.y);
  const w = (spec.width / 100) * SPAN;
  const h = (spec.height / 100) * SPAN;
  // Deterministic seed from geometry so the wobble is stable across re-renders.
  const seed = Math.abs(Math.round((spec.x + spec.y * 7 + spec.width * 13) * 100)) % 9999;
  // fill_style "none" wins over a fill color; otherwise honour the requested
  // style, defaulting to the sketchy hachure look (the client's whole point).
  const fillStyle = spec.fill_style ?? "hachure";
  const opts = {
    stroke: color,
    strokeWidth: spec.stroke_width ?? 2.2,
    roughness: 1.6,
    bowing: 1.2,
    seed,
    fill: fillStyle === "none" ? undefined : (spec.fill ?? undefined),
    fillStyle: (fillStyle === "none" ? "solid" : fillStyle) as "hachure" | "solid",
  };

  switch (spec.kind) {
    case "rectangle":
    case "node":
      if (spec.corner_radius > 0.5) {
        // Approximate a filleted rect with a rounded path.
        const r = Math.min((spec.corner_radius / 100) * SPAN, w / 2, h / 2);
        const x = cx - w / 2;
        const y = cy - h / 2;
        const d =
          `M${x + r},${y} h${w - 2 * r} a${r},${r} 0 0 1 ${r},${r} ` +
          `v${h - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-(w - 2 * r)} ` +
          `a${r},${r} 0 0 1 ${-r},${-r} v${-(h - 2 * r)} a${r},${r} 0 0 1 ${r},${-r} z`;
        return rc.path(d, opts);
      }
      return rc.rectangle(cx - w / 2, cy - h / 2, w, h, opts);
    case "circle":
      return rc.circle(cx, cy, Math.min(w, h), opts);
    case "ellipse":
      return rc.ellipse(cx, cy, w, h, opts);
    case "triangle":
      return rc.polygon(
        [
          [cx, cy - h / 2],
          [cx - w / 2, cy + h / 2],
          [cx + w / 2, cy + h / 2],
        ],
        opts,
      );
    case "line":
    case "edge":
      return rc.line(cx - w / 2, cy, cx + w / 2, cy, opts);
    case "polygon":
      if (!spec.points?.length) return null;
      return rc.polygon(
        spec.points.map(([px, py]) => [sx(px), sy(py)]),
        opts,
      );
    case "path":
      if (!spec.d) return null;
      // Map the 0..100 path numbers into the viewport (rough redraws point by
      // point; an SVG transform would scale stroke + wobble). Arc radii are
      // lengths, so their map is offset-free — no MARGIN.
      return rc.path(
        transform(spec.d, sx, sy, (r) => (r / 100) * SPAN),
        opts,
      );
    case "text":
      if (!spec.label) return null;
      return textEl(cx, cy, spec.label, color, (spec.font_size ?? 4) * FONT_PX_PER_UNIT);
    default:
      return null;
  }
}

export function SketchNode({ spec, status }: { spec: GeometrySpec; status: NodeStatus }) {
  const ref = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    svg.replaceChildren();
    const rc = rough.svg(svg);
    const color = strokeFor(spec, status);
    // A "group" is a scene: draw each part (own stroke unless pruned).
    const shapes = spec.kind === "group" && spec.parts?.length ? spec.parts : [spec];
    for (const part of shapes) {
      const partColor = status === "pruned" ? color : strokeFor(part, status);
      const node = drawShape(rc, part, partColor);
      if (node) svg.appendChild(node);
    }
    if (spec.label) {
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", String(sx(spec.x)));
      t.setAttribute("y", String(sy(spec.y) + 5));
      t.setAttribute("text-anchor", "middle");
      t.setAttribute("font-size", "16");
      t.setAttribute("font-family", "'Architects Daughter', 'Comic Sans MS', cursive");
      t.setAttribute("fill", color);
      t.textContent = spec.label;
      svg.appendChild(t);
    }
  }, [spec, status]);

  return (
    <svg
      ref={ref}
      viewBox={`0 0 ${VIEW} ${VIEW}`}
      width="100%"
      height="100%"
      style={{ opacity: status === "pruned" ? 0.4 : 1, transition: "opacity 0.4s" }}
    />
  );
}
