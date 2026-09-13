import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/components/PlatformIntelligenceConsole.tsx", import.meta.url), "utf8");
const routes = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");

for (const label of ["Overview", "API Keys", "Playground", "Usage & Billing", "Docs", "Advanced"]) {
  assert.ok(source.includes(label), `commercial console missing ${label}`);
}

assert.ok(source.includes("Put agricultural intelligence inside your product."));
assert.ok(source.includes("/v1/intelligence"));
assert.ok(source.includes("/v1/platform/developer/wallet/checkout"));
assert.ok(source.includes("/v1/platform/developer/intelligence/bootstrap"));
assert.ok(source.includes("/v1/platform/developer/intelligence/run"));
assert.ok(source.includes("Idempotency-Key"));
assert.ok(source.includes("agro_live_"));
assert.ok(source.includes("intelligence:run"));
assert.ok(source.includes("Physical execution is not included"));
assert.ok(source.includes("degraded or failed runs are automatically refunded") || source.includes("Degraded or failed intelligence runs are automatically refunded"));
assert.ok(!source.includes("localStorage"), "commercial console must never persist one-time API keys");
assert.ok(!source.includes("sessionStorage"), "commercial console must never persist one-time API keys");
assert.ok(routes.includes("<PlatformIntelligenceConsole />"), "paid intelligence console must be the commercial front door");
assert.ok(routes.includes("<PlatformConsoleApp />"), "advanced control plane must remain reachable");
assert.ok(routes.includes("COMMERCIAL_PLATFORM_ROUTES"));

console.log("AGRO-AI paid intelligence console contract passed.");
