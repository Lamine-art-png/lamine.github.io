import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const APP_URL = "http://127.0.0.1:4173/?mode=register";
const root = path.resolve(process.cwd(), "..");
const source = JSON.parse(fs.readFileSync(path.join(root, "shared/localization/source.json"), "utf8")).catalog;
const manifest = JSON.parse(fs.readFileSync(path.join(root, "shared/supported-locales.json"), "utf8"));

function keyFor(value) {
  const entries = Object.entries(source).filter(([, text]) => text === value);
  if (!entries.length) throw new Error(`Missing canonical source literal: ${value}`);
  return entries[0][0];
}

const keys = {
  createAccount: keyFor("Create account"),
  title: keyFor("Create your AGRO-AI account"),
  fullName: keyFor("Full name"),
  organizationType: keyFor("Organization type"),
  continue: keyFor("Continue"),
};

function loadCatalog(locale) {
  if (locale === "en") return source;
  return JSON.parse(
    fs.readFileSync(path.join(root, "shared/localization/catalogs", `${locale}.json`), "utf8"),
  ).catalog;
}

const directionByLocale = new Map((manifest.locales || []).map((row) => [row.code, row.direction || "ltr"]));

// English source values a customer would read as prose (not code/brand tokens).
function translatableProse(value) {
  return (value.match(/[A-Za-z]{3,}/g) || []).length >= 2
    && !/^\s*(?:curl\s|-H\s|(?:GET|POST|PUT|PATCH|DELETE)\s+\/|\{\s*")|\$[A-Z][A-Z0-9_]{2,}/.test(value);
}

// Rendered strings that are exactly an English source string whose deployed
// translation differs = English leaking into a localized surface.
async function englishLeaks(page, catalog) {
  const englishToKeys = new Map();
  for (const [key, value] of Object.entries(source)) {
    const normalized = value.trim().replace(/\s+/g, " ");
    if (!translatableProse(normalized)) continue;
    if (!englishToKeys.has(normalized)) englishToKeys.set(normalized, []);
    englishToKeys.get(normalized).push(key);
  }
  const rendered = await page.evaluate(() => {
    const out = new Set();
    const skip = (el) => el.closest('select[aria-label="Language"], [data-i18n-ignore], script, style, noscript');
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

function selector(page) {
  return page.locator("select").filter({ has: page.locator('option[value="en"]') }).first();
}

const productionEnabled = new Set(manifest.enabledUiLocales || []);
const representativeLocales = ["pt-BR", "fr-FR", "de", "es", "ja", "zh", "ko", "ar", "fa", "ur", "ru", "uk", "hi", "ta", "my", "am", "sw", "so", "th"]
  .filter((locale) => productionEnabled.has(locale));
if (!representativeLocales.includes("pt-BR")) {
  throw new Error("Brazilian Portuguese must remain a production-complete pre-auth locale");
}

for (const locale of representativeLocales) {
  test(`fresh anonymous signup switches atomically to ${locale}`, async ({ browser }) => {
    const context = await browser.newContext({ locale: "en-US" });
    const page = await context.newPage();

    await page.goto(APP_URL);
    const language = selector(page);
    await expect(language).toBeVisible();

    const catalog = loadCatalog(locale);
    for (const [name, key] of Object.entries(keys)) {
      expect(catalog[key], `${locale} must translate ${name}`).toBeTruthy();
      expect(catalog[key], `${locale} must not leave ${name} in English`).not.toBe(source[key]);
    }

    await language.selectOption(locale);
    await expect(language).toHaveValue(locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.locator("html")).toHaveAttribute("dir", directionByLocale.get(locale) || "ltr");

    await expect(page.getByText(catalog[keys.createAccount], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.title], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.fullName], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.organizationType], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.continue], { exact: true }).first()).toBeVisible();

    await expect(page.getByText("Create your AGRO-AI account", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Full name", { exact: true })).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("[object Object]");
    await expect(page.locator("body")).not.toContainText("AGROAI_KEEP");
    expect(await englishLeaks(page, catalog), `${locale} renders English source strings`).toEqual([]);

    // Continue to the organization step and check it too.
    await page.getByText(catalog[keys.continue], { exact: true }).first().click().catch(() => undefined);
    await page.waitForTimeout(300);
    expect(await englishLeaks(page, catalog), `${locale} organization step renders English`).toEqual([]);

    await page.reload();
    await expect(selector(page)).toHaveValue(locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.getByText(catalog[keys.title], { exact: true }).first()).toBeVisible();

    await context.close();
  });
}

test("manifest never advertises a locale without a deterministic catalog", async () => {
  const advertised = manifest.enabledUiLocales.filter((code) => !["auto", "en"].includes(code));
  for (const locale of advertised) {
    expect(fs.existsSync(path.join(root, "shared/localization/catalogs", `${locale}.json`)), locale).toBeTruthy();
  }
});
