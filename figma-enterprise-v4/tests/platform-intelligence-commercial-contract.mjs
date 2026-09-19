import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/components/PlatformIntelligenceConsole.tsx", import.meta.url), "utf8");
const copy = readFileSync(new URL("../src/app/platformIntelligenceCopy.ts", import.meta.url), "utf8");
const routes = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");
const combined = `${source}\n${copy}`;

for (const label of ["Overview", "API Keys", "Playground", "Usage & Billing", "Docs", "Advanced"]) {
  assert.ok(combined.includes(label), `commercial console missing ${label}`);
}

assert.ok(combined.includes("Put agricultural intelligence inside your product."));
assert.ok(source.includes("/v1/intelligence") || copy.includes("/v1/intelligence"));
assert.ok(source.includes("/v1/platform/developer/wallet/checkout"));
assert.ok(source.includes("/v1/platform/developer/intelligence/bootstrap"));
assert.ok(source.includes("/v1/platform/developer/intelligence/run"));
assert.ok(source.includes("Idempotency-Key") || copy.includes("Idempotency-Key"));
assert.ok(copy.includes("agro_live_"));
assert.ok(copy.includes("intelligence:run"));
assert.ok(copy.includes("physical actions"));
assert.ok(copy.includes("Failed or degraded runs are not charged."));
assert.ok(source.includes('replace(/^\\/platform(?=\\/|$)/, "")'), "commercial console must normalize the enterprise /platform mount");
assert.ok(source.includes('const withBase = useCallback'), "commercial console navigation must preserve the incoming mount prefix");
assert.ok(!source.includes("localStorage"), "commercial console must never persist one-time API keys");
assert.ok(!source.includes("sessionStorage"), "commercial console must never persist one-time API keys");
assert.ok(routes.includes("<PlatformIntelligenceConsole />"), "paid intelligence console must be the commercial front door");
assert.ok(routes.includes("<PlatformConsoleApp />"), "advanced control plane must remain reachable");
assert.ok(routes.includes("COMMERCIAL_PLATFORM_ROUTES"));
const advancedCheck = routes.indexOf("if (platformDeveloper) return");
const commercialCheck = routes.indexOf("if (commercialSurface) return");
assert.ok(advancedCheck >= 0 && commercialCheck >= 0 && advancedCheck < commercialCheck,
  "enrolled advanced developers must be routed before the commercial surface");
assert.ok(routes.includes("if (commercialSurface) return <PlatformIntelligenceConsole />"),
  "commercial-only customers must retain the paid Intelligence front door");

console.log("AGRO-AI paid intelligence console contract passed.");
