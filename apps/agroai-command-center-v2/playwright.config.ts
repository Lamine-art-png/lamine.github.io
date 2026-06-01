import { defineConfig, devices } from "@playwright/test";

// E2E coverage across the four required breakpoints. The webServer builds the
// static bundle and serves it the same way Cloudflare Pages would.
export default defineConfig({
  testDir: "./test",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4180",
    trace: "off",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://localhost:4180",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "laptop-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "tablet-1024", use: { ...devices["Desktop Chrome"], viewport: { width: 1024, height: 768 } } },
    { name: "mobile-390", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } } },
  ],
});
