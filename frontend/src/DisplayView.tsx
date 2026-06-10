// Display view — the HDMI'd screen. View-only, fullscreen, minimal chrome,
// calm and big (plan.md §7: "Display view ≠ participant view"). No controls;
// it only reflects broadcast state.

import { useStore } from "./store";
import { IdeaTree } from "./IdeaTree";

export function DisplayView() {
  const room = useStore((s) => s.room);
  const status = useStore((s) => s.status);
  const statusSpeaker = useStore((s) => s.statusSpeaker);
  const connected = useStore((s) => s.connected);
  const count = useStore((s) => Object.keys(s.nodes).length);

  return (
    <div className="display">
      <header className="display-bar">
        <span className="brand big">Quorum</span>
        <span className="room">room · {room || "…"}</span>
        <span className={`dot ${connected ? "on" : "off"}`} />
      </header>

      <main className="display-stage">
        <IdeaTree big />
      </main>

      <footer className="display-foot">
        {status !== "idle" ? (
          <span className="live">
            {statusSpeaker ? `${statusSpeaker} ` : ""}
            {status}…
          </span>
        ) : (
          <span className="idle">{count} idea{count === 1 ? "" : "s"} on the board</span>
        )}
      </footer>
    </div>
  );
}
