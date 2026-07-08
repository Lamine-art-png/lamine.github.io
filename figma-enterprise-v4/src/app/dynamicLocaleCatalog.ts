import { apiClient } from "./api/client";
import { installCommercialBoundaryBaseCatalogs } from "./commercialBoundaryI18n";
import { normalizeLocale, TRANSLATIONS } from "./i18n";
import { notifyLocaleRuntime } from "./localeRuntimeStore";
import { fullEnglishUiSource } from "./portalLiteralCatalog";

const CACHE_PREFIX = "agroai_ui_catalog_v6:";
const LEGACY_CACHE_PREFIX = "agroai_ui_catalog_v5:";
const RETRY_COOLDOWN_MS = 1_500;
const REQUEST_CHUNK_SIZE = 32;
const REQUEST_PARALLELISM = 3;
const MAX_HYDRATION_PASSES = 3;
const MAX_CHUNK_ATTEMPTS = 3;
const INFLIGHT = new Map<string, Promise<boolean>>();
const RETRY_AFTER = new Map<string, number>();

installCommercialBoundaryBaseCatalogs();
const CORE_ENGLISH_SOURCE: Record<string, string> = { ...TRANSLATIONS.en };
const CRITICAL_CORE_KEYS = [
  "app.loadingPortal", "language", "save", "saving", "newOperation", "workspace", "operate", "intelligence", "account",
  "tasks", "decisions", "evidence", "reports", "connectors", "askAgroAi", "readiness", "sources", "team", "settings",
  "profile", "billing", "security", "support", "logout", "plan", "settingsTitle", "settingsSubtitle", "languageRegion",
  "languageRegionHint", "subscriptionBilling", "accountProfile", "workspacePreferences", "notifications",
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

type CacheEnvelope = {
  version?: number;
  sourceFingerprint?: string;
  source?: unknown;
  catalog?: unknown;
};

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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

function catalogCoversSource(candidate: Record<string, string> | undefined, source: Record<string, string>) {
  if (!candidate) return false;
  return Object.entries(source).every(([key, sourceValue]) => {
    const value = candidate[key];
    return typeof value === "string" && value.trim().length > 0 && placeholderParity(value.trim(), sourceValue);
  });
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

function cacheKey(prefix: string, locale: string, fingerprint: string) {
  return `${prefix}${locale}:${fingerprint}`;
}

function installLocaleCatalog(locale: string, source: Record<string, string>, catalog: Record<string, string>, persist: boolean) {
  TRANSLATIONS[locale] = { ...(TRANSLATIONS[locale] || {}), ...catalog };
  if (persist) writeCached(locale, source, catalog);
  notifyLocaleRuntime();
}

function readExactCached(locale: string, source: Record<string, string>): Record<string, string> | null {
  const fingerprint = sourceFingerprint(source);
  for (const prefix of [CACHE_PREFIX, LEGACY_CACHE_PREFIX]) {
    try {
      const raw = localStorage.getItem(cacheKey(prefix, locale, fingerprint));
      if (!raw) continue;
      const parsed = JSON.parse(raw) as CacheEnvelope;
      const expectedVersion = prefix === CACHE_PREFIX ? 6 : 5;
      if (parsed.version !== expectedVersion || parsed.sourceFingerprint !== fingerprint || !validCatalog(parsed.catalog, source)) continue;
      return parsed.catalog;
    } catch {
      // Ignore corrupt optimization entries.
    }
  }
  return null;
}

function cachedReusable(locale: string, source: Record<string, string>): Record<string, string> {
  const exact = readExactCached(locale, source);
  if (exact) return exact;

  const merged: Record<string, string> = {};
  try {
    const prefix = `${CACHE_PREFIX}${locale}:`;
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key?.startsWith(prefix)) continue;
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw) as CacheEnvelope;
      if (parsed.version !== 6 || !parsed.source || typeof parsed.source !== "object" || Array.isArray(parsed.source)) continue;
      if (!parsed.catalog || typeof parsed.catalog !== "object" || Array.isArray(parsed.catalog)) continue;
      const cachedSource = parsed.source as Record<string, unknown>;
      const cachedCatalog = parsed.catalog as Record<string, unknown>;

      for (const [sourceKey, sourceValue] of Object.entries(source)) {
        if (cachedSource[sourceKey] !== sourceValue) continue;
        const translated = cachedCatalog[sourceKey];
        if (typeof translated !== "string" || !translated.trim() || !placeholderParity(translated.trim(), sourceValue)) continue;
        merged[sourceKey] = translated.trim();
      }
    }
  } catch {
    return merged;
  }
  return merged;
}

function writeCached(locale: string, source: Record<string, string>, catalog: Record<string, string>) {
  try {
    const fingerprint = sourceFingerprint(source);
    localStorage.setItem(cacheKey(CACHE_PREFIX, locale, fingerprint), JSON.stringify({
      version: 6,
      sourceFingerprint: fingerprint,
      source,
      catalog,
    }));
  } catch {
    // Local cache is an optimization only.
  }
}

function clearCachedLocale(locale: string) {
  try {
    const prefixes = [`${CACHE_PREFIX}${locale}:`, `${LEGACY_CACHE_PREFIX}${locale}:`];
    const keys: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key && prefixes.some((prefix) => key.startsWith(prefix))) keys.push(key);
    }
    keys.forEach((key) => localStorage.removeItem(key));
  } catch {
    // Cache invalidation is best-effort only.
  }
}

export function hasCompleteLocaleCatalog(locale: string): boolean {
  const effectiveLocale = normalizeLocale(locale);
  const catalog = TRANSLATIONS[effectiveLocale];
  return Boolean(catalog && catalogCoversSource(catalog, sourceForScope("full")));
}

export function hasCoreLocaleCatalog(locale: string): boolean {
  const effectiveLocale = normalizeLocale(locale);
  return catalogCoversSource(TRANSLATIONS[effectiveLocale], sourceForScope("core"));
}

export function hasCriticalLocaleCatalog(locale: string): boolean {
  const effectiveLocale = normalizeLocale(locale);
  return catalogCoversSource(TRANSLATIONS[effectiveLocale], sourceForScope("critical"));
}

export function primeLocaleCatalogFromCache(locale: string, scope: CatalogScope = "critical"): boolean {
  const effectiveLocale = normalizeLocale(locale);
  const source = sourceForScope(scope);
  if (effectiveLocale === "en") {
    installLocaleCatalog("en", source, source, false);
    return true;
  }
  if (catalogCoversSource(TRANSLATIONS[effectiveLocale], source)) return true;
  const reusable = cachedReusable(effectiveLocale, source);
  if (!catalogCoversSource(reusable, source)) return false;
  installLocaleCatalog(effectiveLocale, source, reusable, false);
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
  const reusable = cachedReusable(locale, source);
  for (const [key, sourceValue] of Object.entries(source)) {
    const value = current[key];
    if (typeof value === "string" && value.trim().length > 0 && placeholderParity(value.trim(), sourceValue)) {
      reusable[key] = value.trim();
    }
  }
  return reusable;
}

async function requestChunk(effectiveLocale: string, chunk: Record<string, string>): Promise<Record<string, string>> {
  let lastError: unknown = new Error(`UI translation unavailable for ${effectiveLocale}`);
  for (let attempt = 1; attempt <= MAX_CHUNK_ATTEMPTS; attempt += 1) {
    try {
      const response = await apiClient.post<CatalogResponse>("/v1/i18n/catalog", {
        locale: effectiveLocale,
        source: chunk,
      });
      if (!response || response.status !== "ok" || response.locale !== effectiveLocale || !validCatalog(response.catalog, chunk)) {
        throw new Error(`Invalid UI translation catalog for ${effectiveLocale}`);
      }
      return response.catalog;
    } catch (error) {
      lastError = error;
      if (attempt < MAX_CHUNK_ATTEMPTS) await delay(250 * (2 ** (attempt - 1)));
    }
  }
  throw lastError;
}

async function loadLocaleCatalog(effectiveLocale: string, source: Record<string, string>, persistFinal: boolean): Promise<boolean> {
  const merged = reusableCatalog(effectiveLocale, source);
  if (catalogCoversSource(merged, source)) {
    installLocaleCatalog(effectiveLocale, source, merged, persistFinal);
    return true;
  }

  let lastError: unknown = null;
  for (let pass = 1; pass <= MAX_HYDRATION_PASSES; pass += 1) {
    const missingSource = Object.fromEntries(Object.entries(source).filter(([key]) => !(key in merged)));
    if (!Object.keys(missingSource).length) break;
    const chunks = sourceChunks(missingSource);

    for (let index = 0; index < chunks.length; index += REQUEST_PARALLELISM) {
      const wave = chunks.slice(index, index + REQUEST_PARALLELISM);
      const settled = await Promise.allSettled(wave.map(async (chunk) => ({ chunk, catalog: await requestChunk(effectiveLocale, chunk) })));
      for (const result of settled) {
        if (result.status === "fulfilled") {
          const { chunk, catalog } = result.value;
          Object.assign(merged, catalog);
          // Keep progressive translations visible in memory, but persist only
          // after a complete full-scope catalog passes validation.
          installLocaleCatalog(effectiveLocale, chunk, catalog, false);
        } else {
          lastError = result.reason;
        }
      }
    }

    if (catalogCoversSource(merged, source)) break;
    if (pass < MAX_HYDRATION_PASSES) await delay(400 * pass);
  }

  if (!catalogCoversSource(merged, source)) {
    const missingCount = Object.keys(source).filter((key) => !(key in merged)).length;
    throw new Error(`Incomplete UI translation catalog for ${effectiveLocale}; missing=${missingCount}; cause=${String(lastError || "unknown")}`);
  }

  installLocaleCatalog(effectiveLocale, source, merged, persistFinal);
  return true;
}

export async function ensureLocaleCatalog(locale: string, scope: CatalogScope = "full"): Promise<boolean> {
  const effectiveLocale = normalizeLocale(locale);
  const source = sourceForScope(scope);
  const current = TRANSLATIONS[effectiveLocale];

  if (effectiveLocale === "en") {
    if (catalogCoversSource(current, source)) return false;
    installLocaleCatalog("en", source, source, false);
    return true;
  }
  if (catalogCoversSource(current, source)) return false;

  const requestKey = `${effectiveLocale}:${sourceFingerprint(source)}`;
  const retryAfter = RETRY_AFTER.get(requestKey) || 0;
  if (retryAfter > Date.now()) throw new Error(`UI translation retry cooldown for ${effectiveLocale}`);
  if (retryAfter) RETRY_AFTER.delete(requestKey);

  const existing = INFLIGHT.get(requestKey);
  if (existing) return existing;

  const pending = loadLocaleCatalog(effectiveLocale, source, scope === "full")
    .then((changed) => {
      RETRY_AFTER.delete(requestKey);
      return changed;
    })
    .catch((error) => {
      if (scope === "full") clearCachedLocale(effectiveLocale);
      RETRY_AFTER.set(requestKey, Date.now() + RETRY_COOLDOWN_MS);
      throw error;
    })
    .finally(() => {
      INFLIGHT.delete(requestKey);
    });
  INFLIGHT.set(requestKey, pending);
  return pending;
}
