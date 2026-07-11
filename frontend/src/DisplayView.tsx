// Display view — the HDMI'd screen. View-only, fullscreen, minimal chrome,
// calm and big (plan.md §7: "Display view ≠ participant view"). No controls;
// it only reflects broadcast state — now in the ORIION layout: brand header,
// full-bleed mind map, and an alignment strip (pipeline stepper while the
// system works, idea count + affirmation tallies while idle).

import { useStore } from "./store";
import { IdeaTree } from "./IdeaTree";
import { Tally } from "./ReactionMenu";
import type { PipelineStatus } from "./protocol";

const STEPS: { key: PipelineStatus; label: string }[] = [
  { key: "listening", label: "Listening" },
  { key: "transcribing", label: "Transcribing" },
  { key: "sketching", label: "Sketching" },
];

export function DisplayView() {
  const room = useStore((s) => s.room);
  const status = useStore((s) => s.status);
  const statusSpeaker = useStore((s) => s.statusSpeaker);
  const connected = useStore((s) => s.connected);
  const nodes = useStore((s) => s.nodes);
  const focusNodeId = useStore((s) => s.focusNodeId);

  const all = Object.values(nodes).filter((n) => n.geometry.kind !== "edge");
  const count = all.length;
  const focused = focusNodeId ? nodes[focusNodeId] : undefined;

  // Alignment strip: the most-affirmed / most-disputed live branches.
  const rated = all
    .filter((n) => n.status !== "pruned" && Math.abs(n.affirmation_score) > 0.01)
    .sort((a, b) => Math.abs(b.affirmation_score) - Math.abs(a.affirmation_score))
    .slice(0, 4);

  return (
    <div className="display">
      <header className="d-head">
        <span className="brand-xl">ORIION</span>
        <span className="d-tagline">Meeting Alignment</span>
        <span className="d-head-right">
          <span className="sk pill room-pill">room · {room || "…"}</span>
          <span className={`conn ${connected ? "on" : "off"}`}>
            <span className={`dot ${connected ? "on" : "off"}`} />
            {connected ? "live" : "offline"}
          </span>
        </span>
      </header>

      {/* Full-bleed: IdeaTree fills this via transform-based pan/zoom
          (see .display-stage in styles.css) */}
      <main className="display-stage">
        <IdeaTree big />
      </main>

      <footer className="d-strip">
        {status !== "idle" ? (
          <div className="stepper">
            {statusSpeaker && <span className="who">{statusSpeaker}</span>}
            {STEPS.map((s, i) => (
              <span key={s.key} style={{ display: "contents" }}>
                <span className={`st${s.key === status ? " active" : ""}`}>{s.label}</span>
                {i < STEPS.length - 1 && <span className="sep">→</span>}
              </span>
            ))}
          </div>
        ) : (
          <>
            <span>
              {count} idea{count === 1 ? "" : "s"} on the board
            </span>
            {focused?.label && <span className="focus-label">· current: {focused.label}</span>}
            {rated.map((n) => (
              <Tally
                key={n.id}
                kind={n.affirmation_score > 0 ? "matches" : "wrong"}
                text={`${n.label ?? "idea"} ${n.affirmation_score.toFixed(1)}`}
              />
            ))}
          </>
        )}
      </footer>
    </div>
  );
}
