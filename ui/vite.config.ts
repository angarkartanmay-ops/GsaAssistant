import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Builds straight into the Python server's static folder, so `python -m havoc run`
// serves the new UI with no Node at runtime. `npm run dev` proxies to a running HAVOC.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/app/",
  build: { outDir: "../havoc/server/static/app", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7777",
      "/ws": { target: "ws://127.0.0.1:7777", ws: true },
    },
  },
});
