import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = readFileSync(resolve(root, "src/app/components/FieldIntelligenceV2.tsx"), "utf8");
const backend = readFileSync(resolve(root, "../agroai_api/app/api/v1/field_intelligence.py"), "utf8");
const activePricing = readFileSync(resolve(root, "src/app/components/PricingPage.tsx"), "utf8");
const routes = readFileSync(resolve(root, "src/app/routes.tsx"), "utf8");

// Existing free field-record capture must stay available: don't gate the entire
// Field Intelligence screen behind Professional.
assert.match(source, /field_intelligence\.capture/);
assert.match(source, /liveFieldAiEnabled=\{liveFieldAiEnabled\}/);
assert.match(source, /\["free", "pilot"\]\.includes/);

// Only entitlement-enabled plans may trigger recurrent remote vision/speech.
// Browser/local recorder and offline evidence queues remain usable on Free.
assert.match(source, /\["intelligence\.deep_analysis"\] === "enabled"/);
assert.equal((source.match(/if \(liveFieldAiEnabled\) startLiveSpeechSampling\(stream\);/g) || []).length, 2);
assert.match(source, /if \(liveFieldAiEnabled\) startLiveVisionSampling\(\);/);
assert.match(source, /setLiveVisionState\(liveFieldAiEnabled \? "sampling" : "idle"\)/);

// The backend must reject unpaid requests before calling the external models.
assert.match(backend, /@router\.post\("\/live-analysis", dependencies=\[Depends\(enforce_paid_live_field_ai\)\]\)/);
assert.match(backend, /@router\.post\("\/live-transcription", dependencies=\[Depends\(enforce_paid_live_field_ai\)\]\)/);

// Free customers see an actionable, honest first-result prompt after an actual
// completed/needs-review observation, never before evidence exists.
assert.match(source, /firstFieldResultReady = observations\.some/);
assert.match(source, /\["completed", "needs_review"\]/);
assert.match(source, /freeWorkspace && firstFieldResultReady/);
assert.match(source, /apiClient\.billing\.checkout\(\{\s*plan_id: "professional", billing_period: "monthly", locale: effectiveLocale/);
assert.match(source, /window\.location\.assign\(response\.checkout_url\)/);

// The active pricing route already supports all paid self-serve tiers;
// obsolete alternate pricing screens must not be used to route buyers to sales.
assert.match(routes, /import\("\.\/components\/PricingPage"\), "PricingPage"/);
assert.match(activePricing, /const paidSelfServe = \["professional", "team", "network"\]\.includes\(plan\.id\)/);
console.log("first-day-paid-conversion-contract: ok");
