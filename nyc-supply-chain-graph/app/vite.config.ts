import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  // MapLibre alone is about 1 MB minified; the app is one page, so one bundle is fine.
  build: { chunkSizeWarningLimit: 1500 },
  worker: { format: "es" },
});
