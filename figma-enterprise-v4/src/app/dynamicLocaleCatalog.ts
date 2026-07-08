import { apiClient } from "./api/client";
import { installCommercialBoundaryBaseCatalogs } from "./commercialBoundaryI18n";
import { normalizeLocale, TRANSLATIONS } from "./i18n";
import { notifyLocaleRuntime } from "./localeRuntimeStore";
import { fullEnglishUiSource } from "./portalLiteralCatalog";

const CACHE_PREFIX = "agroai_ui_catalog_v5:";
const RETRY_COOLDOWN_MS = 2_000;
const REQUEST_CHUNK_SIZE = 48;
const REQUEST_PARALLELISM = 1;
const INFLIGHT = new Map<string, Promise<boolean>>();
const RETRY_AFTER = new Map<string, number>();

installCommercialBoundaryBaseCatalogs();
const CORE_ENGLISH_SOURCE: Record<string, string> = { ...TRANSLATIONS.en };
const CRITICAL_CORE_KEYS = [
  "language", "save", "saving", "newOperation", "workspace", "operate", "intelligence", "account",
  "tasks", "decisions", "evidence", "reports", "connectors", "askAgroAi", "readiness", "sources",
  "team", "settings", "profile", "billing", "security", "support", "logout", "plan", "settingsTitle",
  "settingsSubtitle", "languageRegion", "languageRegionHint", "subscriptionBilling", "accountProfile",
  "workspacePreferences", "notifications",
] as const;
const CRITICAL_ENGLISH_SOURCE: Record<string, string> = Object.fromEntries(
  CRITICAL_CORE_KEYS.map((key) => [key, CORE_ENGLISH_SOURCE[key]]).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
);

export type CatalogScope = "critical" | "core" | "full";

type CatalogResponse = {
  status: string;
  locale: string;
  catalog: Record<string, string>;
  source?: string;
};

function exactKeyParity(candidate: Record<string, string>, source: Record<string, string>) {
  const sourceKeys = Object.keys(source).sort();
  const candidateKeys = Object.keys(candidate).sort();
  return sourceKeys.length === candidateKeys.length && sourceKeys.every((key, index) => key === candidateKeys[index]);
}

function sourceForScope(scope: CatalogScope) {
  if (scope === "critical") return CRITICAL_ENGLISH_SOURCE;
  if (scope === "core") return CORE_ENGLISH_SOURCE;
  return fullEnglishUiSource(CORE_ENGLISH_SOURCE);
}

function catalogCoversSource(candidate: Record<string, string> | undefined, source: Record<string, string>) {
  if (!candidate) return false;
  return Object.entries(source).every(([key, sourceValue]) => {
    const value = candidate[key];
    return typeof value === "string" && value.trim().length > 0 && placeholderParity(value.trim(), sourceValue);
  });
}

export function hasCompleteLocaleCatalog(locale: string): boolean {
  const effectiveLocale = normalizeLocale(locale);
  const catalog = TRANSLATIONS[effectiveLocale];
  const source = sourceForScope("full");
  return Boolean(catalog && exactKeyParity(catalog, source));
}

export function hasCoreLocaleCatalog(locale: string): boolean {
  const effectiveLocale = normalizeLocale(locale);
  return catalogCoversSource(TRANSLATIONS[effectiveLocale], sourceForScope("core"));
}

export function hasCriticalLocaleCatalog(locale: string): boolean {
  const effectiveLocale = normalizeLocale(locale);
  return catalogCoversSource(TRANSLATIONS[effectiveLocale], sourceForScope("critical"));
}

function installLocaleCatalog(locale: string, source: Record<string, string>, catalog: Record<string, string>, persist: boolean) {
  TRANSLATIONS[locale] = { ...(TRANSLATIONS[locale] || {}), ...catalog };
  if (persist) writeCached(locale, source, catalog);
  notifyLocaleRuntime();
}

function placeholderSignature(value: string): string[] | null {
  const tokens: string[] = [];
  let index = 0;
  while (index < value.length) {
    const char = value[index];
    if (char === "}") return null;
    if (char !== "{") {
      index += 1;
      continue;
    }
    const end = value.indexOf("}", index + 1);
    if (end < 0) return null;
    const name = value.slice(index + 1, end);
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) return null;
    tokens.push(`{${name}}`);
    index = end + 1;
  }
  return tokens.sort();
}

function placeholderParity(candidate: string, source: string) {
  const candidateSignature = placeholderSignature(candidate);
  const sourceSignature = placeholderSignature(source);
  if (!candidateSignature || !sourceSignature || candidateSignature.length !== sourceSignature.length) return false;
  return sourceSignature.every((token, index) => token === candidateSignature[index]);
}

function validCatalog(candidate: unknown, source: Record<string, string>): candidate is Record<string, string> {
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
  const catalog = candidate as Record<string, unknown>;
  if (!exactKeyParity(catalog as Record<string, string>, source)) return false;
  return Object.entries(catalog).every(([key, value]) => {
    if (typeof value !== "string" || value.trim().length === 0) return false;
    return placeholderParity(value.trim(), source[key]);
  });
}

function sourceFingerprint(source: Record<string, string>) {
  const stable = Object.keys(source)
    .sort()
    .map((key) => `${key}\u0000${source[key]}`)
    .join("\u0001");
  let hash = 2166136261;
  for (let index = 0; index < stable.length; index += 1) {
    hash ^= stable.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function cacheKey(locale: string, fingerprint: string) {
  return `${CACHE_PREFIX}${locale}:${fingerprint}`;
}

function readCached(locale: string, source: Record<string, string>) {
  try {
    const fingerprint = sourceFingerprint(source);
    const raw = localStorage.getItem(cacheKey(locale, fingerprint));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { version?: number; sourceFingerprint?: string; catalog?: unknown };
    if (parsed.version !== 5 || parsed.sourceFingerprint !== fingerprint || !validCatalog(parsed.catalog, source)) return null;
    return parsed.catalog;
  } catch {
    return null;
  }
}

function cachedCoverage(locale: string, source: Record<string, string>): Record<string, string> | null {
  const exact = readCached(locale, source);
  if (exact) return exact;
  try {
    const prefix = `${CACHE_PREFIX}${locale}:`;
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key?.startsWith(prefix)) continue;
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw) as { version?: number; catalog?: unknown };
      if (parsed.version !== 5 || !parsed.catalog || typeof parsed.catalog !== "object" || Array.isArray(parsed.catalog)) continue;
      const catalog = parsed.catalog as Record<string, string>;
      if (!catalogCoversSource(catalog, source)) continue;
      return Object.fromEntries(Object.keys(source).map((sourceKey) => [sourceKey, catalog[sourceKey].trim()]));
    }
  } catch {
    return null;
  }
  return null;
}

function writeCached(locale: string, source: Record<string, string>, catalog: Record<string, string>) {
  try {
    const fingerprint = sourceFingerprint(source);
    localStorage.setItem(cacheKey(locale, fingerprint), JSON.stringify({ version: 5, sourceFingerprint: fingerprint, catalog }));
  } catch {
    // Local cache is an optimization only.
  }
}

function clearCachedLocale(locale: string) {
  try {
    const prefix = `${CACHE_PREFIX}${locale}:`;
    const keys: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key?.startsWith(prefix)) keys.push(key);
    }
    keys.forEach((key) => localStorage.removeItem(key));
  } catch {
    // Cache invalidation is best-effort only.
  }
}

export function primeLocaleCatalogFromCache(locale: string, scope: CatalogScope = "critical"): boolean {
  const effectiveLocale = normalizeLocale(locale);
  const source = sourceForScope(scope);
  if (effectiveLocale === "en") {
    installLocaleCatalog("en", source, source, false);
    return true;
  }
  if (catalogCoversSource(TRANSLATIONS[effectiveLocale], source)) return true;
  const cached = cachedCoverage(effectiveLocale, source);
  if (!cached) return false;
  installLocaleCatalog(effectiveLocale, source, cached, false);
  return true;
}

function sourceChunks(source: Record<string, string>): Record<string, string>[] {
  const entries = Object.entries(source);
  const chunks: Record<string, string>[] = [];
  for (let index = 0; index < entries.length; index += REQUEST_CHUNK_SIZE) {
    chunks.push(Object.fromEntries(entries.slice(index, index + REQUEST_CHUNK_SIZE)));
  }
  return chunks;
}

function reusableCatalog(locale: string, source: Record<string, string>): Record<string, string> {
  const current = TRANSLATIONS[locale] || {};
  const reusable: Record<string, string> = {};
  for (const [key, sourceValue] of Object.entries(source)) {
    const value = current[key];
    if (typeof value === "string" && value.trim().length > 0 && placeholderParity(value.trim(), sourceValue)) {
      reusable[key] = value.trim();
    }
  }
  return reusable;
}

async function loadLocaleCatalog(effectiveLocale: string, source: Record<string, string>, persistFinal: boolean): Promise<boolean> {
  const cached = cachedCoverage(effectiveLocale, source);
  if (cached) {
    installLocaleCatalog(effectiveLocale, source, cached, false);
    return true;
  }

  const merged = reusableCatalog(effectiveLocale, source);
  const missingSource = Object.fromEntries(Object.entries(source).filter(([key]) => !(key in merged)));
  const chunks = sourceChunks(missingSource);

  for (let index = 0; index < chunks.length; index += REQUEST_PARALLELISM) {
    const wave = chunks.slice(index, index + REQUEST_PARALLELISM);
    const settled = await Promise.allSettled(wave.map(async (chunk) => {
      const response = await apiClient.post<CatalogResponse>("/v1/i18n/catalog", {
        locale: effectiveLocale,
        source: chunk,
      });
      if (!response || response.status !== "ok" || response.locale !== effectiveLocale || !validCatalog(response.catalog, chunk)) {
        throw new Error(`Invalid UI translation catalog for ${effectiveLocale}`);
      }
      return { chunk, catalog: response.catalog };
    }));

    let waveFailure: unknown = null;
    for (const result of settled) {
      if (result.status === "fulfilled") {
        const { chunk, catalog } = result.value;
        Object.assign(merged, catalog);
        // Progressive translation remains visible in-memory. Only a complete
        // full-scope catalog may persist across sessions.
        installLocaleCatalog(effectiveLocale, chunk, catalog, false);
      } else if (!waveFailure) {
        waveFailure = result.reason;
      }
    }
    if (waveFailure) throw waveFailure;
  }

  if (!validCatalog(merged, source)) {
    throw new Error(`Incomplete UI translation catalog for ${effectiveLocale}`);
  }

  installLocaleCatalog(effectiveLocale, source, merged, persistFinal);
  return true;
}

export async function ensureLocaleCatalog(locale: string, scope: CatalogScope = "full"): Promise<boolean> {
  const effectiveLocale = normalizeLocale(locale);
  const source = sourceForScope(scope);
  const current = TRANSLATIONS[effectiveLocale];
  if (effectiveLocale === "en") {
    installLocaleCatalog("en", source, source, false);
    return true;
  }
  if (catalogCoversSource(current, source)) return true;

  const inflightKey = `${effectiveLocale}:${scope}`;
  const inflight = INFLIGHT.get(inflightKey);
  if (inflight) return inflight;

  const retryAt = RETRY_AFTER.get(inflightKey) || 0;
  if (retryAt > Date.now()) return false;

  const request = loadLocaleCatalog(effectiveLocale, source, scope === "full")
    .then((ok) => {
      if (ok) RETRY_AFTER.delete(inflightKey);
      return ok;
    })
    .catch(() => {
      if (scope === "full") clearCachedLocale(effectiveLocale);
      RETRY_AFTER.set(inflightKey, Date.now() + RETRY_COOLDOWN_MS);
      return false;
    })
    .finally(() => {
      INFLIGHT.delete(inflightKey);
    });
  INFLIGHT.set(inflightKey, request);
  return request;
}
