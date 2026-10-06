import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../src/app/components/MarketIntelligenceV2.tsx", import.meta.url), "utf8");
const routes = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");
const nav = readFileSync(new URL("../src/app/components/MainLayout.tsx", import.meta.url), "utf8");

assert.match(routes, /path: "market-intelligence"/);
assert.match(routes, /MarketIntelligenceV2/);
assert.match(nav, /market_intelligence\.read/);
assert.match(nav, /path: "\/market-intelligence"/);

// The customer-facing workspace must be able to bootstrap and manage its own
// commercial position instead of requiring a developer to seed the database.
for (const phrase of [
  "Add commercial position",
  "Add contract",
  "Update market price",
  "Data sources",
  "Create contract",
  "Save price",
  "Refresh market data",
]) {
  assert.ok(page.includes(phrase), `missing GA management surface: ${phrase}`);
}

for (const endpoint of [
  "/v1/market-intelligence/overview",
  "/v1/market-intelligence/capabilities",
  "/v1/market-intelligence/providers",
  "/v1/market-intelligence/positions",
  "/v1/market-intelligence/contracts",
  "/v1/market-intelligence/observations",
  "/v1/market-intelligence/refresh",
]) {
  assert.ok(page.includes(endpoint), `missing GA endpoint usage: ${endpoint}`);
}

// Positions are created through customer-language onboarding; the server
// infers market structure and refreshes governed evidence itself.
const onboarding = readFileSync(new URL("../src/app/components/CommercialOnboarding.tsx", import.meta.url), "utf8");
assert.ok(onboarding.includes('"/v1/market-intelligence/onboarding"'));
assert.ok(onboarding.includes("Create commercial position"));
assert.match(page, /source_status:\s*"MANUAL"/);
assert.match(page, /Customer entered market price/);
assert.doesNotMatch(page, /report slug|usda_mmn_slug/i);
assert.match(page, /never presents manual or delayed data as live/);
assert.doesNotMatch(page, /Math\.random|fakeLive|mockPrice/);

console.log("Market Intelligence GA management contract passed");
