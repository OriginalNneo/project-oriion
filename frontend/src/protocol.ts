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
  | "node"
  | "edge";

export type NodeStatus = "active" | "focused" | "pruned";
export type Role = "participant" | "display";

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
