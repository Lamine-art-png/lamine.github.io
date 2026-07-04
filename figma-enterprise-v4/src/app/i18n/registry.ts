import localeManifest from "../../../../shared/supported-locales.json";

import enCore from "../i18n-resources/en/core.json";
import enIntelligence from "../i18n-resources/en/intelligence.json";
import enAccount from "../i18n-resources/en/account.json";
import enOperations from "../i18n-resources/en/operations.json";
import frCore from "../i18n-resources/fr-FR/core.json";
import frIntelligence from "../i18n-resources/fr-FR/intelligence.json";
import frAccount from "../i18n-resources/fr-FR/account.json";
import frOperations from "../i18n-resources/fr-FR/operations.json";

export type LocaleDirection = "ltr" | "rtl";
export type LocaleCode = string;
export type LocaleOption = {
  code: LocaleCode;
  languageCode: string;
  nativeName: string;
  englishName: string;
  direction: LocaleDirection;
  enabled: boolean;
  catalogComplete: boolean;
  fallbackChain: string[];
};
export type LocaleResolution = {
  requestedLocale: string;
  resolvedLocale: LocaleCode;
  fallbackReason: "exact" | "auto" | "legacy_unsupported" | "regional_fallback" | "language_fallback" | "unsupported_fallback";
  fallbackChain: string[];
};
export type MessageCatalog = Record<string, string>;

type RawLocale = { code: string; languageCode: string; direction?: LocaleDirection; fallbackChain?: string[] };
type RuntimeManifest = {
  defaultLocale: string;
  storageKey?: string;
  enabledUiLocales?: string[];
  catalogCompleteLocales?: string[];
  locales: RawLocale[];
  unsupportedLegacyLocales?: string[];
};

const MANIFEST = localeManifest as RuntimeManifest;
const LABELS: Record<string, { nativeName: string; englishName: string }> = {
  auto: { nativeName: "Auto", englishName: "Browser default" },
  en: { nativeName: "English", englishName: "English" },
  "fr-FR": { nativeName: "Français (France)", englishName: "French (France)" },
};
const mergeCatalog = (...parts: MessageCatalog[]): MessageCatalog => Object.assign({}, ...parts);

export const CATALOGS: Record<string, MessageCatalog> = {
  en: mergeCatalog(enCore, enIntelligence, enAccount, enOperations),
  "fr-FR": mergeCatalog(frCore, frIntelligence, frAccount, frOperations),
};
export const LANGUAGE_STORAGE_KEY = String(MANIFEST.storageKey || "agroai_locale_v1");
export const DEFAULT_LOCALE: LocaleCode = String(MANIFEST.defaultLocale || "en");
const ENABLED = new Set((MANIFEST.enabledUiLocales || []).map((code) => code.toLowerCase()));
const COMPLETE = new Set((MANIFEST.catalogCompleteLocales || []).map((code) => code.toLowerCase()));

export const LOCALES: LocaleOption[] = MANIFEST.locales.map((raw) => ({
  ...raw,
  nativeName: LABELS[raw.code]?.nativeName || raw.code,
  englishName: LABELS[raw.code]?.englishName || raw.code,
  direction: raw.direction || "ltr",
  enabled: ENABLED.has(raw.code.toLowerCase()),
  catalogComplete: COMPLETE.has(raw.code.toLowerCase()),
  fallbackChain: raw.fallbackChain || (raw.code === "en" || raw.code === "auto" ? [] : ["en"]),
}));
export const ENABLED_LOCALES = LOCALES.filter((locale) => locale.enabled);
export const UNSUPPORTED_LEGACY_LOCALES = new Set((MANIFEST.unsupportedLegacyLocales || []).map((item) => item.toLowerCase()));
export const ENABLED_CODES = new Set(ENABLED_LOCALES.map((locale) => locale.code.toLowerCase()));
export const LOCALE_BY_CODE = new Map(LOCALES.map((locale) => [locale.code.toLowerCase(), locale]));

function validateRegistry() {
  const seen = new Set<string>();
  for (const locale of LOCALES) {
    const code = locale.code.toLowerCase();
    if (seen.has(code)) throw new Error(`Duplicate locale code: ${locale.code}`);
    seen.add(code);
    if (locale.enabled && locale.code !== "auto" && !locale.catalogComplete) {
      throw new Error(`Enabled locale is not catalog-complete: ${locale.code}`);
    }
    if (locale.enabled && locale.code !== "auto" && !CATALOGS[locale.code]) {
      throw new Error(`Enabled locale has no catalog: ${locale.code}`);
    }
  }
  if (!ENABLED_CODES.has(DEFAULT_LOCALE.toLowerCase())) throw new Error(`Default locale is not enabled: ${DEFAULT_LOCALE}`);
  const sourceKeys = Object.keys(CATALOGS.en).sort();
  for (const locale of ENABLED_LOCALES) {
    if (locale.code === "auto") continue;
    const keys = Object.keys(CATALOGS[locale.code] || {}).sort();
    if (keys.length !== sourceKeys.length || keys.some((key, index) => key !== sourceKeys[index])) {
      throw new Error(`Enabled locale catalog is incomplete: ${locale.code}`);
    }
  }
}
validateRegistry();
