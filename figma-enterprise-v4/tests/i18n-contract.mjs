import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const src = path.join(root, "src", "app");
const repoRoot = path.resolve(root, "..");
const sharedRoot = path.join(repoRoot, "shared");
const manifest = JSON.parse(fs.readFileSync(path.join(sharedRoot, "supported-locales.json"), "utf8"));
const targets = JSON.parse(fs.readFileSync(path.join(sharedRoot, "chatgpt-language-targets.json"), "utf8"));
const literalPaths = fs.readdirSync(sharedRoot)
  .filter((name) => /^ui-literals\.en\.\d+\.json$/.test(name))
  .sort()
  .map((name) => path.join(sharedRoot, name));
const literalCatalog = Object.assign({}, ...literalPaths.map((file) => JSON.parse(fs.readFileSync(file, "utf8"))));
const i18n = fs.readFileSync(path.join(src, "i18n.ts"), "utf8");
const hook = fs.readFileSync(path.join(src, "hooks", "useLocale.ts"), "utf8");
const selector = fs.readFileSync(path.join(src, "components", "LanguageSelector.tsx"), "utf8");
const dynamicCatalog = fs.readFileSync(path.join(src, "dynamicLocaleCatalog.ts"), "utf8");
const globalOptions = fs.readFileSync(path.join(src, "globalLocaleOptions.ts"), "utf8");
const literalRuntime = fs.readFileSync(path.join(src, "portalLiteralCatalog.ts"), "utf8");
const runtimeCore = fs.readFileSync(path.join(src, "i18n-jsx", "runtimeCore.ts"), "utf8");
const viteConfig = fs.readFileSync(path.join(root, "vite.config.ts"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(`i18n contract failed: ${message}`);
}

assert(Array.isArray(manifest.enabledUiLocales), "manifest enabledUiLocales must be an array");
assert(manifest.enabledUiLocales.includes("auto"), "global UI must include browser-default mode");
assert(manifest.enabledUiLocales.includes("en"), "global UI must include English");
assert(manifest.enabledUiLocales.length >= 50, "global UI registry must expose the broad language set");

const targetCodes = new Set(targets.families.map((item) => item.code));
const enabledLanguageCodes = new Set(
  manifest.locales
    .filter((item) => manifest.enabledUiLocales.includes(item.code))
    .map((item) => item.languageCode)
    .filter((code) => code !== "auto"),
);
for (const code of targetCodes) assert(enabledLanguageCodes.has(code), `AI language family ${code} must be visible in the UI registry`);

assert(literalPaths.length >= 6, "split portal literal catalogs must be present");
assert(Object.keys(literalCatalog).length >= 400, "portal literal inventory must cover the broad static UI surface");
assert(Object.keys(literalCatalog).every((key) => key.startsWith("literal.")), "literal catalog keys must use the literal namespace");

assert(i18n.includes('../../../shared/supported-locales.json'), "frontend runtime must consume the shared manifest");
assert(i18n.includes("MANIFEST.enabledUiLocales"), "enabled locale canonicalization must derive from manifest data");
assert(!/export\s+function\s+useLocale/.test(i18n), "i18n.ts must not export a competing React locale hook");
assert(/export\s+function\s+useLocale/.test(hook), "hooks/useLocale.ts must be the authoritative React locale hook");
assert(hook.includes("useSyncExternalStore"), "locale hook must subscribe to the shared runtime revision");
assert(hook.includes("activateLocale"), "locale switching must expose one authoritative activation path");
assert(hook.includes("hasCoreLocaleCatalog"), "bundled core copy must remain usable before full hydration");
assert(hook.includes('ensureLocaleCatalog(selectedLocale, "core")'), "non-English locales must hydrate the small core catalog first");
assert(hook.includes('ensureLocaleCatalog(selectedLocale, "full")'), "full portal literal hydration must follow core hydration");
assert(hook.indexOf('ensureLocaleCatalog(selectedLocale, "core")') < hook.indexOf('ensureLocaleCatalog(selectedLocale, "full")'), "core hydration must occur before full hydration");
assert(hook.includes("notifyLocaleRuntime"), "locale activation must notify all mounted consumers");
assert(dynamicCatalog.includes('"/v1/i18n/catalog"'), "dynamic UI catalogs must use the backend localization contract");
assert(dynamicCatalog.includes("exactKeyParity"), "dynamic catalogs must fail closed on key drift");
assert(dynamicCatalog.includes("sourceFingerprint"), "dynamic catalogs must invalidate stale source copy");
assert(dynamicCatalog.includes("INFLIGHT"), "dynamic catalogs must deduplicate concurrent hydration");
assert(dynamicCatalog.includes("notifyLocaleRuntime"), "catalog installation must notify every mounted locale consumer");
assert(dynamicCatalog.includes("hasCompleteLocaleCatalog"), "partial bundled catalogs must hydrate to full portal coverage");
assert(dynamicCatalog.includes("fullEnglishUiSource"), "dynamic translation source must include static portal literals");
assert(selector.includes("GLOBAL_UI_LOCALES"), "language selector must render the full global registry");
assert(selector.includes("activateLocale"), "language selector must activate the selected locale immediately");
assert(!selector.includes("disabled={Boolean(pendingLocale)}"), "catalog loading must never disable the language selector");
assert(globalOptions.includes("manifest.enabledUiLocales"), "global selector options must derive from shared manifest");
assert(literalRuntime.includes("PORTAL_LITERAL_CATALOG"), "portal literal source map missing");
assert(literalRuntime.includes("ui-literals.en.6.json"), "all portal literal catalog parts must be consumed");
assert(runtimeCore.includes("LocalizedText"), "static JSX text must be locale-reactive");
assert(runtimeCore.includes("LOCALIZABLE_PROPS"), "static UI props must be locale-reactive");
assert(viteConfig.includes('jsxImportSource: "@agroai/i18n-jsx"'), "Vite must route JSX through the locale-aware runtime");
assert(i18n.includes("canonicalizeSelectedLocale"), "canonical selected-locale migration missing");
assert(i18n.includes("languageRoot"), "regional/language fallback canonicalization missing");
assert(i18n.includes('return languageMatch?.code || "auto"'), "unsupported selected locale must normalize to auto");

for (const token of ["MutationObserver", "applyTextLocalization", "localizeNode", "translatedText", "ALL_LOCALES"]) {
  const hits = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(ts|tsx)$/.test(entry.name) && fs.readFileSync(full, "utf8").includes(token)) hits.push(path.relative(root, full));
    }
  };
  walk(src);
  assert(hits.length === 0, `${token} remains in app source: ${hits.join(", ")}`);
}

console.log(`i18n contract passed with ${manifest.enabledUiLocales.length} visible UI locales and ${Object.keys(literalCatalog).length} static portal literals`);
