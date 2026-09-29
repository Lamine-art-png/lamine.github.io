// Shared black-box localization assertions. No endpoint is mocked: the page
// renders whatever the deployed build ships.
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd(), "..");
export const manifest = JSON.parse(fs.readFileSync(path.join(root, "shared/supported-locales.json"), "utf8"));
export const source = JSON.parse(fs.readFileSync(path.join(root, "shared/localization/source.json"), "utf8")).catalog;
export const directionByLocale = new Map((manifest.locales || []).map((row) => [row.code, row.direction || "ltr"]));

export function loadCatalog(locale) {
  if (locale === "en") return source;
  return JSON.parse(fs.readFileSync(path.join(root, "shared/localization/catalogs", `${locale}.json`), "utf8")).catalog;
}

export function keyFor(value) {
  const entry = Object.entries(source).find(([, text]) => text === value);
  if (!entry) throw new Error(`Missing canonical source literal: ${value}`);
  return entry[0];
}

function translatableProse(value) {
  return (value.match(/[A-Za-z]{3,}/g) || []).length >= 2
    && !/^\s*(?:curl\s|-H\s|(?:GET|POST|PUT|PATCH|DELETE)\s+\/|\{\s*")|\$[A-Z][A-Z0-9_]{2,}/.test(value);
}

/** Rendered strings that are exactly English source prose whose deployed translation differs. */
export async function englishLeaks(page, catalog) {
  const englishToKeys = new Map();
  for (const [key, value] of Object.entries(source)) {
    const normalized = value.trim().replace(/\s+/g, " ");
    if (!translatableProse(normalized)) continue;
    if (!englishToKeys.has(normalized)) englishToKeys.set(normalized, []);
    englishToKeys.get(normalized).push(key);
  }
  const rendered = await page.evaluate(() => {
    const out = new Set();
    const skip = (el) => el.closest('[data-language-selector], [data-i18n-ignore], script, style, noscript');
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || skip(parent)) continue;
      const style = getComputedStyle(parent);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const text = (node.nodeValue || "").trim().replace(/\s+/g, " ");
      if (text) out.add(text);
    }
    for (const el of document.querySelectorAll("[placeholder],[aria-label],[title]")) {
      if (skip(el)) continue;
      for (const attr of ["placeholder", "aria-label", "title"]) {
        const value = (el.getAttribute(attr) || "").trim().replace(/\s+/g, " ");
        if (value) out.add(value);
      }
    }
    return [...out];
  });
  return rendered.filter((text) => {
    const keys = englishToKeys.get(text);
    return keys && keys.every((key) => (catalog[key] || "").trim().replace(/\s+/g, " ") !== text);
  });
}

export function languageSelect(page) {
  return page.locator("select").filter({ has: page.locator('option[value="en"]') }).first();
}

export const SIGNUP_KEYS = {
  createAccount: keyFor("Create account"),
  title: keyFor("Create your AGRO-AI account"),
  fullName: keyFor("Full name"),
  password: keyFor("Password"),
  organizationType: keyFor("Organization type"),
  continue: keyFor("Continue"),
};

// Representative browser matrix across scripts and directions. The static
// release gate validates every advertised locale; these are rendered live.
export const REPRESENTATIVE_LOCALES = [
  "pt-BR", "fr-FR", "de", "es", "ja", "zh", "ko", "ar", "fa", "ur",
  "ru", "uk", "hi", "ta", "my", "th", "am", "sw", "so",
];
