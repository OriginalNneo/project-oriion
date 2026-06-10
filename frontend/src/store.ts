// Zustand store — a *view* of server-broadcast state, nothing authoritative.
// The reducer applies snapshots/diffs exactly as the server sends them
// (RULES.md §4: render is a pure function of the broadcast state).

import { create } from "zustand";
import type { NodeView, PipelineStatus, ServerMessage, TreeSnapshot } from "./protocol";

interface TranscriptLine {
  speakerId: string;
  utteranceId: string;
  text: string;
}

interface QuorumState {
  connected: boolean;
  room: string;
  seq: number;
  nodes: Record<string, NodeView>;
  focusNodeId: string | null;
  status: PipelineStatus;
  statusSpeaker: string | null;
  transcript: TranscriptLine[];
  error: string | null;

  // actions
  setConnected: (c: boolean) => void;
  applyServerMessage: (msg: ServerMessage) => void;
  reset: (room: string) => void;
}

function applySnapshot(snap: TreeSnapshot): Partial<QuorumState> {
  const nodes: Record<string, NodeView> = {};
  for (const n of snap.nodes) nodes[n.id] = n;
  return { nodes, focusNodeId: snap.focus_node_id, seq: snap.seq, room: snap.room };
}

export const useStore = create<QuorumState>((set) => ({
  connected: false,
  room: "",
  seq: 0,
  nodes: {},
  focusNodeId: null,
  status: "idle",
  statusSpeaker: null,
  transcript: [],
  error: null,

  setConnected: (c) => set({ connected: c }),

  reset: (room) =>
    set({
      room,
      seq: 0,
      nodes: {},
      focusNodeId: null,
      status: "idle",
      transcript: [],
      error: null,
    }),

  applyServerMessage: (msg) =>
    set((state) => {
      switch (msg.type) {
        case "welcome":
          return applySnapshot(msg.snapshot);
        case "snapshot":
          return applySnapshot(msg.snapshot);
        case "diff": {
          const nodes = { ...state.nodes };
          for (const n of msg.diff.upserted) nodes[n.id] = n;
          for (const id of msg.diff.removed_ids) delete nodes[id];
          return {
            nodes,
            seq: msg.diff.seq,
            focusNodeId: msg.diff.focus_node_id ?? state.focusNodeId,
          };
        }
        case "transcript": {
          const line = { speakerId: msg.speaker_id, utteranceId: msg.utterance_id, text: msg.text };
          // keep the last 30 lines
          const transcript = [...state.transcript, line].slice(-30);
          return { transcript };
        }
        case "status":
          return { status: msg.status, statusSpeaker: msg.speaker_id };
        case "error":
          return { error: msg.detail };
        default:
          return {};
      }
    }),
}));

// Stable selector helpers.
export const selectNodes = (s: QuorumState): NodeView[] => Object.values(s.nodes);
