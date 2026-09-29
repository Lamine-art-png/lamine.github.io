import { sourceFingerprint as SOURCE_FINGERPRINT } from "../../../shared/localization/source.json";

type CatalogEnvelope = {
  schemaVersion: number;
  locale: string;
  direction?: "ltr" | "rtl";
  sourceFingerprint: string;
  status: string;
  catalog: Record<string, string>;
};

// Every release-validated locale catalog ships with the application as its own
// lazily loaded, content-hashed chunk. Switching language loads a static asset
// from the same deployment; it never calls a translation provider. Only locales
// that the release gate enabled are advertised, so a customer can only select a
// locale whose chunk exists in this build.
const LOADERS = import.meta.glob("../../../shared/localization/catalogs/*.json", {
  import: "default",
}) as Record<string, () => Promise<CatalogEnvelope>>;

const LOADER_BY_LOCALE: Record<string, () => Promise<CatalogEnvelope>> = {};
for (const [path, loader] of Object.entries(LOADERS)) {
  const match = /\/([A-Za-z0-9-]+)\.json$/.exec(path);
  if (match) LOADER_BY_LOCALE[match[1]] = loader;
}

export const BUNDLED_LOCALE_CODES = Object.freeze(Object.keys(LOADER_BY_LOCALE).sort());

const LOADED: Record<string, Record<string, string>> = {};
const INFLIGHT = new Map<string, Promise<Record<string, string> | null>>();

function validEnvelope(envelope: CatalogEnvelope | undefined, locale: string): envelope is CatalogEnvelope {
  return Boolean(
    envelope
    && envelope.schemaVersion === 2
    && envelope.status === "complete-generated"
    && envelope.locale === locale
    && envelope.sourceFingerprint === SOURCE_FINGERPRINT
    && envelope.catalog
    && typeof envelope.catalog === "object"
    && !Array.isArray(envelope.catalog),
  );
}

export function hasBundledLocale(locale: string): boolean {
  return Boolean(LOADER_BY_LOCALE[locale]);
}

export function loadedBundledLocaleCatalog(locale: string): Record<string, string> | null {
  return LOADED[locale] || null;
}

/**
 * Load the deployed static catalog for a locale. Resolves to null when the
 * build has no valid catalog for it (the caller keeps the previous locale).
 */
export function loadBundledLocaleCatalog(locale: string): Promise<Record<string, string> | null> {
  if (LOADED[locale]) return Promise.resolve(LOADED[locale]);
  const loader = LOADER_BY_LOCALE[locale];
  if (!loader) return Promise.resolve(null);
  const existing = INFLIGHT.get(locale);
  if (existing) return existing;
  const pending = loader()
    .then((envelope) => {
      if (!validEnvelope(envelope, locale)) return null;
      LOADED[locale] = envelope.catalog;
      return envelope.catalog;
    })
    .finally(() => INFLIGHT.delete(locale));
  INFLIGHT.set(locale, pending);
  return pending;
}
