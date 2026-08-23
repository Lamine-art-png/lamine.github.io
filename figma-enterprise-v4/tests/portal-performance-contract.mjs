import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const app = readFileSync(join(root, "src", "app", "App.tsx"), "utf8");
const auth = readFileSync(join(root, "src", "app", "auth", "AuthProvider.tsx"), "utf8");

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
assert.match(auth, /void developerHydration/);

console.log("Portal performance contract passed");
