import literalCatalogPart1 from "../../../shared/ui-literals.en.1.json";
import literalCatalogPart2 from "../../../shared/ui-literals.en.2.json";
import literalCatalogPart3 from "../../../shared/ui-literals.en.3.json";
import literalCatalogPart4 from "../../../shared/ui-literals.en.4.json";
import literalCatalogPart5 from "../../../shared/ui-literals.en.5.json";
import literalCatalogPart6 from "../../../shared/ui-literals.en.6.json";
import literalCatalogPart7 from "../../../shared/ui-literals.en.7.json";
import dynamicCopyCatalog from "../../../shared/ui-dynamic-copy.en.json";
import dynamicCopyExtraCatalog from "../../../shared/ui-dynamic-copy-extra.en.json";
import { formatTranslation, getStoredLocale, t, TRANSLATIONS } from "./i18n";

export const DYNAMIC_UI_COPY_CATALOG: Record<string, string> = {
  ...dynamicCopyCatalog,
  ...dynamicCopyExtraCatalog,
};

export const PORTAL_LITERAL_CATALOG: Record<string, string> = Object.assign(
  {},
  literalCatalogPart1,
  literalCatalogPart2,
  literalCatalogPart3,
  literalCatalogPart4,
  literalCatalogPart5,
  literalCatalogPart6,
  literalCatalogPart7,
  DYNAMIC_UI_COPY_CATALOG,
);

function normalizeLiteralText(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

type TemplateMatcher = {
  key: string;
  names: string[];
  regex: RegExp;
};

function buildTemplateMatcher(key: string, template: string): TemplateMatcher | null {
  const names: string[] = [];
  const token = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;
  let cursor = 0;
  let pattern = "^";
  let match: RegExpExecArray | null;
  while ((match = token.exec(template)) !== null) {
    pattern += escapeRegex(template.slice(cursor, match.index));
    pattern += "(.+?)";
    names.push(match[1]);
    cursor = match.index + match[0].length;
  }
  if (!names.length) return null;
  pattern += escapeRegex(template.slice(cursor));
  pattern += "$";
  return { key, names, regex: new RegExp(pattern, "u") };
}

const LITERAL_KEY_BY_TEXT = new Map<string, string>(
  Object.entries(PORTAL_LITERAL_CATALOG).map(([key, value]) => [normalizeLiteralText(value), key]),
);
const TEMPLATE_MATCHERS: TemplateMatcher[] = Object.entries(PORTAL_LITERAL_CATALOG)
  .map(([key, value]) => buildTemplateMatcher(key, normalizeLiteralText(value)))
  .filter((value): value is TemplateMatcher => Boolean(value));

let coreKeyCount = -1;
let coreKeyByText = new Map<string, string>();

function refreshCoreKeyMap() {
  const entries = Object.entries(TRANSLATIONS.en || {});
  if (entries.length === coreKeyCount) return;
  coreKeyByText = new Map(entries.map(([key, value]) => [normalizeLiteralText(value), key]));
  coreKeyCount = entries.length;
}

function templateMatch(value: string): { key: string; values: Record<string, string> } | null {
  const normalized = normalizeLiteralText(value);
  for (const matcher of TEMPLATE_MATCHERS) {
    const match = normalized.match(matcher.regex);
    if (!match) continue;
    const values: Record<string, string> = {};
    matcher.names.forEach((name, index) => { values[name] = match[index + 1]; });
    return { key: matcher.key, values };
  }
  return null;
}

export function literalTranslationKey(value: string): string | undefined {
  const normalized = normalizeLiteralText(value);
  const literalKey = LITERAL_KEY_BY_TEXT.get(normalized);
  if (literalKey) return literalKey;
  const matchedTemplate = templateMatch(normalized);
  if (matchedTemplate) return matchedTemplate.key;
  refreshCoreKeyMap();
  return coreKeyByText.get(normalized);
}

export function hasLiteralTranslationSource(value: string): boolean {
  return Boolean(literalTranslationKey(value));
}

export function translatePortalLiteral(value: string, locale = getStoredLocale()): string {
  const normalized = normalizeLiteralText(value);
  const exactKey = LITERAL_KEY_BY_TEXT.get(normalized);
  const matchedTemplate = exactKey ? null : templateMatch(normalized);
  refreshCoreKeyMap();
  const key = exactKey || matchedTemplate?.key || coreKeyByText.get(normalized);
  if (!key) return value;
  const translated = t(key, locale);
  if (!translated || translated === key) return value;
  const leading = value.match(/^\s*/)?.[0] || "";
  const trailing = value.match(/\s*$/)?.[0] || "";
  if (!matchedTemplate) return `${leading}${translated}${trailing}`;

  const localizedValues = Object.fromEntries(
    Object.entries(matchedTemplate.values).map(([name, captured]) => {
      const capturedKey = LITERAL_KEY_BY_TEXT.get(normalizeLiteralText(captured));
      const localized = capturedKey ? t(capturedKey, locale) : captured;
      return [name, localized && localized !== capturedKey ? localized : captured];
    }),
  );
  return `${leading}${formatTranslation(translated, localizedValues)}${trailing}`;
}

export function dynamicCopySourceForNamespaces(namespaces: readonly string[]): Record<string, string> {
  const prefixes = namespaces.map((namespace) => `dynamic.${namespace}.`);
  return Object.fromEntries(
    Object.entries(DYNAMIC_UI_COPY_CATALOG).filter(([key]) => prefixes.some((prefix) => key.startsWith(prefix))),
  );
}

export function portalCopySourceForValues(values: readonly string[]): Record<string, string> {
  const source: Record<string, string> = {};
  for (const value of values) {
    const normalized = normalizeLiteralText(value);
    const key = LITERAL_KEY_BY_TEXT.get(normalized);
    if (key && PORTAL_LITERAL_CATALOG[key] === value) source[key] = value;
  }
  return source;
}

export function fullEnglishUiSource(base: Record<string, string>): Record<string, string> {
  return { ...base, ...PORTAL_LITERAL_CATALOG };
}
