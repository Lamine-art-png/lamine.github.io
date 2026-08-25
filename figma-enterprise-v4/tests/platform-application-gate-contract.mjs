import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/components/PlatformApplicationGate.tsx", import.meta.url), "utf8");
const selfService = readFileSync(new URL("../src/app/components/PlatformSelfServiceGate.tsx", import.meta.url), "utf8");
const routes = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");

assert.ok(source.includes('const canManageApplication = ["owner", "admin"].includes(organizationRole)'), "application management must be limited in the UI to organization owners and admins");
assert.ok(source.includes("if (!canManageApplication) return <RoleGate"), "non-admin members must receive a deliberate role boundary before the application form");
assert.ok(source.includes("if (!canManageApplication) { setLoading(false); setApplications([]); setAvailable(false); setError(\"\"); return; }"), "non-admin members must not call the protected application-list endpoint");
assert.ok(source.includes("if (!canManageApplication) return; setSubmitting(true)"), "the submit handler must retain a client-side role guard in addition to backend authorization");
assert.ok(source.includes("application.decision_reason"), "needs-information applications must surface the reviewer reason when the backend provides it");
assert.ok(source.includes("/additional-information"), "reviewer follow-up must remain inside the audited application lifecycle");
assert.ok(source.includes("document_references: []"), "the follow-up UI must not fabricate uploaded evidence references");
assert.ok(!source.includes("mailto:support@agroai-pilot.com?subject=Platform%20API%20application%20information"), "review follow-up must not escape into unaudited email");

assert.ok(routes.includes('import { PlatformSelfServiceGate } from "./components/PlatformSelfServiceGate"'), "unenrolled Platform users must enter the self-service-aware gate");
assert.ok(routes.includes("if (!platformDeveloper) return <PlatformSelfServiceGate />"), "the standalone Platform route must not force public developers into the legacy application flow");
assert.ok(selfService.includes('apiClient.get("/v1/platform/terms")'), "self-service must load the server-authoritative effective legal catalog");
assert.ok(selfService.includes('item.legal_review_status !== "approved_effective"'), "the UI must fail closed when any required legal document is not effective");
assert.ok(selfService.includes('apiClient.post("/v1/platform/terms/accept"'), "self-service must record versioned legal acceptance server-side");
assert.ok(selfService.includes("await refreshMe()"), "successful acceptance must refresh the authenticated enrollment state");
assert.ok(selfService.includes("if (apiError?.status === 404)"), "self-service must preserve the reviewed private-beta fallback until launch flags are active");
assert.ok(selfService.includes("return <PlatformApplicationGate />"), "the private-beta gate remains the fail-closed fallback before public activation");
assert.ok(selfService.includes("TEST access never grants live provider credentials"), "the public gate must state the TEST/LIVE boundary");
assert.ok(!selfService.includes("PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED"), "browser code must never control or infer server feature flags from a client-provided value");

console.log("Platform access gate contract passed: private-beta authorization is preserved and public TEST self-service is legal-catalog-gated, server-authoritative, and TEST-only.");
