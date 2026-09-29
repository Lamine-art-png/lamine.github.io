import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import {
  REPRESENTATIVE_LOCALES, SIGNUP_KEYS, directionByLocale, englishLeaks, languageSelect, loadCatalog, manifest, source,
} from "./support/localeLeakScan.mjs";

// Real browser, fresh anonymous context, no localization endpoint mocking:
// the page renders only what the production build ships.
const APP_URL = process.env.AGROAI_APP_URL || "http://127.0.0.1:4173/?mode=register";
const root = path.resolve(process.cwd(), "..");
const productionEnabled = new Set(manifest.enabledUiLocales || []);
const locales = REPRESENTATIVE_LOCALES.filter((locale) => productionEnabled.has(locale));
if (!locales.includes("pt-BR")) {
  throw new Error("Brazilian Portuguese must remain a production-complete pre-auth locale");
}

for (const locale of locales) {
  test(`fresh anonymous signup switches atomically to ${locale}`, async ({ browser }) => {
    const context = await browser.newContext({ locale: "en-US" });
    const page = await context.newPage();
    const catalogRequests = [];
    page.on("request", (request) => { if (request.url().includes("/v1/i18n/catalog")) catalogRequests.push(request.url()); });

    await page.goto(APP_URL);
    const language = languageSelect(page);
    await expect(language).toBeVisible();

    const catalog = loadCatalog(locale);
    for (const [name, key] of Object.entries(SIGNUP_KEYS)) {
      expect(catalog[key], `${locale} must translate ${name}`).toBeTruthy();
      expect(catalog[key], `${locale} must not leave ${name} in English`).not.toBe(source[key]);
    }

    await language.selectOption(locale);
    await expect(language).toHaveValue(locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.locator("html")).toHaveAttribute("dir", directionByLocale.get(locale) || "ltr");

    for (const name of ["createAccount", "title", "fullName", "organizationType", "continue"]) {
      await expect(page.getByText(catalog[SIGNUP_KEYS[name]], { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText("Create your AGRO-AI account", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Full name", { exact: true })).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("[object Object]");
    await expect(page.locator("body")).not.toContainText("AGROAI_KEEP");
    expect(await englishLeaks(page, catalog), `${locale} signup renders English source strings`).toEqual([]);

    const terms = page.locator('a[href*="/terms-of-service"]').first();
    if (await terms.count()) await expect(terms).toHaveAttribute("href", new RegExp(`lang=${locale}`));

    // Continue with an empty form: validation copy must be localized too.
    await page.getByText(catalog[SIGNUP_KEYS.continue], { exact: true }).first().click().catch(() => undefined);
    await page.waitForTimeout(300);
    expect(await englishLeaks(page, catalog), `${locale} validation/next step renders English`).toEqual([]);

    await page.reload();
    await expect(languageSelect(page)).toHaveValue(locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.getByText(catalog[SIGNUP_KEYS.title], { exact: true }).first()).toBeVisible();

    // Deterministic release: switching never asked a translation provider.
    expect(catalogRequests, `${locale} called the runtime catalog endpoint`).toEqual([]);
    await context.close();
  });
}

test("verification link opens in its language on a clean device", async ({ browser }) => {
  const locale = locales.find((code) => code !== "pt-BR") || "pt-BR";
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  const base = new URL(APP_URL);
  await page.goto(`${base.origin}/verify-email?token=invalid-fixture-token&lang=${encodeURIComponent(locale)}`);
  await expect(page.locator("html")).toHaveAttribute("lang", locale);
  await page.waitForTimeout(1500);
  expect(await englishLeaks(page, loadCatalog(locale)), `${locale} verification page renders English`).toEqual([]);
  await context.close();
});

test("manifest never advertises a locale without a deterministic catalog", async () => {
  const advertised = manifest.enabledUiLocales.filter((code) => !["auto", "en"].includes(code));
  for (const locale of advertised) {
    expect(fs.existsSync(path.join(root, "shared/localization/catalogs", `${locale}.json`)), locale).toBeTruthy();
  }
});
