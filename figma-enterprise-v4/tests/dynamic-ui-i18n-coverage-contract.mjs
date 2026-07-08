import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const repoRoot = path.resolve(root, "..");
const appRoot = path.join(root, "src", "app");
const sharedRoot = path.join(repoRoot, "shared");

const read = (...parts) => fs.readFileSync(path.join(...parts), "utf8");
const dynamicCopy = JSON.parse(read(sharedRoot, "ui-dynamic-copy.en.json"));
const dynamicExtra = JSON.parse(read(sharedRoot, "ui-dynamic-copy-extra.en.json"));
const portalCatalog = read(appRoot, "portalLiteralCatalog.ts");
const dynamicRuntime = read(appRoot, "dynamicLocaleCatalog.ts");
const routeHook = read(appRoot, "hooks", "usePortalCopy.ts");
const layout = read(appRoot, "components", "MainLayout.tsx");
const pricing = read(appRoot, "components", "PricingPage.tsx");
const evidence = read(appRoot, "components", "Evidence.tsx");
const integrations = read(appRoot, "components", "IntegrationsV3.tsx");
const boundary = read(appRoot, "components", "CommercialBoundaryHostLocalized.tsx");
const canonical = read(repoRoot, "cloudflare", "edge-gateway", "src", "i18n-canonical-source.ts");

function assert(condition, message) {
  if (!condition) throw new Error(`dynamic UI i18n contract failed: ${message}`);
}

const dynamicEntries = { ...dynamicCopy, ...dynamicExtra };
assert(Object.keys(dynamicEntries).length >= 250, "dynamic copy catalog is too small to cover recorded monetization/operator surfaces");
for (const key of [
  "dynamic.pricing.freeAvailable",
  "dynamic.pricing.comparePlans",
  "dynamic.operations.operatingStatus",
  "dynamic.evidence.store",
  "dynamic.overview.commandCenter",
  "dynamic.cockpit.exceptionQueue",
  "dynamic.cockpit.providerNeedsAttentionTemplate",
  "dynamic.cockpit.connectorStale",
  "dynamic.integrations.upgradeMessageTemplate",
  "dynamic.integrations.setupStateTemplate",
  "dynamic.cockpit.connectionsTemplate",
  "dynamic.paywall.team",
]) assert(typeof dynamicEntries[key] === "string" && dynamicEntries[key].length > 0, `missing ${key}`);

assert(portalCatalog.includes("ui-dynamic-copy.en.json"), "portal catalog must import primary dynamic copy");
assert(portalCatalog.includes("ui-dynamic-copy-extra.en.json"), "portal catalog must import compact dynamic copy");
assert(portalCatalog.includes("dynamicCopySourceForNamespaces"), "namespace source selector missing");
assert(portalCatalog.includes("portalCopySourceForValues"), "existing literal prioritization missing");
assert(portalCatalog.includes("TEMPLATE_MATCHERS"), "generated UI template matcher registry missing");
assert(portalCatalog.includes("templateMatch"), "generated UI template matching missing");
assert(portalCatalog.includes("formatTranslation(translated, localizedValues)"), "matched templates must substitute localized captured values");

assert(canonical.includes("ui-dynamic-copy.en.json"), "edge canonical source must authorize primary dynamic copy");
assert(canonical.includes("ui-dynamic-copy-extra.en.json"), "edge canonical source must authorize compact dynamic copy");
assert(dynamicRuntime.includes("ensureLocaleSourceCatalog"), "route-scoped source hydration missing");
assert(dynamicRuntime.includes("primeLocaleSourceCatalogFromCache"), "route-scoped cache priming missing");
assert(routeHook.includes("ensureLocaleSourceCatalog"), "visible route copy must hydrate independently of full portal completion");
assert(routeHook.includes("useSyncExternalStore"), "route copy must react to installed catalog chunks");

for (const route of ["/pricing", "/evidence", "/operations", "/field-queue", "/tasks", "/readiness", "/fields", "/exceptions", "/integrations"]) {
  assert(layout.includes(`\"${route}\"`), `route-priority map missing ${route}`);
}
assert(layout.includes("tx(currentPlanLabel)"), "sidebar plan name must not render raw English");

assert(pricing.includes('usePortalCopy(["pricing", "shared"])'), "pricing page must hydrate pricing copy first");
for (const expression of ["tx(plan.name)", "tx(plan.recommended_buyer)", "tx(limit)", "tx(feature)", "tx(cell)"]) {
  assert(pricing.includes(expression), `pricing dynamic field bypasses translation: ${expression}`);
}
assert(pricing.includes('tf("Create an account first, then Stripe checkout will open for {plan}."'), "pricing generated checkout sentence must use a translated template");

assert(evidence.includes('usePortalCopy(["evidence", "shared"])'), "evidence page must hydrate evidence copy first");
assert(evidence.includes('tf("{score}% readiness"'), "evidence readiness label must use a translated template");
assert(evidence.includes('tf("Uploaded {files} file(s). Created {evidence} evidence records from {rows} parsed rows."'), "evidence upload result must use a translated template");

assert(integrations.includes("INTEGRATION_LITERAL_VALUES"), "connector profile literals must be prioritized");
assert(integrations.includes('usePortalCopy(["integrations", "shared"], INTEGRATION_LITERAL_VALUES)'), "integrations route copy hook missing");
assert(integrations.includes('tf("Unlock {provider}: {description}'), "connector paywall must use translated template");
assert(integrations.includes("tx(profile.description)"), "connector descriptions must not render raw");
assert(integrations.includes('tf("Upgrade to {plan}"'), "connector upgrade CTA must use translated template");

assert(!boundary.includes("return detail.conversion_context.trim();"), "paywall conversion context must never return raw English");
assert(boundary.includes("return tx(detail.conversion_context.trim());"), "paywall conversion context must pass through locale copy");
assert(boundary.includes('usePortalCopy(["paywall", "shared"])'), "paywall dynamic copy must hydrate before rendering");

console.log(`dynamic UI i18n coverage contract passed with ${Object.keys(dynamicEntries).length} canonical dynamic strings`);
