import { apiClient } from "./api/client";
import { normalizeLocale, TRANSLATIONS } from "./i18n";

const CACHE_PREFIX = "agroai_ui_catalog_v1:";

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

function validCatalog(candidate: unknown, source: Record<string, string>): candidate is Record<string, string> {
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
  const catalog = candidate as Record<string, unknown>;
  if (!exactKeyParity(catalog as Record<string, string>, source)) return false;
  return Object.values(catalog).every((value) => typeof value === "string" && value.trim().length > 0);
}

function cacheKey(locale: string) {
  return `${CACHE_PREFIX}${locale}`;
}

function readCached(locale: string, source: Record<string, string>) {
  try {
    const raw = localStorage.getItem(cacheKey(locale));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { version?: number; catalog?: unknown };
    if (parsed.version !== 1 || !validCatalog(parsed.catalog, source)) return null;
    return parsed.catalog;
  } catch {
    return null;
  }
}

function writeCached(locale: string, catalog: Record<string, string>) {
  try {
    localStorage.setItem(cacheKey(locale), JSON.stringify({ version: 1, catalog }));
  } catch {
    // Local cache is an optimization only.
  }
}

export async function ensureLocaleCatalog(locale: string): Promise<boolean> {
  const effectiveLocale = normalizeLocale(locale);
  if (TRANSLATIONS[effectiveLocale]) return false;

  const source = TRANSLATIONS.en;
  const cached = readCached(effectiveLocale, source);
  if (cached) {
    TRANSLATIONS[effectiveLocale] = cached;
    return true;
  }

  const response = await apiClient.post<CatalogResponse>("/v1/i18n/catalog", {
    locale: effectiveLocale,
    source,
  });
  if (!response || response.status !== "ok" || !validCatalog(response.catalog, source)) {
    throw new Error(`Invalid UI translation catalog for ${effectiveLocale}`);
  }

  TRANSLATIONS[effectiveLocale] = response.catalog;
  writeCached(effectiveLocale, response.catalog);
  return true;
}
