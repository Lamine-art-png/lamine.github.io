import sourceEnvelope from "../../../shared/localization/source.json";

type SourceEnvelope = {
  schemaVersion: number;
  sourceFingerprint: string;
  catalog: Record<string, string>;
};

type CatalogEnvelope = {
  schemaVersion: number;
  locale: string;
  direction?: "ltr" | "rtl";
  sourceFingerprint: string;
  status: string;
  catalog: Record<string, string>;
};

const source = sourceEnvelope as SourceEnvelope;
const sourceKeys = Object.keys(source.catalog).sort();

const modules = import.meta.glob("../../../shared/localization/catalogs/*.json", {
  eager: true,
  import: "default",
}) as Record<string, CatalogEnvelope>;

function validCatalog(envelope: CatalogEnvelope): boolean {
  if (!envelope || envelope.schemaVersion !== 2 || envelope.status !== "complete-generated") return false;
  if (envelope.sourceFingerprint !== source.sourceFingerprint) return false;
  if (!envelope.catalog || typeof envelope.catalog !== "object" || Array.isArray(envelope.catalog)) return false;

  const keys = Object.keys(envelope.catalog).sort();
  if (keys.length !== sourceKeys.length || keys.some((key, index) => key !== sourceKeys[index])) return false;

  for (const [key, original] of Object.entries(source.catalog)) {
    const value = envelope.catalog[key];
    if (typeof value !== "string" || !value.trim() || value.trim().toLowerCase() === "[object object]") return false;
    const sourceTokens = original.match(/\{[A-Za-z_][A-Za-z0-9_]*\}/g)?.sort() || [];
    const translatedTokens = value.match(/\{[A-Za-z_][A-Za-z0-9_]*\}/g)?.sort() || [];
    if (sourceTokens.length !== translatedTokens.length || sourceTokens.some((token, index) => token !== translatedTokens[index])) return false;
  }
  return true;
}

export const BUNDLED_LOCALE_CATALOGS: Record<string, Record<string, string>> = {};

for (const moduleValue of Object.values(modules)) {
  const envelope = moduleValue as CatalogEnvelope;
  if (!validCatalog(envelope)) continue;
  BUNDLED_LOCALE_CATALOGS[envelope.locale] = envelope.catalog;
}

export const BUNDLED_LOCALE_CODES = Object.freeze(Object.keys(BUNDLED_LOCALE_CATALOGS).sort());

export function hasBundledCompleteLocale(locale: string) {
  return Boolean(BUNDLED_LOCALE_CATALOGS[locale]);
}
