import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(here, "../src/app");
const repoRoot = path.resolve(here, "../..");
const component = fs.readFileSync(path.join(appRoot, "components/intelligence/DecisionMemoryWorkspace.tsx"), "utf8");
const catalogModule = fs.readFileSync(path.join(appRoot, "decisionMemoryI18n.ts"), "utf8");
const backendI18n = fs.readFileSync(path.join(repoRoot, "agroai_api/app/api/v1/i18n.py"), "utf8");
const canonicalCatalog = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared/ui-catalog.en.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared/supported-locales.json"), "utf8"));

function objectBody(source, exportName) {
  const marker = `export const ${exportName}: Record<string, string> = {`;
  const start = source.indexOf(marker);
  if (start < 0) throw new Error(`${exportName} not found`);
  const bodyStart = start + marker.length;
  const end = source.indexOf("\n};", bodyStart);
  if (end < 0) throw new Error(`${exportName} body is not closed`);
  return source.slice(bodyStart, end);
}

function keysFrom(body) {
  return [...body.matchAll(/"(decisionMemory\.[^"]+)"\s*:/g)].map((match) => match[1]).sort();
}

const enKeys = Object.keys(canonicalCatalog).filter((key) => key.startsWith("decisionMemory.")).sort();
const frKeys = keysFrom(objectBody(catalogModule, "DECISION_MEMORY_FR"));
if (!enKeys.length) throw new Error("Decision Memory canonical English source is empty");
if (JSON.stringify(enKeys) !== JSON.stringify(frKeys)) {
  throw new Error("Decision Memory English/French base catalogs lost exact key parity");
}

const usedKeys = [...component.matchAll(/"(decisionMemory\.[^"]+)"/g)].map((match) => match[1]);
const missingSourceKeys = [...new Set(usedKeys.filter((key) => !enKeys.includes(key)))];
if (missingSourceKeys.length) {
  throw new Error(`Decision Memory UI uses keys missing from the canonical global English translation source: ${missingSourceKeys.join(", ")}`);
}

if (!catalogModule.includes('sharedUiCatalogEn from "../../../shared/ui-catalog.en.json"')) {
  throw new Error("Decision Memory frontend source must come from the shared canonical UI catalog");
}
if (!backendI18n.includes('_CANONICAL_CATALOG_PATH = _REPO_ROOT / "shared" / "ui-catalog.en.json"')) {
  throw new Error("Backend UI translation must authorize the shared canonical UI catalog");
}
if (!component.includes("ensureLocaleSourceCatalog(selectedLocale, DECISION_MEMORY_EN)")) {
  throw new Error("Decision Memory must hydrate its operating catalog through the global dynamic locale service");
}
if (!component.includes("primeLocaleSourceCatalogFromCache")) {
  throw new Error("Decision Memory must reuse durable translated catalog cache");
}
if (/effectiveLocale\.toLowerCase\(\)\.startsWith\(["']fr["']\)/.test(component)) {
  throw new Error("Decision Memory must not branch UI copy between English and French");
}
if (component.includes("function useMemoryCopy")) {
  throw new Error("Decision Memory must not contain a two-language copy hook");
}

const enabled = new Set((manifest.enabledUiLocales || []).filter((locale) => !["auto", "en", "fr-FR"].includes(locale)));
const dynamic = new Set(manifest.dynamicCatalogLocales || []);
const missingDynamic = [...enabled].filter((locale) => !dynamic.has(locale));
if (missingDynamic.length) {
  throw new Error(`Enabled UI locales missing dynamic translation support: ${missingDynamic.join(", ")}`);
}
const localeCodes = new Set((manifest.locales || []).map((locale) => locale.code));
const missingMetadata = (manifest.enabledUiLocales || []).filter((locale) => !localeCodes.has(locale));
if (missingMetadata.length) {
  throw new Error(`Enabled UI locales missing locale metadata: ${missingMetadata.join(", ")}`);
}

console.log(`Decision Memory global i18n contract passed for ${(manifest.enabledUiLocales || []).length - 1} enabled language choices plus Auto.`);