#!/usr/bin/env node
// Deterministic production localization contract.
//
// Proves, against the deployed site, that every advertised locale is served
// from a shipped, release-validated catalog — the path customers actually use:
//   1. the API language registry equals the release manifest's advertised set;
//   2. the deployed portal bundle maps every advertised non-English locale to a
//      catalog chunk, and each chunk is reachable and contains the exact
//      checked-in release artifact identity (catalogSha256 recomputed here
//      from the catalog content — a translation-only change is detected), the
//      current canonical source fingerprint, and complete status;
//   3. the locale observability endpoint accepts events.
// No translation provider is called; runtime generation is not a customer path.
import fs from "node:fs";
import path from "node:path";
import { catalogSha256 } from "./i18n-catalog-identity.mjs";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const APP = (process.env.AGROAI_APP_ORIGIN || "https://app.agroai-pilot.com").replace(/\/+$/, "");
const API = (process.env.AGROAI_API_ORIGIN || "https://api.agroai-pilot.com").replace(/\/+$/, "");
const ATTEMPTS = Number(process.env.AGROAI_VERIFY_ATTEMPTS || 30);
const DELAY_MS = Number(process.env.AGROAI_VERIFY_DELAY_MS || 20_000);

const manifest = JSON.parse(fs.readFileSync(path.join(root, "shared/supported-locales.json"), "utf8"));
const fingerprint = JSON.parse(fs.readFileSync(path.join(root, "shared/localization/source.json"), "utf8")).sourceFingerprint;
const advertised = manifest.enabledUiLocales.filter((code) => code !== "auto");
const translated = advertised.filter((code) => code !== "en");

const CATALOG_DIR = process.env.AGROAI_CATALOG_DIR || path.join(root, "shared/localization/catalogs");
const expectedIdentity = Object.fromEntries(translated.map((code) => {
  const envelope = JSON.parse(fs.readFileSync(path.join(CATALOG_DIR, `${code}.json`), "utf8"));
  return [code, catalogSha256(envelope)];
}));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function text(url, init) {
  const response = await fetch(url, { redirect: "follow", ...init });
  return { status: response.status, body: await response.text() };
}

async function registryMatches() {
  const { status, body } = await text(`${API}/v1/i18n/languages`);
  if (status !== 200) return `registry_http_${status}`;
  const codes = JSON.parse(body).languages.map((row) => row.code).filter((code) => code !== "auto").sort();
  const expected = [...advertised].sort();
  return JSON.stringify(codes) === JSON.stringify(expected) ? null : `registry_mismatch:api=${codes.length},manifest=${expected.length}`;
}

async function deployedBundle() {
  const index = await text(`${APP}/`);
  const queue = [...new Set(index.body.match(/\/assets\/[A-Za-z0-9._-]+\.js/g) || [])];
  const seen = new Set();
  let js = "";
  // The catalog loader map lives in a lazily imported chunk; follow imports.
  while (queue.length && seen.size < 400) {
    const asset = queue.shift();
    if (seen.has(asset)) continue;
    seen.add(asset);
    const { status, body } = await text(`${APP}${asset}`);
    if (status !== 200) continue;
    js += body;
    if (js.includes('catalogs/pt-BR.json":()=>')) break; // loader map found
    for (const match of body.matchAll(/(?:\.\/|\/assets\/|assets\/)([A-Za-z0-9._-]+\.js)/g)) {
      const next = `/assets/${match[1]}`;
      if (!seen.has(next)) queue.push(next);
    }
  }
  return js;
}

async function catalogsDeployed() {
  const js = await deployedBundle();
  const map = new Map();
  for (const match of js.matchAll(/catalogs\/([A-Za-z-]+)\.json":\(\)=>[^"]{0,40}import\("\.\/([A-Za-z0-9._-]+\.js)"\)/g)) {
    map.set(match[1], match[2]);
  }
  const missing = translated.filter((code) => !map.has(code));
  if (missing.length) return `catalog_chunks_missing:${missing.join(",")}`;
  const failures = [];
  await Promise.all(translated.map(async (code) => {
    const { status, body } = await text(`${APP}/assets/${map.get(code)}`);
    if (status !== 200) failures.push(`${code}:http_${status}`);
    else if (!body.includes(expectedIdentity[code])) failures.push(`${code}:catalog_artifact_not_deployed`);
    else if (!body.includes(fingerprint)) failures.push(`${code}:stale_fingerprint`);
    else if (!body.includes("complete-generated")) failures.push(`${code}:incomplete_status`);
  }));
  return failures.length ? `catalog_chunks_invalid:${failures.sort().join(",")}` : null;
}

async function eventsAccepted() {
  const { status } = await text(`${API}/v1/i18n/events`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: APP },
    body: JSON.stringify({ event: "locale_switch_completed", selectedLocale: "pt-BR", effectiveLocale: "pt-BR", surface: "/release-contract", latencyMs: 1 }),
  });
  return status === 202 ? null : `events_http_${status}`;
}

let lastFailure = "unknown";
for (let attempt = 1; attempt <= ATTEMPTS; attempt += 1) {
  try {
    const failures = (await Promise.all([registryMatches(), catalogsDeployed(), eventsAccepted()])).filter(Boolean);
    if (!failures.length) {
      console.log(JSON.stringify({
        status: "ok",
        advertisedLocales: advertised.length,
        deployedCatalogs: translated.length,
        sourceFingerprint: fingerprint,
        catalogIdentity: "catalogSha256-per-locale",
        runtimeGenerationRequired: false,
      }));
      process.exit(0);
    }
    lastFailure = failures.join(" | ");
  } catch (error) {
    lastFailure = String(error?.message || error);
  }
  console.error(`attempt ${attempt}/${ATTEMPTS}: ${lastFailure}`);
  if (attempt < ATTEMPTS) await sleep(DELAY_MS);
}
console.error(`deterministic production localization contract failed: ${lastFailure}`);
process.exit(1);
