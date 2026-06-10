// Reconnecting WebSocket client — the single channel to the gateway.
// Holds no state of its own; it forwards parsed ServerMessages to a callback and
// lets callers send ClientMessages. (Server is the source of truth — RULES.md §4.)

import type { ClientMessage, ServerMessage } from "./protocol";

type OnMessage = (msg: ServerMessage) => void;
type OnStatus = (connected: boolean) => void;

export interface WsOptions {
  room: string;
  speakerId: string;
  role: "participant" | "display";
  displayName?: string;
  onMessage: OnMessage;
  onStatus?: OnStatus;
}

function wsUrl(): string {
  // Same-origin: Vite proxies /ws to the backend in dev; in prod the gateway
  // serves it directly. Works for phones hitting the LAN IP unchanged.
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

export class QuorumSocket {
  private ws: WebSocket | null = null;
  private opts: WsOptions;
  private closedByUser = false;
  private backoff = 500;

  constructor(opts: WsOptions) {
    this.opts = opts;
  }

  connect(): void {
    this.closedByUser = false;
    const ws = new WebSocket(wsUrl());
    this.ws = ws;

    ws.onopen = () => {
      this.backoff = 500;
      this.opts.onStatus?.(true);
      // First frame must be the join handshake.
      this.send({
        type: "join",
        room: this.opts.room,
        role: this.opts.role,
        speaker_id: this.opts.speakerId,
        display_name: this.opts.displayName,
      });
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as ServerMessage;
        this.opts.onMessage(msg);
      } catch {
        // ignore malformed frame
      }
    };

    ws.onclose = () => {
      this.opts.onStatus?.(false);
      if (!this.closedByUser) {
        setTimeout(() => this.connect(), this.backoff);
        this.backoff = Math.min(this.backoff * 2, 8000);
      }
    };

    ws.onerror = () => ws.close();
  }

  send(msg: ClientMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  close(): void {
    this.closedByUser = true;
    this.ws?.close();
  }
}
