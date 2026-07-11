// Participant view — the ORIION phone screen. Holds the controls + feedback
// (plan.md §7: the phones hold controls; the HDMI display stays calm).
//   * Current Generated Visual card — the focused idea's sketch
//     (tap -> mind map view, hold -> reaction menu),
//   * Live Captions card — the "what the system heard" surface (transparency)
//     with the text box as the no-mic fallback / correction path + Undo,
//   * manual shape buttons -> demo_op (the original manual loop trigger),
//   * the always-visible mic pill (tap = mic toggle, hold = react).

import { useEffect, useRef, useState } from "react";
import type { ShapeKind } from "./protocol";
import type { QuorumSocket } from "./ws";
import { useStore } from "./store";
import { IdeaTree } from "./IdeaTree";
import { SketchNode } from "./SketchNode";
import { VoiceInput } from "./speech";
import { MicPill } from "./MicPill";
import { ReactionMenu, Tally } from "./ReactionMenu";

const SHAPES: { kind: ShapeKind; label: string }[] = [
  { kind: "rectangle", label: "▭ Rectangle" },
  { kind: "circle", label: "◯ Circle" },
  { kind: "triangle", label: "△ Triangle" },
  { kind: "ellipse", label: "⬭ Ellipse" },
];

const HOLD_MS = 380;

export function ParticipantView({
  socket,
  speakerId,
  onLeave,
}: {
  socket: QuorumSocket;
  speakerId: string;
  onLeave: () => void;
}) {
  const [text, setText] = useState("");
  const [fillet, setFillet] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [view, setView] = useState<"main" | "map">("main");
  const [reactOpen, setReactOpen] = useState(false);
  const focusNodeId = useStore((s) => s.focusNodeId);
  const nodes = useStore((s) => s.nodes);
  const status = useStore((s) => s.status);
  const connected = useStore((s) => s.connected);
  const room = useStore((s) => s.room);
  const transcript = useStore((s) => s.transcript);

  const voiceUnavailable = VoiceInput.unavailableReason();
  const voiceSupported = voiceUnavailable === null;
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

  const sendUtterance = (t: string) =>
    socket.send({ type: "utterance", speaker_id: speakerId, text: t });

  const say = () => {
    const t = text.trim();
    if (!t) return;
    sendUtterance(t);
    setText("");
  };

  // Undo: sends the literal text 'undo' — engine maps it to OpType.UNDO.
  const undo = () => sendUtterance("undo");

  // Focused node for the visual card (connector edges aren't drawable cards).
  const focused = focusNodeId ? nodes[focusNodeId] : undefined;
  const focusedDrawable = focused && focused.geometry.kind !== "edge" ? focused : undefined;

  // Hold-to-react on the visual card: `held` suppresses the tap that follows
  // a hold (same pattern as MicPill; no separate onClick so the synthetic
  // click after a touch hold can't double-fire).
  const holdTimer = useRef<number | null>(null);
  const held = useRef(false);
  const cardDown = () => {
    held.current = false;
    if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
    holdTimer.current = window.setTimeout(() => {
      held.current = true;
      setReactOpen(true);
    }, HOLD_MS);
  };
  const cardUp = () => {
    if (holdTimer.current !== null) {
      window.clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
    if (!held.current) setView("map");
  };
  const cardCancel = () => {
    if (holdTimer.current !== null) {
      window.clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
  };

  // Live captions auto-scroll (newest at the bottom).
  const feedRef = useRef<HTMLDivElement | null>(null);
  const lastLines = transcript.slice(-6);
  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [transcript.length, interim]);

  const sketching = status !== "idle";
  const micHint = !voiceSupported
    ? (voiceUnavailable ?? "voice unavailable")
    : `${listening ? "Tap to pause" : "Tap to speak"} · Hold to react`;

  return (
    <div className="p-shell">
      <header className="p-head">
        <span className="brand">ORIION</span>
        <span className={`conn ${connected ? "on" : "off"}`}>
          <span className={`dot ${connected ? "on" : "off"}`} />
          {connected ? "live" : "offline"}
        </span>
        <span className="room">room · {room || "…"}</span>
        <span className="me">you · {speakerId}</span>
        <span className="status">
          {sketching ? (
            <span className="status-live">
              <span className="status-pip" /> {status}…
            </span>
          ) : listening ? (
            <span className="status-live">
              <span className="status-pip" /> listening…
            </span>
          ) : (
            ""
          )}
        </span>
        <button className="chrome leave" onClick={onLeave} title="Leave this room">
          leave ↩
        </button>
      </header>

      {view === "main" ? (
        <>
          {/* Current Generated Visual — the focused idea's sketch. */}
          <section
            className="visual-card sk lg"
            onPointerDown={cardDown}
            onPointerUp={cardUp}
            onPointerLeave={cardCancel}
            onPointerCancel={cardCancel}
          >
            {sketching && <div className="sketch-badge">sketching…</div>}
            <div className="card-ttl-row">
              <span className="card-ttl">Current Generated Visual</span>
              <button
                type="button"
                className="react-btn"
                disabled={!focusedDrawable}
                title={focusedDrawable ? "React to this visual" : "No visual to react to yet"}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  setReactOpen(true);
                }}
              >
                ⊕ React
              </button>
            </div>
            <div className="visual-body">
              {focusedDrawable ? (
                <SketchNode spec={focusedDrawable.geometry} status={focusedDrawable.status} />
              ) : (
                <div className="visual-empty">
                  No idea in focus yet — say a shape ("a red circle") to begin.
                </div>
              )}
            </div>
            <div className="visual-cap">
              {focusedDrawable?.label ?? (focusedDrawable ? "current idea" : "")}
            </div>
            {focusedDrawable && (
              <div className="chips">
                {focusedDrawable.affirmation_score > 0.01 && (
                  <Tally kind="matches" text={focusedDrawable.affirmation_score.toFixed(1)} />
                )}
                {focusedDrawable.affirmation_score < -0.01 && (
                  <Tally kind="wrong" text={focusedDrawable.affirmation_score.toFixed(1)} />
                )}
              </div>
            )}
            <div className="visual-hint">Tap to see the mind map · Hold to react</div>
          </section>

          {/* Live captions — the "what the system heard" surface + correction path. */}
          <section className="captions-card sk lg">
            <div className="card-ttl">Live Captions</div>
            <div className="cap-feed" ref={feedRef}>
              {lastLines.length === 0 && !interim && (
                <div className="cap-empty">Nothing heard yet — speak, or type below.</div>
              )}
              {lastLines.map((l) => (
                <div className="cap-row" key={l.utteranceId}>
                  <span>
                    <b>{l.speakerId}:</b> {l.text}
                  </span>
                </div>
              ))}
              {interim && (
                <div className="cap-row ghost">
                  <span>
                    <b>{speakerId}:</b> {interim}…
                  </span>
                </div>
              )}
              {voiceError && (
                <div className="cap-row err">
                  <span>{voiceError}</span>
                </div>
              )}
            </div>
            <div className="say">
              <input
                className="app-in"
                value={text}
                placeholder='Say or type: "a red circle", "go with the triangle"…'
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setText(e.target.value)}
                onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && say()}
              />
              <button className="sm" onClick={say}>
                Send
              </button>
              <button className="btn-undo sm" onClick={undo} title="Undo last change">
                ↩ Undo
              </button>
            </div>

            <details className="manual">
              <summary>manual shape buttons</summary>
              <div className="row">
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={fillet}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFillet(e.target.checked)}
                  />
                  fillet / rounded
                </label>
              </div>
              <div className="shape-grid">
                {SHAPES.map((s) => (
                  <div key={s.kind} className="shape-cell">
                    <button className="sm" onClick={() => create(s.kind)}>
                      {s.label}
                    </button>
                    <button className="ghost sm" disabled={!focusNodeId} onClick={() => branch(s.kind)}>
                      branch
                    </button>
                  </div>
                ))}
              </div>
            </details>
          </section>
        </>
      ) : (
        <>
          <div className="map-head">
            <span className="ttl">Idea Mind Map</span>
            <span className="spacer" />
            <button className="chrome" onClick={() => setView("main")}>
              Minimise
            </button>
          </div>
          {/* tree-wrap: full-bleed, flex:1, no overflow:auto so the pan layer is
              the only scroll mechanism. min-height:0 is critical for flex shrink. */}
          <section className="tree-wrap">
            <IdeaTree />
          </section>
        </>
      )}

      <div className="mic-dock">
        <MicPill
          listening={listening}
          disabled={!voiceSupported}
          hint={micHint}
          onTap={toggleMic}
          onHold={() => setReactOpen(true)}
        />
      </div>

      {reactOpen && (
        <ReactionMenu
          focusLabel={focusedDrawable?.label ?? null}
          canReact={!!focusedDrawable}
          onClose={() => setReactOpen(false)}
          onUtterance={sendUtterance}
        />
      )}
    </div>
  );
}
