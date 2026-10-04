import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const routeSource = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");
const navSource = readFileSync(new URL("../src/app/components/MainLayout.tsx", import.meta.url), "utf8");
const pageSource = readFileSync(new URL("../src/app/components/MarketIntelligence.tsx", import.meta.url), "utf8");
const managedPageSource = readFileSync(new URL("../src/app/components/MarketIntelligenceV2.tsx", import.meta.url), "utf8");

assert.match(routeSource, /path: "market-intelligence"/);
assert.match(routeSource, /MarketIntelligenceV2/);
assert.match(navSource, /capabilityEnabled\(entitlements, "market_intelligence\.read"/);
assert.match(navSource, /path: "\/market-intelligence"/);

assert.match(pageSource, /\/v1\/market-intelligence\/overview/);
assert.match(pageSource, /\/v1\/market-intelligence\/scenarios/);
assert.match(pageSource, /\/v1\/market-intelligence\/ask/);
assert.match(pageSource, /"DEMO DATA"/);
// Source states render as localized labels from the shared copy module.
const commercialCopySource = readFileSync(new URL("../src/app/components/commercialCopy.ts", import.meta.url), "utf8");
for (const state of ["LIVE", "DELAYED", "STALE", "MANUAL", "UNAVAILABLE", "NOT_CONFIGURED"]) {
  assert.match(commercialCopySource, new RegExp(`\\b${state}: "[^"]+"`));
}
assert.match(pageSource, /stateLabel\(tx, badge\.state\)/);
assert.match(pageSource, /does not execute trades or provide personalized derivatives instructions/);
assert.match(pageSource, /projected_revenue: string \| null/);
assert.match(pageSource, /normalized === "auto" \? undefined : locale/);
assert.match(pageSource, /new Intl\.NumberFormat\(numberLocale\(locale\)/);
assert.match(pageSource, /toLocaleString\(numberLocale\(locale\)\)/);
assert.doesNotMatch(pageSource, /Math\.random|mockPrice|fakeLive/);

assert.match(managedPageSource, /\/v1\/market-intelligence\/providers/);
assert.match(managedPageSource, /\/v1\/market-intelligence\/refresh/);
assert.match(managedPageSource, /\/v1\/market-intelligence\/positions/);
assert.match(managedPageSource, /\/v1\/market-intelligence\/contracts/);
assert.match(managedPageSource, /\/v1\/market-intelligence\/observations/);
assert.match(managedPageSource, /Governed sources refresh automatically on a schedule/);
assert.match(managedPageSource, /CommercialIntelligenceHome/);
assert.match(managedPageSource, /CommercialOnboarding/);

// Commercial Intelligence home and onboarding.
const homeSource = readFileSync(new URL("../src/app/components/CommercialIntelligenceHome.tsx", import.meta.url), "utf8");
const onboardingSource = readFileSync(new URL("../src/app/components/CommercialOnboarding.tsx", import.meta.url), "utf8");
for (const endpoint of ["/v1/market-intelligence/home", "/v1/market-intelligence/alerts/", "/provenance", "/v1/market-intelligence/scenarios/compare", "/v1/market-intelligence/decision-journal", "/v1/market-intelligence/ask"]) {
  assert.ok(homeSource.includes(endpoint), `home missing ${endpoint}`);
}
assert.match(homeSource, /Is anything materially affecting your business\?/);
assert.match(homeSource, /Scenarios are deterministic what-ifs, not forecasts\./);
assert.match(homeSource, /does not execute trades or provide personalized derivatives instructions/);
assert.match(homeSource, /Value hidden by data licence/);
for (const endpoint of ["/v1/market-intelligence/onboarding/infer", "/v1/market-intelligence/onboarding\"", "/v1/market-intelligence/fields"]) {
  assert.ok(onboardingSource.includes(endpoint.replace("\\\"", "\"")), `onboarding missing ${endpoint}`);
}
// Customers never need provider report identifiers or raw ISO codes.
for (const source of [onboardingSource, managedPageSource, homeSource]) {
  assert.doesNotMatch(source, /report slug|usda_mmn_slug|Country code/i);
  assert.doesNotMatch(source, /\b(?:ml|mr|pl|pr|left|right)-\d/);
}
assert.match(onboardingSource, /Intl\.DisplayNames/);
assert.match(managedPageSource, /never presents manual or delayed data as live/);
assert.doesNotMatch(managedPageSource, /Math\.random|fakeLive/);

console.log("Market Intelligence frontend contract passed");
