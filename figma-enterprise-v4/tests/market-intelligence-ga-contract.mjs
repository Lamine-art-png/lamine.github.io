import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../src/app/components/MarketIntelligenceV2.tsx", import.meta.url), "utf8");
const routes = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");

assert.match(routes, /import\("\.\/components\/MarketIntelligenceV2"\)/);
assert.match(routes, /"MarketIntelligenceV2"/);
assert.match(page, /Add commercial position/);
assert.match(page, /Add contract/);
assert.match(page, /Update market price/);
assert.match(page, /Market data providers/);
assert.match(page, /Refresh market data/);
assert.match(page, /\/v1\/market-intelligence\/providers/);
assert.match(page, /\/v1\/market-intelligence\/refresh/);
assert.match(page, /\/v1\/market-intelligence\/positions/);
assert.match(page, /\/v1\/market-intelligence\/contracts/);
assert.match(page, /\/v1\/market-intelligence\/observations/);
assert.match(page, /Customer entered market price/);
assert.match(page, /source_status: "MANUAL"/);
assert.match(page, /never presents manual or delayed data as live/);
assert.doesNotMatch(page, /fakeLive|mockPrice|Math\.random/);

console.log("Market Intelligence GA portal workflow contract passed");
