/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The SPA calls the API on the same origin under /api (nginx proxies it in the
// containers, #10). In `npm run dev` Vite does the same; the target is configurable
// through API_PROXY_TARGET (see .env.example).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": { target: apiTarget, changeOrigin: true },
      },
    },
    preview: {
      proxy: {
        "/api": { target: apiTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: "dist",
    },
    test: {
      environment: "jsdom",
      include: ["tests/**/*.test.{ts,tsx}"],
      setupFiles: ["tests/setup.ts"],
      restoreMocks: true,
      // Form journeys type into many fields; on a loaded host (parallel agents, shared CI runners)
      // they can exceed the 5 s default. Assertions are unchanged; only the time budget grows.
      testTimeout: 30_000,
    },
  };
});
