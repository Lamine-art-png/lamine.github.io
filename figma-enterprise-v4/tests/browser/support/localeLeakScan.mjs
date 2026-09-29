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

// English prose that never entered the inventory (e.g. a sentence split
// around a link) cannot be matched against source strings. Two or more
// distinct English function words in one rendered text node is a strong,
// language-independent signal of untranslated English on pre-auth pages.
const ENGLISH_FUNCTION_WORDS = ["the", "and", "of", "your", "with", "for", "this", "that", "will", "are", "is", "to", "you", "our", "before", "after"];
export async function untranslatedEnglishProse(page) {
  const texts = await page.evaluate(() => {
    const out = [];
    const skip = (el) => el.closest("[data-language-selector], [data-i18n-ignore], script, style, noscript, code, pre");
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || skip(parent)) continue;
      const style = getComputedStyle(parent);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const text = (node.nodeValue || "").trim().replace(/\s+/g, " ");
      if (text) out.push(text);
    }
    for (const el of document.querySelectorAll("[placeholder],[aria-label],[title]")) {
      if (skip(el)) continue;
      for (const attr of ["placeholder", "aria-label", "title"]) {
        const value = (el.getAttribute(attr) || "").trim();
        if (value) out.push(value);
      }
    }
    return out;
  });
  return texts.filter((text) => {
    const words = new Set((text.toLowerCase().match(/[a-z]+/g) || []));
    return ENGLISH_FUNCTION_WORDS.filter((word) => words.has(word)).length >= 2;
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

// Walk every signup step (legal acceptance included) up to the final submit
// button without submitting,
// scanning each step. Values are synthetic; nothing is sent to the API.
export async function walkSignupSteps(page, catalog, onStep) {
  const continueLabel = catalog[SIGNUP_KEYS.continue];
  for (let step = 1; step <= 3; step += 1) {
    await onStep(step);
    if (await page.locator('form button[type="submit"]').first().isVisible().catch(() => false)) {
      return page.locator('input[type="checkbox"]').first().isVisible().catch(() => false)
        .then(async (legalVisible) => legalVisible || (await page.locator("form").innerText()).length > 0);
    }
    for (const box of await page.locator('form input[type="checkbox"]:visible').all()) {
      if (!(await box.isChecked())) await box.check();
    }
    for (const input of await page.locator("form input:visible, form textarea:visible").all()) {
      const type = (await input.getAttribute("type")) || "text";
      if (["checkbox", "radio", "hidden", "submit"].includes(type)) continue;
      if (await input.inputValue().catch(() => "")) continue;
      const placeholder = (await input.getAttribute("placeholder")) || "";
      const isTextarea = await input.evaluate((el) => el.tagName === "TEXTAREA");
      const value = isTextarea ? "Locale proof: irrigation scheduling and evidence review for a multi-farm operation."
        : type === "email" ? "locale-proof@example.com"
        : type === "password" ? "Harvest-Signal-Window-2026"
        : type === "url" || /https?:/.test(placeholder) ? "https://example.com"
        : type === "tel" ? "+55 11 99999-0000"
        : "Locale proof 12";
      await input.fill(value);
    }
    for (const select of await page.locator("form select:visible").all()) {
      if (await select.getAttribute("data-language-selector") !== null) continue;
      const values = await select.locator("option").evaluateAll((options) => options.map((o) => o.value).filter(Boolean));
      if (values.length) await select.selectOption(values[0]);
    }
    await page.getByRole("button", { name: continueLabel, exact: true }).first().click();
    await page.waitForTimeout(300);
  }
  return page.locator('form button[type="submit"]').first().isVisible();
}
