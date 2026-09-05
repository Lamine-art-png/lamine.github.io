import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const app = readFileSync(join(root, "src", "app", "App.tsx"), "utf8");
const auth = readFileSync(join(root, "src", "app", "auth", "AuthProvider.tsx"), "utf8");
const overview = readFileSync(join(root, "src", "app", "components", "Overview.tsx"), "utf8");
const statusBar = readFileSync(join(root, "src", "app", "components", "OperatingStatusBar.tsx"), "utf8");

// Connection and authenticated code loading must overlap session validation.
assert.match(app, /const apiOrigin = "https:\/\/api\.agroai-pilot\.com"/);
assert.match(app, /link\.rel = "preconnect"/);
assert.match(app, /if \(!token\) \{ setRouter\(null\)/);
assert.match(app, /import\("\.\/routes"\)/);

// A language switch must never cover the entire authenticated product.
assert.doesNotMatch(app, /LocaleTransitionCover/);
assert.doesNotMatch(app, /MAX_LOCALE_TRANSITION_COVER_MS/);
assert.doesNotMatch(app, /localeCoverVisible/);

// First-paint session state comes from one aggregate request, with refresh
// deduplication and the Platform developer gate off the Enterprise hot path.
assert.match(auth, /refreshInFlight/);
assert.match(auth, /apiClient\.get\("\/v1\/auth\/bootstrap"\)/);
assert.doesNotMatch(auth, /apiClient\.me\(\)/);
assert.doesNotMatch(auth, /apiClient\.getOrgs\(\)/);
assert.doesNotMatch(auth, /apiClient\.getWorkspaces\(\)/);
assert.match(auth, /platformDeveloperIsFirstPaintCritical\(\)/);
assert.match(auth, /window\.setTimeout\(\(\) => \{/);
assert.match(auth, /1500/);

// The Command Center aggregate is the only initial field-ops resource. It
// already carries tasks and audit events, so separate first-paint calls would
// rebuild the same server context and regress latency.
assert.match(overview, /apiClient\.fieldOps\.commandCenter\(workspaceId\)/);
assert.doesNotMatch(overview, /apiClient\.fieldOps\.tasks\(workspaceId\)/);
assert.doesNotMatch(overview, /apiClient\.fieldOps\.auditTrail\(workspaceId\)/);

// The expensive intelligence brief is demand-loaded only when the Brain drawer
// is open. It must never be an unconditional global page-load request.
assert.match(statusBar, /apiClient\.intelligence\.brief\(\)/);
assert.match(statusBar, /\{ enabled: open \}/);

console.log("Portal performance contract passed");
