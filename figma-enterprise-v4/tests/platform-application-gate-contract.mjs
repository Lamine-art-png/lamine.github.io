import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/components/PlatformApplicationGate.tsx", import.meta.url), "utf8");

assert.ok(source.includes('const canManageApplication = ["owner", "admin"].includes(organizationRole)'), "application management must be limited in the UI to organization owners and admins");
assert.ok(source.includes("if (!canManageApplication) return <RoleGate"), "non-admin members must receive a deliberate role boundary before the application form");
assert.ok(source.includes("if (!canManageApplication) { setLoading(false); setApplications([]); setAvailable(false); setError(\"\"); return; }"), "non-admin members must not call the protected application-list endpoint");
assert.ok(source.includes("if (!canManageApplication) return; setSubmitting(true)"), "the submit handler must retain a client-side role guard in addition to backend authorization");
assert.ok(source.includes("application.decision_reason"), "needs-information applications must surface the reviewer reason when the backend provides it");
assert.ok(source.includes("/additional-information"), "reviewer follow-up must remain inside the audited application lifecycle");
assert.ok(source.includes("document_references: []"), "the follow-up UI must not fabricate uploaded evidence references");
assert.ok(!source.includes("mailto:support@agroai-pilot.com?subject=Platform%20API%20application%20information"), "review follow-up must not escape into unaudited email");

console.log("Platform application gate contract passed: owner-admin authorization, reviewer context, and audited follow-up are preserved.");
