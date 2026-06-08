/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The Python server (`pflow ui`) serves the built bundle from src/pflow/ui/static/.
// `base: "./"` makes asset URLs relative so it serves correctly from "/".
// In dev, run `pflow ui` on PFLOW_UI_PORT (default 8765) and `npm run dev` here;
// the proxy forwards /api to the live backend so the React app hot-reloads against it.
const apiPort = process.env.PFLOW_UI_PORT ?? "8765";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/pflow/ui/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
