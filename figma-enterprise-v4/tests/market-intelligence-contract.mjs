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
assert.match(pageSource, /"LIVE"/);
assert.match(pageSource, /"DELAYED"/);
assert.match(pageSource, /"STALE"/);
assert.match(pageSource, /"MANUAL"/);
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
assert.match(managedPageSource, /ECB/);
assert.match(managedPageSource, /USDA MyMarketNews/);
assert.match(managedPageSource, /never presents manual or delayed data as live/);
assert.doesNotMatch(managedPageSource, /Math\.random|fakeLive/);

console.log("Market Intelligence frontend contract passed");
