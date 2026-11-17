/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on its own port and Vite forwards /v1 to it, so the
// browser sees one origin, as it does behind the dashboard's own server.
const api = process.env.DPOLENS_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    proxy: { "/v1": { target: api, changeOrigin: false } },
  },
  build: {
    sourcemap: false,
    // Every asset as a file of its own, never a data: URL, so the dashboard's
    // Content-Security-Policy can allow fonts and images from itself alone.
    assetsInlineLimit: 0,
    rolldownOptions: {
      output: {
        // The libraries are two files apart from the dashboard's own code, React
        // and the router in one and the rest in the other, each under the size
        // Vite warns about. They change only when a library is upgraded, so a
        // browser keeps them from one DPOLens release to the next.
        codeSplitting: {
          groups: [
            {
              name: "react",
              test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/,
              priority: 2,
            },
            { name: "vendor", test: /node_modules[\\/]/, priority: 1 },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
