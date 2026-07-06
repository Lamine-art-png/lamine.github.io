import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: /.*\.e2e\.spec\.ts/,
  timeout: 30000,
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:4177", trace: "retain-on-failure" },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4177",
    url: "http://127.0.0.1:4177",
    reuseExistingServer: false,
    timeout: 120000,
  },
});
