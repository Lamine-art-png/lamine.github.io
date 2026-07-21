import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const authSource = readFileSync(new URL("../src/app/components/AuthScreen.tsx", import.meta.url), "utf8");
const consoleSource = readFileSync(new URL("../src/app/components/PlatformConsole.tsx", import.meta.url), "utf8");
const applicationSource = readFileSync(new URL("../src/app/components/PlatformApplicationGate.tsx", import.meta.url), "utf8");
const safetySource = readFileSync(new URL("../src/app/components/PlatformSafetyNotice.tsx", import.meta.url), "utf8");
const routesSource = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");
const clientSource = readFileSync(new URL("../src/app/api/client.ts", import.meta.url), "utf8");

const requiredRoutes = [
  "/home", "/projects", "/service-accounts", "/api-keys", "/playground",
  "/usage", "/logs", "/webhooks", "/billing", "/docs", "/live-access",
  "/support", "/settings",
];
for (const route of requiredRoutes) assert.ok(consoleSource.includes(`\"${route}\"`), `missing Platform console route ${route}`);

assert.ok(routesSource.includes('path: "/platform/*"'), "Enterprise Portal must expose the controlled /platform/* surface");
assert.ok(routesSource.includes('path: "/*", Component: PlatformProduct'), "platform.agroai-pilot.com must receive the standalone product shell");
assert.ok(routesSource.includes('window.location.hostname.toLowerCase() === "platform.agroai-pilot.com"'), "router must select the product by hostname");
assert.ok(routesSource.includes("if (!platformDeveloper) return <PlatformApplicationGate />"), "unenrolled organizations must enter the application gate");
assert.ok(routesSource.includes("<PlatformSafetyNotice />"), "enrolled developers must see the controlled-launch state");

assert.ok(authSource.includes('window.location.hostname.toLowerCase() === "platform.agroai-pilot.com"'), "authentication must identify the standalone hostname exactly");
assert.ok(authSource.includes("Build on AGRO-AI."), "the standalone hostname must present Platform product positioning");
assert.ok(authSource.includes("Platform API enrollment remains a separate reviewed step after sign-in."), "account verification and API enrollment must remain distinct");
assert.ok(authSource.includes("It does not approve Platform API enrollment, issue API keys, enable live providers, activate billing, or authorize physical actions."), "registration must deny implied API activation");
assert.ok(authSource.includes("AGRO-AI Enterprise Portal"), "the shared auth implementation must preserve Enterprise Portal identity");

assert.ok(applicationSource.includes('apiClient.get("/v1/platform/applications")'), "application status must come from the existing backend");
assert.ok(applicationSource.includes('apiClient.post("/v1/platform/applications"'), "applications must use the reviewed backend contract");
assert.ok(applicationSource.includes('application_type: "developer_beta"'), "the public gate must submit only developer-beta applications");
assert.ok(applicationSource.includes('requested_environment: "test"'), "the public gate must remain test-only");
assert.ok(!applicationSource.includes('requested_environment: "live"'), "the application gate must never request live access");
assert.ok(!applicationSource.includes("createProject("), "the application gate must not create a project");
assert.ok(!applicationSource.includes("createKey("), "the application gate must not issue a key");
assert.ok(applicationSource.includes("Submission creates a review record only."), "application non-approval semantics must be visible");
assert.ok(applicationSource.includes("Application approval never grants automatic live access or physical execution."), "live and physical boundaries must be visible before submission");

assert.ok(consoleSource.includes("Permanent API keys never enter browser JavaScript."), "Playground must state the browser-secret boundary");
assert.ok(consoleSource.includes("/v1/platform/developer/playground/execute"), "Playground must use the authenticated server-mediated endpoint");
assert.ok(consoleSource.includes("portal_session_synthetic") || consoleSource.includes("Server-mediated"), "Playground must remain synthetic/server-mediated");
assert.ok(!consoleSource.includes('type="password"'), "Platform console must not render an API-key/password input");
assert.ok(!consoleSource.includes("sessionStorage"), "Platform console must not persist credentials in sessionStorage");
assert.ok(!consoleSource.includes("localStorage"), "Platform console must not directly persist credentials in localStorage");
assert.ok(!/agro_(?:test|live)_[A-Za-z0-9_-]{16,}/.test(consoleSource), "Platform console must not contain a complete hardcoded API credential");
assert.ok(!/Authorization:\s*Bearer\s+agro_(?:test|live)_/i.test(consoleSource), "Platform console must not embed a concrete API credential in an Authorization header");
assert.ok(consoleSource.includes("agro_test_") && consoleSource.includes("agro_live_"), "documentation may truthfully name the reviewed key prefixes");

for (const capability of ["projects()", "serviceAccounts()", "keys()", "usage()", "requestLogs()", "webhooks()"]) {
  assert.ok(consoleSource.includes(`apiClient.platformDeveloper.${capability}`), `console must use existing control-plane capability ${capability}`);
}
assert.ok(clientSource.includes('platformDeveloper: {'), "existing API client must remain the control-plane source");
assert.ok(consoleSource.includes("No self-service charges are active."), "billing must remain truthful when disabled");
assert.ok(consoleSource.includes("Live-access requests are not enabled"), "live access must remain truthful when disabled");
assert.ok(safetySource.includes("Physical execution disabled"), "physical-action safety state must be visible");
assert.ok(safetySource.includes("Automatic live approval disabled"), "automatic live approval must remain visibly disabled");
assert.ok(safetySource.includes("Test data isolated"), "test-data isolation must remain visibly stated");

console.log(`Platform API product contract passed: ${requiredRoutes.length} console routes, host-specific auth, reviewed application gate, keyless Playground, and visible controlled-launch boundaries.`);
