// App shell — picks the role from the URL, opens the single WebSocket, and feeds
// every ServerMessage into the store. Role routing:
//   /            -> Participant (phone)
//   /display     -> Display (HDMI screen, view-only)
// Query params: ?room=demo&name=alice  (speaker_id defaults to a random handle).

import { useEffect, useMemo, useRef, useState } from "react";
import { QuorumSocket } from "./ws";
import { useStore } from "./store";
import { ParticipantView } from "./ParticipantView";
import { DisplayView } from "./DisplayView";

function randomHandle(): string {
  const animals = ["fox", "owl", "elk", "wren", "lynx", "crow", "hare", "newt"];
  const a = animals[Math.floor(Math.random() * animals.length)];
  return `${a}-${Math.floor(Math.random() * 90 + 10)}`;
}

function useSession() {
  return useMemo(() => {
    const params = new URLSearchParams(location.search);
    const isDisplay = location.pathname.replace(/\/+$/, "").endsWith("/display");
    const room = params.get("room") ?? "demo";
    const role: "participant" | "display" = isDisplay ? "display" : "participant";
    // The display doesn't speak; give it a stable id so it just observes.
    const speakerId = isDisplay ? "display" : params.get("name") ?? randomHandle();
    return { room, role, speakerId };
  }, []);
}

export default function App() {
  const { room, role, speakerId } = useSession();
  const applyServerMessage = useStore((s) => s.applyServerMessage);
  const setConnected = useStore((s) => s.setConnected);
  const reset = useStore((s) => s.reset);
  const [socket, setSocket] = useState<QuorumSocket | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
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

  if (role === "display") return <DisplayView />;
  if (!socket) return <div className="loading">connecting…</div>;
  return <ParticipantView socket={socket} speakerId={speakerId} />;
}
