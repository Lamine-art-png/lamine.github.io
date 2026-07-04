import { useEffect, useMemo, useState } from "react";
import {
  CATALOGS,
  DEFAULT_LOCALE,
  ENABLED_CODES,
  ENABLED_LOCALES,
  LANGUAGE_STORAGE_KEY,
  LOCALE_BY_CODE,
  LOCALES,
  UNSUPPORTED_LEGACY_LOCALES,
  type LocaleCode,
  type LocaleResolution,
} from "./registry";

function cleanTag(value?: string | null): string {
  return String(value || "auto").trim().replace("_", "-") || "auto";
}
function enabledExact(code: string): LocaleCode | null {
  const lower = code.toLowerCase();
  return ENABLED_CODES.has(lower)
    ? (ENABLED_LOCALES.find((locale) => locale.code.toLowerCase() === lower)?.code || null)
    : null;
}
function enabledForLanguage(languageCode?: string): LocaleCode | null {
  if (!languageCode || languageCode === "auto") return null;
  return ENABLED_LOCALES.find((locale) => locale.languageCode.toLowerCase() === languageCode.toLowerCase())?.code || null;
}

export function resolveLocaleDetailed(value?: string | null): LocaleResolution {
  const requestedLocale = cleanTag(value);
  const lower = requestedLocale.toLowerCase();
  if (lower === "auto") {
    return { requestedLocale: "auto", resolvedLocale: "auto", fallbackReason: "auto", fallbackChain: [DEFAULT_LOCALE] };
  }
  if (UNSUPPORTED_LEGACY_LOCALES.has(lower)) {
    return { requestedLocale, resolvedLocale: "auto", fallbackReason: "legacy_unsupported", fallbackChain: ["auto", DEFAULT_LOCALE] };
  }
  const exact = enabledExact(requestedLocale);
  if (exact) return { requestedLocale, resolvedLocale: exact, fallbackReason: "exact", fallbackChain: [] };

  const known = LOCALE_BY_CODE.get(lower);
  const chain = known?.fallbackChain || [];
  for (const fallback of chain) {
    const exactFallback = enabledExact(fallback);
    if (exactFallback) {
      return { requestedLocale, resolvedLocale: exactFallback, fallbackReason: "regional_fallback", fallbackChain: chain };
    }
    const fallbackMeta = LOCALE_BY_CODE.get(fallback.toLowerCase());
    const languageFallback = enabledForLanguage(fallbackMeta?.languageCode || fallback);
    if (languageFallback) {
      return { requestedLocale, resolvedLocale: languageFallback, fallbackReason: "regional_fallback", fallbackChain: chain };
    }
  }
  const languageRoot = known?.languageCode || requestedLocale.split("-")[0];
  const languageFallback = enabledForLanguage(languageRoot);
  if (languageFallback) {
    return { requestedLocale, resolvedLocale: languageFallback, fallbackReason: "language_fallback", fallbackChain: [languageRoot] };
  }
  return { requestedLocale, resolvedLocale: "auto", fallbackReason: "unsupported_fallback", fallbackChain: ["auto", DEFAULT_LOCALE] };
}

export function normalizeLocale(value?: string | null): LocaleCode {
  return resolveLocaleDetailed(value).resolvedLocale;
}
export function getStoredLocale(): LocaleCode {
  try {
    return normalizeLocale(localStorage.getItem(LANGUAGE_STORAGE_KEY) || localStorage.getItem("agroai_locale") || "auto");
  } catch {
    return "auto";
  }
}
export function currentLocale(): LocaleCode {
  const stored = getStoredLocale();
  if (stored !== "auto") return stored;
  if (typeof navigator === "undefined") return DEFAULT_LOCALE;
  const browser = resolveLocaleDetailed(navigator.language);
  return browser.resolvedLocale === "auto" ? DEFAULT_LOCALE : browser.resolvedLocale;
}
export function isRtlLocale(locale: string) {
  const normalized = normalizeLocale(locale);
  const effective = normalized === "auto" ? DEFAULT_LOCALE : normalized;
  return (LOCALES.find((item) => item.code === effective)?.direction || "ltr") === "rtl";
}
function interpolate(value: string, params?: Record<string, string | number>) {
  if (!params) return value;
  return Object.entries(params).reduce((text, [key, item]) => text.replaceAll(`{${key}}`, String(item)), value);
}
export function t(key: string, locale = currentLocale(), params?: Record<string, string | number>): string {
  const normalized = normalizeLocale(locale);
  const effective = normalized === "auto" ? DEFAULT_LOCALE : normalized;
  const value = CATALOGS[effective]?.[key];
  if (value) return interpolate(value, params);
  if (effective === "en") return key;
  return `[[missing:${effective}:${key}]]`;
}
export function applyLocale(locale = getStoredLocale()) {
  if (typeof document === "undefined") return;
  const normalized = normalizeLocale(locale);
  const effective = normalized === "auto" ? currentLocale() : normalized;
  document.documentElement.lang = effective;
  document.documentElement.dir = isRtlLocale(effective) ? "rtl" : "ltr";
}
export function setStoredLocale(locale: string) {
  const normalized = normalizeLocale(locale);
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
    localStorage.removeItem("agroai_locale");
  } catch {
    // Best effort; switching remains active in memory.
  }
  applyLocale(normalized);
  window.dispatchEvent(new CustomEvent("agroai:locale-change", { detail: { locale: normalized } }));
}
export function localeCoverage() {
  const sourceKeys = Object.keys(CATALOGS.en);
  return Object.fromEntries(
    Object.entries(CATALOGS)
      .filter(([locale]) => ENABLED_CODES.has(locale.toLowerCase()))
      .map(([locale, catalog]) => [locale, sourceKeys.filter((key) => !catalog[key])]),
  );
}
export function useLocale() {
  const [locale, setLocaleState] = useState<LocaleCode>(() => getStoredLocale());
  const effectiveLocale = locale === "auto" ? currentLocale() : locale;
  const localeMeta = LOCALES.find((item) => item.code === locale)
    || LOCALES.find((item) => item.code === effectiveLocale)
    || LOCALES[0];
  const direction = isRtlLocale(effectiveLocale) ? "rtl" : "ltr";

  useEffect(() => {
    applyLocale(locale);
    const listener = ((event: CustomEvent) => {
      setLocaleState(normalizeLocale(event.detail?.locale || getStoredLocale()));
    }) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, [locale]);

  return useMemo(() => ({
    locale,
    effectiveLocale,
    direction,
    localeMeta,
    setLocale: (nextLocale: string) => {
      const normalized = normalizeLocale(nextLocale);
      setStoredLocale(normalized);
      setLocaleState(normalized);
    },
    t: (key: string, params?: Record<string, string | number>) => t(key, effectiveLocale, params),
    coverageReport: localeCoverage,
  }), [direction, effectiveLocale, locale, localeMeta]);
}
