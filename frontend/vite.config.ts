import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend gateway runs on :8000. In dev we proxy /ws and /api to it so the
// browser talks to one origin (no CORS surprises) and a phone on the LAN can hit
// the Vite host directly. RULES.md §4: all realtime data over the single WS.
// Override the backend port with VITE_BACKEND_PORT when :8000 is taken.
const BACKEND_PORT = process.env.VITE_BACKEND_PORT ?? "8000";
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on 0.0.0.0 so phones can reach it by LAN IP
    port: 5173,
    proxy: {
      "/ws": { target: `ws://localhost:${BACKEND_PORT}`, ws: true, changeOrigin: true },
      "/api": {
        target: `http://localhost:${BACKEND_PORT}`,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
