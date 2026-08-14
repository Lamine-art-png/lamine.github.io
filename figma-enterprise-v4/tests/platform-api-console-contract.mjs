import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const mainSource = readFileSync(new URL("../src/main.tsx", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../src/app/App.tsx", import.meta.url), "utf8");
const authSource = readFileSync(new URL("../src/app/components/PlatformAuthScreen.tsx", import.meta.url), "utf8");
const verificationSource = readFileSync(new URL("../src/app/components/VerifyEmail.tsx", import.meta.url), "utf8");
const consoleSource = readFileSync(new URL("../src/app/components/PlatformConsole.tsx", import.meta.url), "utf8");
const applicationSource = readFileSync(new URL("../src/app/components/PlatformApplicationGate.tsx", import.meta.url), "utf8");
const selfServiceSource = readFileSync(new URL("../src/app/components/PlatformSelfServiceGate.tsx", import.meta.url), "utf8");
const cliApprovalSource = readFileSync(new URL("../src/app/components/PlatformCliDeviceApproval.tsx", import.meta.url), "utf8");
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
assert.ok(routesSource.includes("if (!platformDeveloper) return <PlatformSelfServiceGate />"), "unenrolled Platform users must enter the self-service-aware gate");
assert.ok(routesSource.match(/path: "\/cli", Component: PlatformCliDeviceApproval/g)?.length === 2, "CLI approval must be reachable on both product hosts");
assert.ok(routesSource.includes("<PlatformSafetyNotice />"), "enrolled developers must see the controlled-launch state");
assert.ok(layoutSource.includes('{ name: "Platform API", path: "/platform", icon: Code2 }'), "Enterprise Portal must expose the unified Platform product");
assert.ok(layoutSource.includes('<NavSection title="Products" items={productItems}'), "Platform API must be a first-class product");
assert.ok(layoutSource.includes('{ name: "API access reviews", path: "/admin/platform-api"'), "internal review operations must remain distinct");
assert.ok(!layoutSource.includes('name: "Developers/API"'), "duplicate legacy developer navigation must remain removed");

assert.ok(mainSource.includes('standalonePlatformHost ? "AGRO-AI Platform API" : "AGRO-AI Enterprise Portal"'), "runtime identity must distinguish products");
assert.ok(mainSource.includes("Verified developers can activate bounded TEST access after accepting the current developer agreements."), "runtime identity must describe TEST self-service truthfully");
assert.ok(mainSource.includes("Permanent API keys never enter browser JavaScript."), "runtime identity must preserve the browser-secret boundary");
assert.ok(appSource.includes("standalonePlatformHost ? <PlatformAuthScreen /> : <AuthScreen />"), "standalone Platform must have dedicated developer onboarding copy");
assert.equal(portalManifest.name, "AGRO-AI Enterprise Portal");
assert.equal(platformManifest.name, "AGRO-AI Platform API");
assert.equal(platformManifest.start_url, "/");
assert.equal(platformManifest.scope, "/");

assert.ok(authSource.includes("Build on AGRO-AI."), "standalone developer auth must present Platform positioning");
assert.ok(authSource.includes("No sales call or manual API-access review for eligible TEST developers."), "developer onboarding must state the self-service TEST path");
assert.ok(authSource.includes("Automated screening protects the developer platform."), "organization verification must remain a security boundary");
assert.ok(authSource.includes("Account creation does not enable LIVE projects"), "registration must deny implied LIVE activation");
assert.ok(authSource.includes("accept the current developer agreements"), "onboarding must state the legal acceptance boundary");

assert.ok(selfServiceSource.includes('apiClient.get("/v1/platform/terms")'), "self-service must load the effective legal catalog from the server");
assert.ok(selfServiceSource.includes('document.legal_review_status !== "approved_effective"'), "self-service must fail closed on unapproved legal documents");
assert.ok(selfServiceSource.includes('apiClient.post("/v1/platform/terms/accept"'), "agreement acceptance must be versioned and server-side");
assert.ok(selfServiceSource.includes("await refreshMe()"), "legal acceptance must refresh the server-authoritative enrollment state");
assert.ok(selfServiceSource.includes("return <PlatformApplicationGate />"), "legacy reviewed enrollment remains a fail-closed fallback before launch");
assert.ok(selfServiceSource.includes("TEST access never grants live provider credentials"), "self-service must state the TEST/LIVE boundary");

assert.ok(cliApprovalSource.includes('apiClient.post("/v1/platform/cli/device/approve"'), "browser must approve the CLI device code through the first-party backend");
assert.ok(cliApprovalSource.includes('apiClient.post("/v1/platform/terms/accept"'), "new public CLI users must accept the effective developer agreements");
assert.ok(cliApprovalSource.includes("apiClient.platformDeveloper.overview()"), "CLI approval must trigger/check bounded TEST enrollment before authorization");
assert.ok(cliApprovalSource.includes("Return to the terminal"), "successful browser approval must hand control back to the terminal");
assert.ok(!cliApprovalSource.includes("AGROAI_API_KEY"), "browser device approval must never ask for a machine API key");

assert.ok(verificationSource.includes('query.get("product") === "platform_api"'), "verification may recognize only the fixed Platform product marker");
assert.ok(verificationSource.includes("confirmVerification(token)"), "verification must adopt the authenticated session through the shared auth provider");
assert.ok(verificationSource.includes('platformFlow ? (platformHostname ? "/" : "/platform") : "/"'), "Platform verification must return to a fixed first-party path");
assert.ok(verificationSource.includes("window.history.replaceState"), "single-use verification tokens must leave browser history");
assert.ok(!verificationSource.includes("return_to"));
assert.ok(!verificationSource.includes("redirect_uri"));

// Private-beta review remains available strictly as the fail-closed fallback.
assert.ok(applicationSource.includes('apiClient.get("/v1/platform/applications")'));
assert.ok(applicationSource.includes('application_type: "developer_beta"'));
assert.ok(applicationSource.includes('requested_environment: "test"'));
assert.ok(!applicationSource.includes('requested_environment: "live"'));
assert.ok(!applicationSource.includes("createProject("));
assert.ok(!applicationSource.includes("createKey("));
assert.ok(applicationSource.includes("Application approval never grants automatic live access or physical execution."));

assert.ok(consoleSource.includes("Permanent API keys never enter browser JavaScript."), "Playground must state the browser-secret boundary");
assert.ok(consoleSource.includes("/v1/platform/developer/playground/execute"), "Playground must use the server-mediated endpoint");
assert.ok(!consoleSource.includes('type="password"'), "Platform console must not render an API-key/password input");
assert.ok(!consoleSource.includes("sessionStorage"), "Platform console must not persist credentials in sessionStorage");
assert.ok(!consoleSource.includes("localStorage"), "Platform console must not directly persist credentials in localStorage");
assert.ok(!/Authorization:\s*Bearer\s+agro_(?:test|live)_/i.test(consoleSource));
assert.ok(consoleSource.includes("agro_test_") && consoleSource.includes("agro_live_"));

for (const capability of ["projects()", "serviceAccounts()", "keys()", "usage()", "requestLogs()", "webhooks()"]) {
  assert.ok(consoleSource.includes(`apiClient.platformDeveloper.${capability}`), `console must use existing control-plane capability ${capability}`);
}
assert.ok(clientSource.includes('platformDeveloper: {'));
assert.ok(consoleSource.includes("No self-service charges are active."), "billing must remain truthful while disabled");
assert.ok(consoleSource.includes("Live-access requests are not enabled"), "live access must remain truthful while disabled");
assert.ok(safetySource.includes("Physical execution disabled"));
assert.ok(safetySource.includes("Automatic live approval disabled"));
assert.ok(safetySource.includes("Test data isolated"));

console.log(`Platform API product contract passed: ${requiredRoutes.length} console routes, public TEST self-service, dedicated developer auth, CLI browser approval, legal-catalog enforcement, private-beta fallback, keyless Playground, and fail-closed LIVE/physical boundaries.`);
