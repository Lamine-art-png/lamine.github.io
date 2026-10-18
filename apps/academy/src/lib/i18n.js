// Localization engine. The language inventory is derived from the Enterprise
// Portal manifest (shared/supported-locales.json) so the Academy offers exactly
// the languages AGRO-AI already supports. UI copy comes from bundled catalogs,
// layered with reviewed database overrides; English is the fallback.
import manifest from "../../../../shared/supported-locales.json" with { type: "json" };
import { CATALOGS, CATALOG_META } from "../i18n/index.js";

const EN = CATALOGS.en;

export const LOCALES = manifest.locales
  .filter((l) => l.code !== "auto" && manifest.enabledUiLocales.includes(l.code))
  .map((l) => ({
    code: l.code,
    lang: l.languageCode,
    nativeName: l.nativeName || l.code,
    englishName: l.englishName || l.code,
    dir: l.direction === "rtl" ? "rtl" : "ltr",
  }));

const BY_CODE = new Map(LOCALES.map((l) => [l.code.toLowerCase(), l]));
const BY_LANG = new Map();
for (const l of LOCALES) if (!BY_LANG.has(l.lang.toLowerCase())) BY_LANG.set(l.lang.toLowerCase(), l);
// Common aliases browsers send that the manifest names differently.
const ALIASES = { nb: "no", nn: "no", fil: "tl", "zh-cn": "zh", "zh-hans": "zh", pt: "pt-BR", fr: "fr-FR" };

export const DEFAULT_LOCALE = "en";

/** Resolve any requested tag to a supported locale code, or null. */
export function matchLocale(tag) {
  if (!tag) return null;
  const t = String(tag).trim().toLowerCase().replace("_", "-");
  if (BY_CODE.has(t)) return BY_CODE.get(t).code;
  if (ALIASES[t]) return ALIASES[t];
  const base = t.split("-")[0];
  if (ALIASES[base]) return ALIASES[base];
  if (BY_CODE.has(base)) return BY_CODE.get(base).code;
  if (BY_LANG.has(base)) return BY_LANG.get(base).code;
  return null;
}

export function negotiate(acceptLanguage) {
  const tags = String(acceptLanguage || "")
    .split(",")
    .map((p) => {
      const [tag, q] = p.trim().split(";q=");
      return { tag, q: q ? Number(q) : 1 };
    })
    .filter((x) => x.tag && x.q > 0)
    .sort((a, b) => b.q - a.q);
  for (const { tag } of tags) {
    const m = matchLocale(tag);
    if (m) return m;
  }
  return DEFAULT_LOCALE;
}

export const localeInfo = (code) => BY_CODE.get(String(code).toLowerCase()) || BY_CODE.get("en");

/**
 * How far the interface is translated for a locale:
 *   "source"   — English, the original
 *   "reviewed" — a catalog reviewed by native speakers
 *   "machine"  — a machine-prepared catalog not yet reviewed
 *   "fallback" — no catalog: English text with the locale's formatting and direction
 */
export function interfaceStatus(code) {
  if (code === "en") return "source";
  if (!CATALOGS[code]) return "fallback";
  return CATALOG_META[code]?.reviewed ? "reviewed" : "machine";
}
export const TRANSLATED_INTERFACE_COUNT = LOCALES.filter((l) => interfaceStatus(l.code) !== "fallback").length;

// Database overrides, cached per isolate for a short time.
let overrideCache = { at: 0, data: new Map() };
export async function loadOverrides(env, force = false) {
  if (!force && Date.now() - overrideCache.at < 60_000) return overrideCache.data;
  const data = new Map();
  try {
    const rows = (await env.DB.prepare("SELECT locale, key, value FROM ui_translations").all()).results;
    for (const r of rows) {
      if (!data.has(r.locale)) data.set(r.locale, {});
      data.get(r.locale)[r.key] = r.value;
    }
  } catch {
    // Missing table during a first deploy must not take the site down.
  }
  overrideCache = { at: Date.now(), data };
  return data;
}
export const clearOverrideCache = () => (overrideCache = { at: 0, data: new Map() });

function interpolate(str, vars) {
  if (!vars) return str;
  return str.replace(/\{(\w+)\}/g, (m, k) => (vars[k] != null ? String(vars[k]) : m));
}

export function makeTranslator(locale, overrides) {
  const cat = CATALOGS[locale] || {};
  const ov = overrides?.get(locale) || {};
  const enOv = overrides?.get("en") || {};
  const t = (key, vars) => {
    const s = ov[key] ?? cat[key] ?? enOv[key] ?? EN[key];
    return s == null ? key : interpolate(s, vars);
  };
  t.has = (key) => key in ov || key in cat;
  t.locale = locale;
  return t;
}

export function catalogCoverage() {
  const total = Object.keys(EN).length;
  return LOCALES.map((l) => {
    const cat = CATALOGS[l.code] || {};
    const translated = Object.keys(EN).filter((k) => k in cat).length;
    return {
      ...l,
      translated,
      total,
      pct: Math.round((translated / total) * 100),
      provenance: l.code === "en" ? "source" : CATALOG_META[l.code]?.provenance || "missing",
    };
  });
}

export function formatDate(locale, iso, opts = { dateStyle: "long" }) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(locale, { timeZone: "UTC", ...opts }).format(new Date(iso));
  } catch {
    return new Intl.DateTimeFormat("en", { timeZone: "UTC", ...opts }).format(new Date(iso));
  }
}

export function formatNumber(locale, n, opts) {
  try {
    return new Intl.NumberFormat(locale, opts).format(n);
  } catch {
    return String(n);
  }
}
