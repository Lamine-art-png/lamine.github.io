import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const consoleSource = readFileSync(new URL("../src/app/components/PlatformConsole.tsx", import.meta.url), "utf8");
const safetySource = readFileSync(new URL("../src/app/components/PlatformSafetyNotice.tsx", import.meta.url), "utf8");
const routesSource = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");
const clientSource = readFileSync(new URL("../src/app/api/client.ts", import.meta.url), "utf8");

const requiredRoutes = [
  "/home",
  "/projects",
  "/service-accounts",
  "/api-keys",
  "/playground",
  "/usage",
  "/logs",
  "/webhooks",
  "/billing",
  "/docs",
  "/live-access",
  "/support",
  "/settings",
];

for (const route of requiredRoutes) {
  assert.ok(consoleSource.includes(`\"${route}\"`), `missing Platform console route ${route}`);
}

assert.ok(routesSource.includes('path: "/platform/*"'), "Enterprise Portal must expose the controlled /platform/* surface");
assert.ok(routesSource.includes('path: "/*", Component: PlatformProduct'), "platform.agroai-pilot.com must receive the standalone product shell");
assert.ok(routesSource.includes('window.location.hostname.toLowerCase() === "platform.agroai-pilot.com"'), "router must select the product by hostname");
assert.ok(routesSource.includes("<PlatformSafetyNotice />"), "the standalone product must render its controlled-launch state");

assert.ok(consoleSource.includes("Permanent API keys never enter browser JavaScript."), "Playground must state the browser-secret boundary");
assert.ok(consoleSource.includes("/v1/platform/developer/playground/execute"), "Playground must use the authenticated server-mediated endpoint");
assert.ok(consoleSource.includes("portal_session_synthetic") || consoleSource.includes("Server-mediated"), "Playground must remain synthetic/server-mediated");
assert.ok(!consoleSource.includes('type="password"'), "Platform console must not render an API-key/password input");
assert.ok(!consoleSource.includes("sessionStorage"), "Platform console must not persist credentials in sessionStorage");
assert.ok(!consoleSource.includes("localStorage"), "Platform console must not directly persist credentials in localStorage");
assert.ok(!consoleSource.includes("agro_test_"), "Platform console must not hardcode a real-looking secret");
assert.ok(!consoleSource.includes("agro_live_"), "Platform console must not hardcode a real-looking secret");

for (const capability of [
  "apiClient.platformDeveloper.projects()",
  "apiClient.platformDeveloper.serviceAccounts()",
  "apiClient.platformDeveloper.keys()",
  "apiClient.platformDeveloper.usage()",
  "apiClient.platformDeveloper.requestLogs()",
  "apiClient.platformDeveloper.webhooks()",
]) {
  assert.ok(consoleSource.includes(capability), `console must use existing control-plane capability ${capability}`);
}

assert.ok(clientSource.includes('platformDeveloper: {'), "existing API client must remain the control-plane source");
assert.ok(consoleSource.includes("No self-service charges are active."), "billing must remain truthful when disabled");
assert.ok(consoleSource.includes("Live-access requests are not enabled"), "live access must remain truthful when disabled");
assert.ok(safetySource.includes("Physical execution disabled"), "physical-action safety state must be visible");
assert.ok(safetySource.includes("Automatic live approval disabled"), "automatic live approval must remain visibly disabled");
assert.ok(safetySource.includes("Test data isolated"), "test-data isolation must remain visibly stated");

console.log(`Platform API console contract passed: ${requiredRoutes.length} product routes, host split, server-mediated Playground, and visible controlled-launch boundaries.`);
