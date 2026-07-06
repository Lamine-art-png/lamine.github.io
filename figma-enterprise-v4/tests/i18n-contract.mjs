import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const src = path.join(root, "src", "app");
const repoRoot = path.resolve(root, "..");
const manifestPath = path.join(repoRoot, "shared", "supported-locales.json");
const targetsPath = path.join(repoRoot, "shared", "chatgpt-language-targets.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const targets = JSON.parse(fs.readFileSync(targetsPath, "utf8"));
const i18n = fs.readFileSync(path.join(src, "i18n.ts"), "utf8");
const app = fs.readFileSync(path.join(src, "App.tsx"), "utf8");
const hook = fs.readFileSync(path.join(src, "hooks", "useLocale.ts"), "utf8");
const selector = fs.readFileSync(path.join(src, "components", "LanguageSelector.tsx"), "utf8");
const dynamicCatalog = fs.readFileSync(path.join(src, "dynamicLocaleCatalog.ts"), "utf8");
const globalOptions = fs.readFileSync(path.join(src, "globalLocaleOptions.ts"), "utf8");

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
    .filter((code) => code !== "auto")
);
for (const code of targetCodes) assert(enabledLanguageCodes.has(code), `AI language family ${code} must be visible in the UI registry`);

assert(i18n.includes('../../../shared/supported-locales.json'), "frontend runtime must consume the shared manifest");
assert(i18n.includes("MANIFEST.enabledUiLocales"), "enabled locale canonicalization must derive from manifest data");
assert(!/export\s+function\s+useLocale/.test(i18n), "i18n.ts must not export a competing React locale hook");
assert(/export\s+function\s+useLocale/.test(hook), "hooks/useLocale.ts must be the authoritative React locale hook");
assert(hook.includes("ensureLocaleCatalog"), "locale hook must hydrate non-static UI catalogs");
assert(dynamicCatalog.includes('"/v1/i18n/catalog"'), "dynamic UI catalogs must use the backend localization contract");
assert(dynamicCatalog.includes("exactKeyParity"), "dynamic catalogs must fail closed on key drift");
assert(selector.includes("GLOBAL_UI_LOCALES"), "language selector must render the full global registry");
assert(globalOptions.includes("manifest.enabledUiLocales"), "global selector options must derive from shared manifest");
assert(!/key=\{\s*(locale|selectedLocale|effectiveLocale)\s*\}/.test(app), "locale must not be used as an app/router React key");
assert(i18n.includes('const EN_KEYS = Object.keys(en).sort()'), "English catalog parity guard missing");
assert(i18n.includes('const FR_KEYS = Object.keys(frFR).sort()'), "French catalog parity guard missing");
assert(i18n.includes('canonicalizeSelectedLocale'), "canonical selected-locale migration missing");
assert(i18n.includes('languageRoot'), "regional/language fallback canonicalization missing");
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

for (const key of [
  "app.loadingSession",
  "app.loadingPortal",
  "app.recoveryTitle",
  "intelligence.newChat",
  "intelligence.languageGenerationFailed",
  "intelligence.placeholder",
]) {
  assert(i18n.includes(`\"${key}\"`), `required key missing: ${key}`);
}

console.log(`i18n contract passed with ${manifest.enabledUiLocales.length} visible UI locales`);
