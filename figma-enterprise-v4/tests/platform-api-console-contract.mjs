import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const mainSource = readFileSync(new URL("../src/main.tsx", import.meta.url), "utf8");
const authSource = readFileSync(new URL("../src/app/components/AuthScreen.tsx", import.meta.url), "utf8");
const verificationSource = readFileSync(new URL("../src/app/components/VerifyEmail.tsx", import.meta.url), "utf8");
const consoleSource = readFileSync(new URL("../src/app/components/PlatformConsole.tsx", import.meta.url), "utf8");
const applicationSource = readFileSync(new URL("../src/app/components/PlatformApplicationGate.tsx", import.meta.url), "utf8");
const safetySource = readFileSync(new URL("../src/app/components/PlatformSafetyNotice.tsx", import.meta.url), "utf8");
const routesSource = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");
const layoutSource = readFileSync(new URL("../src/app/components/MainLayout.tsx", import.meta.url), "utf8");
const clientSource = readFileSync(new URL("../src/app/api/client.ts", import.meta.url), "utf8");
const portalManifest = JSON.parse(readFileSync(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"));
const platformManifest = JSON.parse(readFileSync(new URL("../public/platform.webmanifest", import.meta.url), "utf8"));

const requiredRoutes = [
  "/home", "/projects", "/service-accounts", "/api-keys", "/playground",
  "/usage", "/logs", "/webhooks", "/billing", "/docs", "/live-access",
  "/support", "/settings",
];
for (const route of requiredRoutes) assert.ok(consoleSource.includes(`"${route}"`), `missing Platform console route ${route}`);

assert.ok(routesSource.includes('path: "/platform/*"'), "Enterprise Portal must expose the controlled /platform/* surface");
assert.ok(routesSource.includes('path: "/*", Component: PlatformProduct'), "platform.agroai-pilot.com must receive the standalone product shell");
assert.ok(routesSource.includes('window.location.hostname.toLowerCase() === "platform.agroai-pilot.com"'), "router must select the product by hostname");
assert.ok(routesSource.includes("if (!platformDeveloper) return <PlatformApplicationGate />"), "unenrolled organizations must enter the application gate");
assert.ok(routesSource.includes("<PlatformSafetyNotice />"), "enrolled developers must see the controlled-launch state");
assert.ok(layoutSource.includes('{ name: "Platform API", path: "/platform", icon: Code2 }'), "the Enterprise Portal must expose the unified Platform product to every verified organization");
assert.ok(layoutSource.includes('<NavSection title="Products" items={productItems}'), "Platform API must be presented as a first-class product, not an account utility");
assert.ok(layoutSource.includes('{ name: "API access reviews", path: "/admin/platform-api"'), "internal approval operations must be visibly distinct from the developer console");
assert.ok(!layoutSource.includes('name: "Developers/API"'), "the duplicate legacy developer navigation must be removed");
assert.ok(routesSource.includes('path: "developers/api", element: <Navigate to="/platform" replace />'), "legacy deep links must converge on the unified Platform console");

assert.ok(mainSource.includes('window.location.hostname.toLowerCase() === "platform.agroai-pilot.com"'), "runtime product identity must use the exact standalone hostname");
assert.ok(mainSource.includes('standalonePlatformHost ? "AGRO-AI Platform API" : "AGRO-AI Enterprise Portal"'), "browser and recovery identity must distinguish the two products");
assert.ok(mainSource.includes("document.title = runtimeProductName"), "the standalone browser tab must not retain the Portal title");
assert.ok(mainSource.includes('manifestLink.href = "/platform.webmanifest"'), "the standalone product must use its own install manifest");
assert.equal(portalManifest.name, "AGRO-AI Enterprise Portal", "the existing Portal manifest must remain intact");
assert.equal(platformManifest.name, "AGRO-AI Platform API", "the standalone product must have a distinct manifest identity");
assert.equal(platformManifest.start_url, "/");
assert.equal(platformManifest.scope, "/");
assert.notEqual(platformManifest.short_name, portalManifest.short_name, "installed products must not have identical labels");

assert.ok(authSource.includes('window.location.hostname.toLowerCase() === "platform.agroai-pilot.com"'), "authentication must identify the standalone hostname exactly");
assert.ok(authSource.includes("Build on AGRO-AI."), "the standalone hostname must present Platform product positioning");
assert.ok(authSource.includes("Platform API enrollment remains a separate reviewed step after sign-in."), "account verification and API enrollment must remain distinct");
assert.ok(authSource.includes("It does not approve Platform API enrollment, issue API keys, enable live providers, activate billing, or authorize physical actions."), "registration must deny implied API activation");
assert.ok(authSource.includes("AGRO-AI Enterprise Portal"), "the shared auth implementation must preserve Enterprise Portal identity");

assert.ok(verificationSource.includes('query.get("product") === "platform_api"'), "verification may recognize only the fixed Platform product marker");
assert.ok(verificationSource.includes("confirmVerification(token)"), "verification must adopt the authenticated session through the shared auth provider");
assert.ok(verificationSource.includes('platformFlow ? (platformHostname ? "/" : "/platform") : "/"'), "Platform verification must return to a fixed first-party product path");
assert.ok(verificationSource.includes("window.history.replaceState"), "the single-use verification token must be removed from browser history");
assert.ok(!verificationSource.includes("return_to"), "verification must not support a caller-controlled return URL");
assert.ok(!verificationSource.includes("redirect_uri"), "verification must not support a caller-controlled redirect URI");
assert.ok(!verificationSource.includes("window.location.search).get(\"next\")"), "verification must not accept an arbitrary next target");
assert.ok(verificationSource.includes("Platform API enrollment"), "the verification UI must preserve the separate enrollment boundary");

assert.ok(applicationSource.includes('apiClient.get("/v1/platform/applications")'), "application status must come from the existing backend");
assert.ok(applicationSource.includes('apiClient.post("/v1/platform/applications"'), "applications must use the reviewed backend contract");
assert.ok(applicationSource.includes('application_type: "developer_beta"'), "the public gate must submit only developer-beta applications");
assert.ok(applicationSource.includes('requested_environment: "test"'), "the public gate must remain test-only");
assert.ok(!applicationSource.includes('requested_environment: "live"'), "the application gate must never request live access");
assert.ok(!applicationSource.includes("createProject("), "the application gate must not create a project");
assert.ok(!applicationSource.includes("createKey("), "the application gate must not issue a key");
assert.ok(applicationSource.includes("Submission creates a review record only."), "application non-approval semantics must be visible");
assert.ok(applicationSource.includes("Application approval never grants automatic live access or physical execution."), "live and physical boundaries must be visible before submission");
assert.ok(applicationSource.includes("/additional-information"), "needs-information responses must use the audited backend application lifecycle");
assert.ok(applicationSource.includes("document_references: []"), "additional information must not invent unverified document references");
assert.ok(applicationSource.includes("encodeURIComponent(application.id)"), "application identifiers must be encoded before entering a URL path");
assert.ok(applicationSource.includes("TERMINAL_STATUSES"), "terminal applications must be distinguished from active review records");
assert.ok(applicationSource.includes("You can submit a new corrected application."), "terminal decisions must not permanently block reapplication");
assert.ok(!applicationSource.includes("mailto:support@agroai-pilot.com?subject=Platform%20API%20application%20information"), "needs-information responses must not leave the audited workflow for email");

assert.ok(consoleSource.includes("Permanent API keys never enter browser JavaScript."), "Playground must state the browser-secret boundary");
assert.ok(consoleSource.includes("/v1/platform/developer/playground/execute"), "Playground must use the authenticated server-mediated endpoint");
assert.ok(consoleSource.includes("portal_session_synthetic") || consoleSource.includes("Server-mediated"), "Playground must remain synthetic/server-mediated");
assert.ok(!consoleSource.includes('type="password"'), "Platform console must not render an API-key/password input");
assert.ok(!consoleSource.includes("sessionStorage"), "Platform console must not persist credentials in sessionStorage");
assert.ok(!consoleSource.includes("localStorage"), "Platform console must not directly persist credentials in localStorage");
assert.ok(!/agro_(?:test|live)_[A-Za-z0-9_-]{16,}/.test(consoleSource), "Platform console must not contain a complete hardcoded API credential");
assert.ok(!/Authorization:\s*Bearer\s+agro_(?:test|live)_/i.test(consoleSource), "Platform console must not embed a concrete API credential in an Authorization header");
assert.ok(consoleSource.includes("agro_test_") && consoleSource.includes("agro_live_"), "documentation may truthfully name the reviewed key prefixes");

assert.ok(consoleSource.includes("Reset the deterministic sandbox for"), "sandbox reset must require explicit confirmation");
assert.ok(consoleSource.includes("Event delivery will stop until the endpoint is explicitly re-enabled."), "webhook disablement must require explicit confirmation");
assert.ok(consoleSource.includes("The server did not return the one-time secret."), "empty one-time-secret responses must fail visibly");
assert.ok(consoleSource.includes('aria-live="assertive"'), "one-time-secret failures must be announced accessibly");
assert.ok(consoleSource.includes("function ActionError"), "write operations must expose a consistent inline error surface");
for (const fallback of [
  "Sandbox reset failed.",
  "Service account creation failed.",
  "API key creation failed.",
  "API key rotation failed.",
  "API key revocation failed.",
  "Webhook creation failed.",
  "Webhook secret rotation failed.",
  "Webhook disablement failed.",
]) {
  assert.ok(consoleSource.includes(fallback), `missing visible write failure contract: ${fallback}`);
}

for (const capability of ["projects()", "serviceAccounts()", "keys()", "usage()", "requestLogs()", "webhooks()"]) {
  assert.ok(consoleSource.includes(`apiClient.platformDeveloper.${capability}`), `console must use existing control-plane capability ${capability}`);
}
assert.ok(clientSource.includes('platformDeveloper: {'), "existing API client must remain the control-plane source");
assert.ok(consoleSource.includes("No self-service charges are active."), "billing must remain truthful when disabled");
assert.ok(consoleSource.includes("Live-access requests are not enabled"), "live access must remain truthful when disabled");
assert.ok(safetySource.includes("Physical execution disabled"), "physical-action safety state must be visible");
assert.ok(safetySource.includes("Automatic live approval disabled"), "automatic live approval must remain visibly disabled");
assert.ok(safetySource.includes("Test data isolated"), "test-data isolation must remain visibly stated");

console.log(`Platform API product contract passed: ${requiredRoutes.length} console routes, distinct runtime product identity, host-specific auth, redirect-safe verification, reviewed application and reapplication lifecycle, keyless Playground, visible write failures, destructive-action confirmations, and controlled-launch boundaries.`);
