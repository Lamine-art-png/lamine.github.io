import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/app");
const catalog = fs.readFileSync(path.join(root, "commercialBoundaryI18n.ts"), "utf8");
const host = fs.readFileSync(path.join(root, "components/CommercialBoundaryHostLocalized.tsx"), "utf8");
const dynamic = fs.readFileSync(path.join(root, "dynamicLocaleCatalog.ts"), "utf8");
const literalRuntime = fs.readFileSync(path.join(root, "portalLiteralCatalog.ts"), "utf8");

for (const required of [
  "COMMERCIAL_BOUNDARY_EN",
  "COMMERCIAL_BOUNDARY_FR",
  "installCommercialBoundaryBaseCatalogs",
  "ui-commercial-boundary.en.json",
]) {
  if (!catalog.includes(required)) throw new Error(`Missing ${required}`);
}

for (const required of [
  "useLocale()",
  "commercialBoundary.title.quota",
  "commercialBoundary.body.unavailable",
  "commercialBoundary.close",
  "reasonText(detail, t)",
]) {
  if (!host.includes(required)) throw new Error(`Missing localized boundary contract: ${required}`);
}

if (host.includes("detail?.message") || host.includes("detail.message")) {
  throw new Error("Raw backend message copy must not be rendered as portal UI");
}

if (!literalRuntime.includes("ui-literals.en.7.json")) {
  throw new Error("Portal runtime must consume monetization literal catalog part 7");
}

const install = dynamic.indexOf("installCommercialBoundaryBaseCatalogs();");
const snapshot = dynamic.indexOf("const CORE_ENGLISH_SOURCE");
if (install < 0 || snapshot < 0 || install > snapshot) {
  throw new Error("Commercial copy must join the core catalog before the source snapshot");
}

console.log("Commercial boundary localization contract passed.");
