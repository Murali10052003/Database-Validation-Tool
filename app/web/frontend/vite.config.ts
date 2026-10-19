import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev runs at "/" with an /api proxy to the FastAPI backend.
// Production builds under "/static/" so FastAPI can serve the bundle from its
// existing static mount (see app/main.py).
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/static/" : "/",
  build: {
    outDir: "../static",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
}));
