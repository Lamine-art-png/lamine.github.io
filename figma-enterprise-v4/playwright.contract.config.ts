import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: /.*\.spec\.mjs/,
  timeout: 30000,
  reporter: "line",
  fullyParallel: false,
  workers: 1,
  use: {
    trace: "retain-on-failure",
  },
});
