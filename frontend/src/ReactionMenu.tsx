// ReactionMenu — the ORIION tap-and-hold reaction surface.
//
// Every reaction is sent as a PLAIN UTTERANCE over the existing WebSocket, so
// the conversation stays the input device and each reaction is visible in the
// shared transcript (transparency, RULES.md §4). The canned phrases are chosen
// to hit the rules classifier's deterministic preference vocabulary
// (backend/quorum/pipeline/classify.py _PREFERENCE_PHRASES) with the focused
// node as the implicit target (target falls back to focus_node_id):
//
//   Matches      -> "i like the current one"       FOCUS, signal +0.7
//   Partly right -> "maybe the current one"        FOCUS, signal +0.3
//   Wrong        -> "not the current one"          disaffirm, signal -0.6
//                   (two Wrongs cross the -0.8 auto-prune floor — deliberate
//                   group semantics; undo recovers)
//   Unclear      -> "this is unclear, please clarify"  no deterministic rule —
//                   lands in the transcript, escalates to the LLM if configured
//   Alternative  -> prefills the note input with "how about " (a _BRANCH_HINTS
//                   phrase) — the user names the alternative, which branches
//   Ready to Save-> "let's go with this"           FOCUS, signal +1.0 (strongest)
//   + Note       -> the typed text, verbatim

import { useRef, useState } from "react";

export type ReactionKind = "matches" | "partly" | "wrong" | "unclear" | "alt" | "ready" | "note";

export function RxGlyph({ kind }: { kind: ReactionKind }) {
  switch (kind) {
    case "matches":
      return <span className="ic ic-green">✓</span>;
    case "partly":
      return <span className="ic ic-yellow">◐</span>;
    case "wrong":
      return <span className="ic ic-red">✕</span>;
    case "unclear":
      return <span className="ic ic-blue">?</span>;
    case "alt":
      return <span className="ic ic-yellow">💡</span>;
    case "ready":
      return <span className="ic ic-green">👍</span>;
    case "note":
      return <span className="ic ic-plain">+</span>;
  }
}

/** Affirmation tally chip (✓ positive score / ✕ negative score). */
export function Tally({ kind, text }: { kind: ReactionKind; text: string }) {
  return (
    <span className="rx">
      <RxGlyph kind={kind} /> {text}
    </span>
  );
}

const REACTIONS: { kind: ReactionKind; label: string; utterance: string | null }[] = [
  { kind: "matches", label: "Matches", utterance: "i like the current one" },
  { kind: "partly", label: "Partly right", utterance: "maybe the current one" },
  { kind: "wrong", label: "Wrong", utterance: "not the current one" },
  { kind: "unclear", label: "Unclear", utterance: "this is unclear, please clarify" },
  { kind: "alt", label: "Alternative", utterance: null }, // prefills "how about "
  { kind: "ready", label: "Ready to Save", utterance: "let's go with this" },
];

export function ReactionMenu({
  focusLabel,
  canReact,
  onClose,
  onUtterance,
}: {
  focusLabel: string | null;
  canReact: boolean;
  onClose: () => void;
  onUtterance: (text: string) => void;
}) {
  const [note, setNote] = useState("");
  const noteRef = useRef<HTMLInputElement | null>(null);

  const stop = (e: React.PointerEvent | React.MouseEvent) => e.stopPropagation();

  const pick = (r: (typeof REACTIONS)[number]) => {
    if (r.utterance === null) {
      // Alternative: the user must name it — "how about a triangle" branches.
      setNote("how about ");
      noteRef.current?.focus();
      return;
    }
    onUtterance(r.utterance);
    onClose();
  };

  const sendNote = () => {
    const t = note.trim();
    if (!t || t === "how about") return onClose();
    onUtterance(t);
    onClose();
  };

  return (
    <>
      <div className="scrim" onClick={onClose} onPointerDown={stop} />
      <div className="rx-menu" onPointerDown={stop} onClick={stop}>
        <div className="rh">
          <b>React to: {focusLabel ?? "current visual"}</b>
        </div>
        <div className="rx-grid">
          {REACTIONS.map((r) => (
            <button
              type="button"
              className="rx-opt"
              key={r.kind}
              disabled={!canReact}
              title={canReact ? r.label : "no visual to react to yet"}
              onClick={() => pick(r)}
            >
              <span className="big">
                <RxGlyph kind={r.kind} />
              </span>
              <span>{r.label}</span>
            </button>
          ))}
        </div>
        <div className="rx-bot">
          <input
            ref={noteRef}
            className="app-in"
            placeholder="Add a note or correction…"
            value={note}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNote(e.target.value)}
            onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && sendNote()}
          />
          <button type="button" className="sm" onClick={sendNote}>
            Send
          </button>
        </div>
        <div className="rx-note-hint">
          {canReact
            ? "Your reaction is spoken for you — it appears in the shared transcript."
            : "No idea in focus yet — say a shape to begin."}
        </div>
      </div>
    </>
  );
}
