import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Static-build compatible output for Cloudflare Pages.
// Base is relative so the app can be served from any sub-path.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2021",
  },
  server: {
    port: 4180,
  },
});
