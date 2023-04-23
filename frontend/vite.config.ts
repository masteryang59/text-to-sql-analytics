import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` serves the UI on :5173 and forwards /api to the FastAPI server.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});

export function aggregateStats(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function aggregateStats(data: unknown): unknown {
  if (!data) return null;
  return data;
}