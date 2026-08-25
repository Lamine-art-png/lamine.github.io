import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared", "supported-locales.json"), "utf8"));
const canonical = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared", "ui-catalog.en.json"), "utf8"));
const endpoint = String(process.env.I18N_PREWARM_ENDPOINT || "https://api.agroai-pilot.com/v1/i18n/catalog").trim();
const requestedLocales = String(process.env.I18N_PREWARM_LOCALES || "").trim();
const configuredLocales = Array.isArray(manifest.dynamicCatalogLocales) ? manifest.dynamicCatalogLocales : [];
const locales = requestedLocales
  ? requestedLocales.split(",").map((value) => value.trim()).filter(Boolean)
  : configuredLocales;
const concurrency = Math.max(1, Math.min(Number(process.env.I18N_PREWARM_CONCURRENCY || 3), 6));
const maxAttempts = Math.max(1, Math.min(Number(process.env.I18N_PREWARM_ATTEMPTS || 4), 6));

const criticalKeys = [
  "app.loadingPortal", "language", "save", "saving", "newOperation", "workspace", "operate", "intelligence", "account",
  "tasks", "decisions", "evidence", "reports", "connectors", "askAgroAi", "readiness", "sources", "team", "settings",
  "profile", "billing", "security", "support", "logout", "plan", "settingsTitle", "settingsSubtitle", "languageRegion",
  "languageRegionHint", "subscriptionBilling", "accountProfile", "workspacePreferences", "notifications",
];

const source = Object.fromEntries(criticalKeys.map((key) => [key, canonical[key]]));
if (Object.values(source).some((value) => typeof value !== "string" || !value.trim())) {
  throw new Error("Critical locale prewarm source drifted from the canonical UI catalog");
}
if (!locales.length) throw new Error("No dynamic locales configured for critical prewarm");

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function prewarmLocale(locale) {
  let lastError = new Error(`No response for ${locale}`);
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(`prewarm_${locale}_timeout`), 20_000);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "accept": "application/json",
          "origin": "https://app.agroai-pilot.com",
          "x-request-id": `i18n-prewarm-${locale}-${attempt}`,
        },
        body: JSON.stringify({ locale, source }),
        signal: controller.signal,
      });
      const text = await response.text();
      let body;
      try { body = JSON.parse(text); }
      catch { throw new Error(`${locale}: HTTP ${response.status} non-JSON ${text.slice(0, 240)}`); }
      if (!response.ok || body?.status !== "ok") throw new Error(`${locale}: HTTP ${response.status} ${text.slice(0, 500)}`);
      if (body?.locale !== locale) throw new Error(`${locale}: response locale=${String(body?.locale)}`);
      const catalog = body?.catalog;
      if (!catalog || typeof catalog !== "object" || Array.isArray(catalog)) throw new Error(`${locale}: catalog missing`);
      for (const [key, sourceValue] of Object.entries(source)) {
        if (typeof catalog[key] !== "string" || !catalog[key].trim()) throw new Error(`${locale}: missing ${key}`);
        if (catalog[key].includes("{") !== sourceValue.includes("{")) throw new Error(`${locale}: placeholder structure drift for ${key}`);
      }
      const changed = Object.keys(source).filter((key) => catalog[key].trim() !== source[key].trim());
      if (changed.length < 2) throw new Error(`${locale}: critical shell remained English`);
      return { locale, provider: body.source || body.providers?.[0] || "unknown", changed: changed.length };
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt < maxAttempts) await delay(700 * attempt);
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastError;
}

const results = [];
const failures = [];
let cursor = 0;

async function worker() {
  while (true) {
    const index = cursor++;
    if (index >= locales.length) return;
    const locale = locales[index];
    try {
      const result = await prewarmLocale(locale);
      results.push(result);
      console.log(`PREWARM PASS ${locale} changed=${result.changed} provider=${result.provider}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failures.push({ locale, message });
      console.error(`PREWARM FAIL ${locale} ${message}`);
    }
  }
}

await Promise.all(Array.from({ length: concurrency }, () => worker()));
results.sort((a, b) => a.locale.localeCompare(b.locale));
failures.sort((a, b) => a.locale.localeCompare(b.locale));
console.log(JSON.stringify({ endpoint, critical_keys: criticalKeys.length, total: locales.length, passed: results.length, failed: failures.length, results, failures }, null, 2));
if (failures.length) process.exit(1);
