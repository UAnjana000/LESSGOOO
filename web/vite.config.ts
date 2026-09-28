import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// The local Caddy proxy serves a `tls internal` certificate, so allow it when proxying in dev.
const api = { target: process.env.VITE_API_PROXY ?? "https://localhost:8443", changeOrigin: true, secure: false };

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      injectRegister: false,
      injectManifest: { globPatterns: ["**/*.{js,css,html,woff2,svg,png}"], maximumFileSizeToCacheInBytes: 4_000_000 },
      manifest: {
        name: "Dr. B. R. Ambedkar Digital Heritage Archive",
        short_name: "Ambedkar Archive",
        description: "Search and read the archive's approved sources, with citations to the original pages.",
        start_url: "/",
        display: "fullscreen",
        orientation: "landscape",
        background_color: "#eef1f7",
        theme_color: "#1b2a6b",
        icons: [
          { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
          { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    host: "0.0.0.0",
    port: 5173,
    watch: {
      usePolling: true,
      interval: 100,
    },
    proxy: { "/api": api, "/iiif": api },
  },
  test: { environment: "jsdom" },
});
