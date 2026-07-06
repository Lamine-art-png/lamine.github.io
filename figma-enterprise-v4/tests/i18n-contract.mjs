import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const src = path.join(root, "src", "app");
const repoRoot = path.resolve(root, "..");
const manifestPath = path.join(repoRoot, "shared", "supported-locales.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const i18n = fs.readFileSync(path.join(src, "i18n.ts"), "utf8");
const app = fs.readFileSync(path.join(src, "App.tsx"), "utf8");
const hook = fs.readFileSync(path.join(src, "hooks", "useLocale.ts"), "utf8");
const selector = fs.readFileSync(path.join(src, "components", "LanguageSelector.tsx"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(`i18n contract failed: ${message}`);
}

assert(Array.isArray(manifest.enabledUiLocales), "manifest enabledUiLocales must be an array");
assert(manifest.enabledUiLocales.join(",") === "auto,en,fr-FR", "production UI scope must remain bounded to auto,en,fr-FR");
assert(i18n.includes('../../../shared/supported-locales.json'), "frontend runtime must consume the shared manifest");
assert(i18n.includes("MANIFEST.enabledUiLocales"), "enabled locale options must derive from manifest data");
assert(!/export\s+function\s+useLocale/.test(i18n), "i18n.ts must not export a competing React locale hook");
assert(/export\s+function\s+useLocale/.test(hook), "hooks/useLocale.ts must be the authoritative React locale hook");
assert(selector.includes("useLocale"), "language selector must consume the authoritative locale hook");
assert(!/key=\{\s*(locale|selectedLocale|effectiveLocale)\s*\}/.test(app), "locale must not be used as an app/router React key");
assert(i18n.includes('const EN_KEYS = Object.keys(en).sort()'), "enabled catalog parity guard missing");
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

console.log("i18n contract passed");
