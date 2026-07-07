import literalCatalogPart1 from "../../../shared/ui-literals.en.1.json";
import literalCatalogPart2 from "../../../shared/ui-literals.en.2.json";
import literalCatalogPart3 from "../../../shared/ui-literals.en.3.json";
import literalCatalogPart4 from "../../../shared/ui-literals.en.4.json";
import literalCatalogPart5 from "../../../shared/ui-literals.en.5.json";
import literalCatalogPart6 from "../../../shared/ui-literals.en.6.json";
import { getStoredLocale, t, TRANSLATIONS } from "./i18n";

export const PORTAL_LITERAL_CATALOG: Record<string, string> = Object.assign(
  {},
  literalCatalogPart1,
  literalCatalogPart2,
  literalCatalogPart3,
  literalCatalogPart4,
  literalCatalogPart5,
  literalCatalogPart6,
);

const LITERAL_KEY_BY_TEXT = new Map<string, string>(
  Object.entries(PORTAL_LITERAL_CATALOG).map(([key, value]) => [normalizeLiteralText(value), key]),
);

let coreKeyCount = -1;
let coreKeyByText = new Map<string, string>();

function normalizeLiteralText(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function refreshCoreKeyMap() {
  const entries = Object.entries(TRANSLATIONS.en || {});
  if (entries.length === coreKeyCount) return;
  coreKeyByText = new Map(entries.map(([key, value]) => [normalizeLiteralText(value), key]));
  coreKeyCount = entries.length;
}

export function literalTranslationKey(value: string): string | undefined {
  const normalized = normalizeLiteralText(value);
  const literalKey = LITERAL_KEY_BY_TEXT.get(normalized);
  if (literalKey) return literalKey;
  refreshCoreKeyMap();
  return coreKeyByText.get(normalized);
}

export function hasLiteralTranslationSource(value: string): boolean {
  return Boolean(literalTranslationKey(value));
}

export function translatePortalLiteral(value: string, locale = getStoredLocale()): string {
  const key = literalTranslationKey(value);
  if (!key) return value;
  const translated = t(key, locale);
  if (!translated || translated === key) return value;
  const leading = value.match(/^\s*/)?.[0] || "";
  const trailing = value.match(/\s*$/)?.[0] || "";
  return `${leading}${translated}${trailing}`;
}

export function fullEnglishUiSource(base: Record<string, string>): Record<string, string> {
  return { ...base, ...PORTAL_LITERAL_CATALOG };
}
