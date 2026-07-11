// Entry screens — the ORIION join flow. Purely client-side: these forms only
// decide which room/name the WebSocket `join` frame uses (App.tsx owns the
// socket lifecycle). The server remains the sole source of session truth
// (RULES.md §4) — nothing here is authoritative state.

import { useState } from "react";

// Cosmetic-only prefill of the participant's display name (flagged per
// RULES.md §4: never session truth — identity always flows form → URL → join).
const NAME_KEY = "oriion.preferred_name";

export function ParticipantJoin({
  onJoin,
}: {
  onJoin: (room: string, name: string) => void;
}) {
  const [name, setName] = useState<string>(() => {
    try {
      return localStorage.getItem(NAME_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [room, setRoom] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const join = () => {
    const n = name.trim();
    const r = room.trim().toLowerCase();
    if (!n) return setErr("Enter a display name.");
    if (!r) return setErr("Enter the room key shared on the big screen.");
    try {
      localStorage.setItem(NAME_KEY, n);
    } catch {
      /* cosmetic only */
    }
    onJoin(r, n);
  };

  return (
    <div className="form-wrap">
      <div className="brand-xl">ORIION</div>
      <div className="brand-sub">Meeting Alignment</div>
      <div className="brand-note">Join your room — the conversation is the input device.</div>
      <div className="form-card sk lg">
        <div className="lab-field">Display name</div>
        <input
          className="app-in"
          style={{ width: "100%" }}
          placeholder="e.g. alice"
          value={name}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            setName(e.target.value);
            setErr(null);
          }}
        />
        <div className="lab-field">Room key</div>
        <input
          className="app-in keyish"
          style={{ width: "100%" }}
          placeholder="demo"
          value={room}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            setRoom(e.target.value);
            setErr(null);
          }}
          onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && join()}
        />
        {err && <div className="form-err">{err}</div>}
        <button className="wide" style={{ marginTop: 14 }} onClick={join}>
          Join Meeting
        </button>
      </div>
      <div className="foot-note">
        Everyone on the same room key shares one live board. Open <b>/display</b> on the big
        screen.
      </div>
    </div>
  );
}

export function DisplayJoin({ onJoin }: { onJoin: (room: string) => void }) {
  const [room, setRoom] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const show = () => {
    const r = room.trim().toLowerCase();
    if (!r) return setErr("Enter the room to display.");
    onJoin(r);
  };

  return (
    <div className="form-wrap">
      <div className="brand-xl">ORIION</div>
      <div className="brand-sub">Shared Display</div>
      <div className="brand-note">Show a room's live idea board on this screen.</div>
      <div className="form-card sk lg" style={{ textAlign: "center" }}>
        <div className="lab-field" style={{ textAlign: "left" }}>
          Room key
        </div>
        <input
          className="app-in keyish"
          style={{ width: "100%" }}
          placeholder="demo"
          value={room}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            setRoom(e.target.value);
            setErr(null);
          }}
          onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && show()}
        />
        {err && <div className="form-err">{err}</div>}
        <button className="wide" style={{ marginTop: 14 }} onClick={show}>
          Show Room
        </button>
      </div>
      <div className="foot-note">View-only: this screen reflects the room; phones hold the controls.</div>
    </div>
  );
}
