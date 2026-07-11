// App shell — picks the role from the URL, opens the single WebSocket, and feeds
// every ServerMessage into the store. Role routing:
//   /            -> Participant (phone)
//   /display     -> Display (HDMI screen, view-only)
// Session (room + name) comes from the URL when present (?room=demo&name=alice),
// otherwise from the ORIION entry screens — which just feed the same state.
// The URL stays the shareable session truth (history.replaceState on join).

import { useEffect, useMemo, useState } from "react";
import { QuorumSocket } from "./ws";
import { useStore } from "./store";
import { ParticipantView } from "./ParticipantView";
import { DisplayView } from "./DisplayView";
import { ParticipantJoin, DisplayJoin } from "./EntryScreens";

function randomHandle(): string {
  const animals = ["fox", "owl", "elk", "wren", "lynx", "crow", "hare", "newt"];
  const a = animals[Math.floor(Math.random() * animals.length)];
  return `${a}-${Math.floor(Math.random() * 90 + 10)}`;
}

interface Session {
  room: string;
  speakerId: string;
}

function roleFromUrl(): "participant" | "display" {
  return location.pathname.replace(/\/+$/, "").endsWith("/display") ? "display" : "participant";
}

/** Session from URL params — null when no ?room, which shows the entry screen. */
function sessionFromUrl(role: "participant" | "display"): Session | null {
  const params = new URLSearchParams(location.search);
  const room = params.get("room");
  if (!room) return null;
  // The display doesn't speak; give it a stable id so it just observes.
  const speakerId = role === "display" ? "display" : (params.get("name") ?? randomHandle());
  return { room, speakerId };
}

export default function App() {
  const role = useMemo(roleFromUrl, []);
  const [session, setSession] = useState<Session | null>(() => sessionFromUrl(role));
  const applyServerMessage = useStore((s) => s.applyServerMessage);
  const setConnected = useStore((s) => s.setConnected);
  const reset = useStore((s) => s.reset);
  const [socket, setSocket] = useState<QuorumSocket | null>(null);

  const room = session?.room ?? null;
  const speakerId = session?.speakerId ?? null;

  // The effect is fully re-runnable: each run owns one socket, cleanup closes
  // it. No "ran once" guard — under React 18 StrictMode the dev double-mount
  // runs effect -> cleanup -> effect, and a guard would leave the second mount
  // with a closed socket and no way to reconnect (the bug that froze the app).
  // A null session (entry screen showing) simply means no socket yet.
  useEffect(() => {
    if (room === null || speakerId === null) {
      setSocket(null);
      return;
    }
    reset(room);
    const s = new QuorumSocket({
      room,
      speakerId,
      role,
      onMessage: applyServerMessage,
      onStatus: setConnected,
    });
    s.connect();
    setSocket(s);
    return () => s.close();
  }, [room, role, speakerId, applyServerMessage, setConnected, reset]);

  const joinParticipant = (r: string, name: string) => {
    history.replaceState(null, "", `/?room=${encodeURIComponent(r)}&name=${encodeURIComponent(name)}`);
    setSession({ room: r, speakerId: name });
  };
  const joinDisplay = (r: string) => {
    history.replaceState(null, "", `/display?room=${encodeURIComponent(r)}`);
    setSession({ room: r, speakerId: "display" });
  };
  const leave = () => {
    history.replaceState(null, "", role === "display" ? "/display" : "/");
    setSession(null);
  };

  if (session === null) {
    return role === "display" ? (
      <DisplayJoin onJoin={joinDisplay} />
    ) : (
      <ParticipantJoin onJoin={joinParticipant} />
    );
  }
  if (role === "display") return <DisplayView />;
  if (!socket) return <div className="loading">connecting…</div>;
  return <ParticipantView socket={socket} speakerId={session.speakerId} onLeave={leave} />;
}
