import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/t": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/auth": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin/menu-categories": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin/menu-items": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin/tables": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin/settings": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin/staff": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin/sessions": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin/reports": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/tables": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/kitchen": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // WebSocket endpoints (/ws/kitchen, /ws/t/{qr_token}).
      // `ws: true` is required — without it the handshake is not proxied and
      // the client reconnect loop spins forever against the Vite dev server.
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
