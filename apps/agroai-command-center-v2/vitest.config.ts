import { defineConfig } from "vitest/config";

// Unit tests run in node and cover pure store logic.
// Playwright e2e specs (*.spec.ts) are excluded here and run via test:e2e.
export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    environment: "node",
  },
});
