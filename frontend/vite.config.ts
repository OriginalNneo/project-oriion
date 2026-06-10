import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend gateway runs on :8000. In dev we proxy /ws and /api to it so the
// browser talks to one origin (no CORS surprises) and a phone on the LAN can hit
// the Vite host directly. RULES.md §4: all realtime data over the single WS.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on 0.0.0.0 so phones can reach it by LAN IP
    port: 5173,
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true, changeOrigin: true },
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
