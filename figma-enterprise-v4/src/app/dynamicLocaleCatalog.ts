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

export type CatalogScope = "core" | "full";

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
  return scope === "core" ? CORE_ENGLISH_SOURCE : fullEnglishUiSource(CORE_ENGLISH_SOURCE);
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

function writeCached(locale: string, source: Record<string, string>, catalog: Record<string, string>) {
  try {
    const fingerprint = sourceFingerprint(source);
    localStorage.setItem(cacheKey(locale, fingerprint), JSON.stringify({ version: 5, sourceFingerprint: fingerprint, catalog }));
  } catch {
    // Local cache is an optimization only.
  }
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

async function loadLocaleCatalog(effectiveLocale: string, source: Record<string, string>): Promise<boolean> {
  const cached = readCached(effectiveLocale, source);
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

  installLocaleCatalog(effectiveLocale, source, merged, true);
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

  const pending = loadLocaleCatalog(effectiveLocale, source)
    .then((changed) => {
      RETRY_AFTER.delete(requestKey);
      return changed;
    })
    .catch((error) => {
      RETRY_AFTER.set(requestKey, Date.now() + RETRY_COOLDOWN_MS);
      throw error;
    })
    .finally(() => {
      INFLIGHT.delete(requestKey);
    });
  INFLIGHT.set(requestKey, pending);
  return pending;
}
