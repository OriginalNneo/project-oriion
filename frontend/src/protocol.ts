// Wire protocol — the TypeScript mirror of backend/quorum/domain/messages.py.
// Keep these in lockstep with the Python models; they are the single contract
// between client and gateway (RULES.md §4). Phase 5 can codegen this from the
// pydantic schema; for now it is hand-kept and small.

export type ShapeKind =
  | "rectangle"
  | "circle"
  | "triangle"
  | "ellipse"
  | "line"
  | "group"
  // IR v2 — intricacy primitives (isometric faces, wireframes, labels):
  | "polygon"
  | "path"
  | "text"
  | "node"
  | "edge";

export type NodeStatus = "active" | "focused" | "pruned";
export type Role = "participant" | "display";

// Mirrors rough.js fillStyle choices (domain/geometry.py FillStyle).
export type FillStyle = "hachure" | "solid" | "none";

export interface GeometrySpec {
  kind: ShapeKind;
  x: number;
  y: number;
  width: number;
  height: number;
  corner_radius: number;
  label: string | null;
  stroke: string;
  fill: string | null;
  // "group" scenes: positioned primitives sharing the same 0..100 box.
  parts: GeometrySpec[];
  // --- IR v2 fields (all optional; v1 specs omit them) ---
  name?: string | null; // addressable part name for later MODIFY targeting
  points?: [number, number][] | null; // polygon vertices, 0..100 box
  d?: string | null; // constrained SVG path data, 0..100 box (see pathdata.ts)
  font_size?: number; // text glyph size in abstract units (4 ≈ 15px)
  stroke_width?: number | null; // viewBox px; null = renderer default
  fill_style?: FillStyle | null; // null = renderer default
}

export interface NodeView {
  id: string;
  geometry: GeometrySpec;
  svg: string | null;
  parent_ids: string[];
  affirmation_score: number;
  status: NodeStatus;
  label: string | null;
  suggested_by: string | null;
}

export interface TreeSnapshot {
  room: string;
  nodes: NodeView[];
  focus_node_id: string | null;
  seq: number;
}

export interface StateDiff {
  room: string;
  seq: number;
  upserted: NodeView[];
  removed_ids: string[];
  focus_node_id: string | null;
}

export type PipelineStatus = "listening" | "transcribing" | "sketching" | "idle";

// ---- Client -> Server ----
export type ClientMessage =
  | { type: "join"; room: string; role: Role; speaker_id: string; display_name?: string }
  | { type: "audio"; speaker_id: string; pcm_b64: string; seq: number }
  | { type: "utterance"; speaker_id: string; text: string }
  | {
      type: "demo_op";
      speaker_id: string;
      shape: ShapeKind;
      fillet?: boolean;
      branch_from?: string | null;
      focus?: boolean;
    }
  | { type: "correction"; speaker_id: string; utterance_id: string; corrected_text: string };

// ---- Server -> Client ----
export type ServerMessage =
  | { type: "welcome"; room: string; speaker_id: string; role: Role; snapshot: TreeSnapshot }
  | { type: "snapshot"; snapshot: TreeSnapshot }
  | { type: "diff"; diff: StateDiff }
  | { type: "transcript"; speaker_id: string; utterance_id: string; text: string; final: boolean }
  | { type: "status"; speaker_id: string | null; status: PipelineStatus }
  | { type: "error"; detail: string };
