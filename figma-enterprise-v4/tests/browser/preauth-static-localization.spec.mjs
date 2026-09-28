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

function selector(page) {
  return page.locator("select").filter({ has: page.locator('option[value="en"]') }).first();
}

for (const locale of ["pt-BR", "ja", "ar", "de", "my", "fr-FR"]) {
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
    await expect(page.locator("html")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");

    await expect(page.getByText(catalog[keys.createAccount], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.title], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.fullName], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.organizationType], { exact: true }).first()).toBeVisible();
    await expect(page.getByText(catalog[keys.continue], { exact: true }).first()).toBeVisible();

    await expect(page.getByText("Create your AGRO-AI account", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Full name", { exact: true })).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("[object Object]");

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
