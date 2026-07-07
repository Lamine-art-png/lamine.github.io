import { defineConfig } from "vitest/config";

// Unit tests run in node and cover pure store logic. External network is disabled
// so representative-fallback tests cannot depend on live API latency or DNS.
export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    environment: "node",
    setupFiles: ["./test/setup.ts"],
  },
});
