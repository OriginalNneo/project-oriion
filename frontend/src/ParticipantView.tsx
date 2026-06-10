// Participant view — the phone screen. Holds the controls + feedback (plan.md §7:
// the phones hold controls; the HDMI display stays calm). The MVP loop:
//   * a mic toggle -> browser speech recognition -> `utterance` messages
//     (the conversation is the input device),
//   * a "say something" text box as the no-mic fallback / correction path,
//   * shape buttons -> demo_op (the original manual loop trigger),
//   * a live transcript of what the system heard (transparency),
//   * the shared idea tree.

import { useEffect, useRef, useState } from "react";
import type { ShapeKind } from "./protocol";
import type { QuorumSocket } from "./ws";
import { useStore } from "./store";
import { IdeaTree } from "./IdeaTree";
import { VoiceInput } from "./speech";

const SHAPES: { kind: ShapeKind; label: string }[] = [
  { kind: "rectangle", label: "▭ Rectangle" },
  { kind: "circle", label: "◯ Circle" },
  { kind: "triangle", label: "△ Triangle" },
  { kind: "ellipse", label: "⬭ Ellipse" },
];

export function ParticipantView({ socket, speakerId }: { socket: QuorumSocket; speakerId: string }) {
  const [text, setText] = useState("");
  const [fillet, setFillet] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const focusNodeId = useStore((s) => s.focusNodeId);
  const status = useStore((s) => s.status);
  const connected = useStore((s) => s.connected);
  const transcript = useStore((s) => s.transcript);

  const voiceSupported = VoiceInput.isSupported();
  const voiceRef = useRef<VoiceInput | null>(null);
  if (voiceRef.current === null && voiceSupported) {
    voiceRef.current = new VoiceInput({
      onFinal: (t) => socket.send({ type: "utterance", speaker_id: speakerId, text: t }),
      onInterim: setInterim,
      onState: setListening,
      onError: setVoiceError,
    });
  }
  useEffect(() => () => voiceRef.current?.stop(), []);

  const toggleMic = () => {
    const voice = voiceRef.current;
    if (!voice) return;
    setVoiceError(null);
    if (voice.listening) voice.stop();
    else voice.start();
  };

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
        <span className="status">
          {status !== "idle" ? `${status}…` : listening ? "listening…" : ""}
        </span>
      </header>

      <section className="controls">
        <div className="voice-row">
          <button
            className={`mic${listening ? " on" : ""}`}
            onClick={toggleMic}
            disabled={!voiceSupported}
            title={voiceSupported ? "toggle voice input" : "voice needs Chrome/Safari + a secure origin"}
          >
            {listening ? "● listening — tap to stop" : "🎤 Speak"}
          </button>
          <span className="interim">
            {voiceError
              ? voiceError
              : interim
                ? `“${interim}…”`
                : listening
                  ? "say a shape, a change, or a preference"
                  : voiceSupported
                    ? ""
                    : "voice unavailable here — use the text box"}
          </span>
        </div>

        <div className="say">
          <input
            value={text}
            placeholder='Say or type: "a red circle", "make it bigger", "go with the triangle"…'
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && say()}
          />
          <button onClick={say}>Send</button>
        </div>

        <details className="manual">
          <summary>manual shape buttons</summary>
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
        </details>
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
