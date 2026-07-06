import { apiClient } from "./api/client";
import { normalizeLocale, TRANSLATIONS } from "./i18n";

const CACHE_PREFIX = "agroai_ui_catalog_v3:";
const INFLIGHT = new Map<string, Promise<boolean>>();

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
    if (parsed.version !== 3 || parsed.sourceFingerprint !== fingerprint || !validCatalog(parsed.catalog, source)) return null;
    return parsed.catalog;
  } catch {
    return null;
  }
}

function writeCached(locale: string, source: Record<string, string>, catalog: Record<string, string>) {
  try {
    const fingerprint = sourceFingerprint(source);
    localStorage.setItem(cacheKey(locale, fingerprint), JSON.stringify({ version: 3, sourceFingerprint: fingerprint, catalog }));
  } catch {
    // Local cache is an optimization only.
  }
}

async function loadLocaleCatalog(effectiveLocale: string, source: Record<string, string>): Promise<boolean> {
  const cached = readCached(effectiveLocale, source);
  if (cached) {
    TRANSLATIONS[effectiveLocale] = cached;
    return true;
  }

  const response = await apiClient.post<CatalogResponse>("/v1/i18n/catalog", {
    locale: effectiveLocale,
    source,
  });
  if (!response || response.status !== "ok" || response.locale !== effectiveLocale || !validCatalog(response.catalog, source)) {
    throw new Error(`Invalid UI translation catalog for ${effectiveLocale}`);
  }

  TRANSLATIONS[effectiveLocale] = response.catalog;
  writeCached(effectiveLocale, source, response.catalog);
  return true;
}

export async function ensureLocaleCatalog(locale: string): Promise<boolean> {
  const effectiveLocale = normalizeLocale(locale);
  if (TRANSLATIONS[effectiveLocale]) return false;

  const source = TRANSLATIONS.en;
  const requestKey = `${effectiveLocale}:${sourceFingerprint(source)}`;
  const existing = INFLIGHT.get(requestKey);
  if (existing) return existing;

  const pending = loadLocaleCatalog(effectiveLocale, source).finally(() => {
    INFLIGHT.delete(requestKey);
  });
  INFLIGHT.set(requestKey, pending);
  return pending;
}
