// Participant view — the phone screen. Holds the controls + feedback (plan.md §7:
// the phones hold controls; the HDMI display stays calm). Phase 0 gives:
//   * shape buttons -> demo_op (the manual loop trigger),
//   * a "say something" text box -> utterance (exercises the rules classifier),
//   * a live transcript of what the system heard (transparency),
//   * the shared idea tree.

import { useState } from "react";
import type { ShapeKind } from "./protocol";
import type { QuorumSocket } from "./ws";
import { useStore } from "./store";
import { IdeaTree } from "./IdeaTree";

const SHAPES: { kind: ShapeKind; label: string }[] = [
  { kind: "rectangle", label: "▭ Rectangle" },
  { kind: "circle", label: "◯ Circle" },
  { kind: "triangle", label: "△ Triangle" },
  { kind: "ellipse", label: "⬭ Ellipse" },
];

export function ParticipantView({ socket, speakerId }: { socket: QuorumSocket; speakerId: string }) {
  const [text, setText] = useState("");
  const [fillet, setFillet] = useState(false);
  const focusNodeId = useStore((s) => s.focusNodeId);
  const status = useStore((s) => s.status);
  const connected = useStore((s) => s.connected);
  const transcript = useStore((s) => s.transcript);

  const create = (shape: ShapeKind) =>
    socket.send({ type: "demo_op", speaker_id: speakerId, shape, fillet });

  const branch = (shape: ShapeKind) =>
    socket.send({
      type: "demo_op",
      speaker_id: speakerId,
      shape,
      fillet,
      branch_from: focusNodeId,
    });

  const say = () => {
    const t = text.trim();
    if (!t) return;
    socket.send({ type: "utterance", speaker_id: speakerId, text: t });
    setText("");
  };

  return (
    <div className="participant">
      <header className="bar">
        <span className="brand">Quorum</span>
        <span className={`dot ${connected ? "on" : "off"}`} />
        <span className="me">you: {speakerId}</span>
        <span className="status">{status !== "idle" ? `${status}…` : ""}</span>
      </header>

      <section className="controls">
        <div className="row">
          <label className="toggle">
            <input type="checkbox" checked={fillet} onChange={(e) => setFillet(e.target.checked)} />
            fillet / rounded
          </label>
        </div>
        <div className="shape-grid">
          {SHAPES.map((s) => (
            <div key={s.kind} className="shape-cell">
              <button onClick={() => create(s.kind)}>{s.label}</button>
              <button className="ghost" disabled={!focusNodeId} onClick={() => branch(s.kind)}>
                branch
              </button>
            </div>
          ))}
        </div>

        <div className="say">
          <input
            value={text}
            placeholder='Say something: "a circle", "go with the triangle"…'
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && say()}
          />
          <button onClick={say}>Send</button>
        </div>
      </section>

      <section className="tree-wrap">
        <IdeaTree />
      </section>

      <section className="transcript">
        <h4>What the system heard</h4>
        <ul>
          {transcript
            .slice(-6)
            .reverse()
            .map((l) => (
              <li key={l.utteranceId}>
                <b>{l.speakerId}:</b> {l.text}
              </li>
            ))}
        </ul>
      </section>
    </div>
  );
}
