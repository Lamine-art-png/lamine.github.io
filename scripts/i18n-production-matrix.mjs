import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared", "supported-locales.json"), "utf8"));
const endpoint = String(process.env.I18N_SMOKE_ENDPOINT || "https://api.agroai-pilot.com/v1/i18n/catalog").trim();
const locales = Array.isArray(manifest.dynamicCatalogLocales) ? manifest.dynamicCatalogLocales : [];
const source = { settings: "Settings", language: "Language", workspace: "Workspace" };
const concurrency = Math.max(1, Math.min(Number(process.env.I18N_SMOKE_CONCURRENCY || 3), 6));
const maxAttempts = Math.max(1, Math.min(Number(process.env.I18N_SMOKE_ATTEMPTS || 3), 6));

if (!locales.length) throw new Error("No dynamicCatalogLocales found in shared manifest");

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function checkLocale(locale) {
  let lastError = new Error(`No response for ${locale}`);
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(`locale_${locale}_timeout`), 20_000);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "accept": "application/json",
          "origin": "https://app.agroai-pilot.com",
          "x-request-id": `i18n-matrix-${locale}-${attempt}`,
        },
        body: JSON.stringify({ locale, source }),
        signal: controller.signal,
      });
      const text = await response.text();
      let body;
      try { body = JSON.parse(text); }
      catch { throw new Error(`${locale}: HTTP ${response.status} non-JSON ${text.slice(0, 240)}`); }

      if (!response.ok) throw new Error(`${locale}: HTTP ${response.status} ${text.slice(0, 500)}`);
      if (body?.status !== "ok") throw new Error(`${locale}: status=${String(body?.status)}`);
      if (body?.locale !== locale) throw new Error(`${locale}: response locale=${String(body?.locale)}`);
      const catalog = body?.catalog;
      if (!catalog || typeof catalog !== "object" || Array.isArray(catalog)) throw new Error(`${locale}: catalog missing`);
      const sourceKeys = Object.keys(source).sort();
      const catalogKeys = Object.keys(catalog).sort();
      if (JSON.stringify(sourceKeys) !== JSON.stringify(catalogKeys)) throw new Error(`${locale}: key drift`);
      if (sourceKeys.some((key) => typeof catalog[key] !== "string" || !catalog[key].trim())) throw new Error(`${locale}: empty translation`);
      const changed = sourceKeys.filter((key) => catalog[key].trim() !== source[key]);
      if (!changed.length) throw new Error(`${locale}: catalog remained English`);
      return { locale, changed: changed.length, provider: body.source || body.providers?.[0] || "unknown" };
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
      const result = await checkLocale(locale);
      results.push(result);
      console.log(`PASS ${locale} changed=${result.changed} provider=${result.provider}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failures.push({ locale, message });
      console.error(`FAIL ${locale} ${message}`);
    }
  }
}

await Promise.all(Array.from({ length: concurrency }, () => worker()));
results.sort((a, b) => a.locale.localeCompare(b.locale));
failures.sort((a, b) => a.locale.localeCompare(b.locale));

console.log(JSON.stringify({ endpoint, total: locales.length, passed: results.length, failed: failures.length, results, failures }, null, 2));
if (failures.length) process.exit(1);
