import { expect, test } from "@playwright/test";
import {
  REPRESENTATIVE_LOCALES, SIGNUP_KEYS, directionByLocale, englishLeaks, languageSelect, loadCatalog, manifest,
} from "./support/localeLeakScan.mjs";

// Black-box production proof: a real Chromium against the deployed site with a
// fresh context (no cookies, storage, auth or cached catalogs) and no mocking.
const APP_URL = process.env.AGROAI_PRODUCTION_APP || "https://app.agroai-pilot.com/?mode=register";
const LEGAL_ORIGIN = process.env.AGROAI_PRODUCTION_LEGAL || "https://agroai-pilot.com";
const advertised = (manifest.enabledUiLocales || []).filter((code) => code !== "auto");
const locales = REPRESENTATIVE_LOCALES.filter((code) => advertised.includes(code));
const onlyLocales = (process.env.AGROAI_PROOF_LOCALES || "").split(",").map((v) => v.trim()).filter(Boolean);
const proofLocales = onlyLocales.length ? onlyLocales : locales;

test("production selector advertises exactly the release-eligible locale set", async ({ browser }) => {
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
  const select = languageSelect(page);
  await expect(select).toBeVisible({ timeout: 30_000 });
  const offered = await select.locator("option").evaluateAll((options) => options.map((option) => option.value));
  expect([...offered].sort()).toEqual([...manifest.enabledUiLocales].sort());
  await context.close();
});

for (const locale of proofLocales) {
  test(`production signup is genuinely ${locale}`, async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await browser.newContext({ locale: "en-US" });
    const page = await context.newPage();
    const catalog = loadCatalog(locale);
    await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
    const select = languageSelect(page);
    await expect(select).toBeVisible({ timeout: 30_000 });
    await select.selectOption(locale);
    await expect(select).toHaveValue(locale, { timeout: 20_000 });
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.locator("html")).toHaveAttribute("dir", directionByLocale.get(locale) || "ltr");
    for (const key of Object.values(SIGNUP_KEYS)) {
      await expect(page.getByText(catalog[key], { exact: true }).first()).toBeVisible({ timeout: 15_000 });
    }
    await expect(page.locator("body")).not.toContainText("[object Object]");
    await expect(page.locator("body")).not.toContainText("AGROAI_KEEP");
    expect(await englishLeaks(page, catalog), `${locale} production signup renders English`).toEqual([]);
    await expect(page.locator('a[href*="/terms-of-service"]').first()).toHaveAttribute("href", new RegExp(`lang=${locale}`));
    await expect(page.locator('a[href*="/privacy-policy"]').first()).toHaveAttribute("href", new RegExp(`lang=${locale}`));

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(languageSelect(page)).toHaveValue(locale, { timeout: 20_000 });
    await expect(page.getByText(catalog[SIGNUP_KEYS.title], { exact: true }).first()).toBeVisible({ timeout: 15_000 });
    await context.close();
  });

  test(`production legal pages are ${locale} presentations of the accepted version`, async ({ request }) => {
    for (const slug of ["terms-of-service", "privacy-policy"]) {
      const response = await request.get(`${LEGAL_ORIGIN}/${slug}?lang=${encodeURIComponent(locale)}`);
      expect(response.ok()).toBeTruthy();
      expect(response.headers()["content-language"]).toBe(locale);
      expect(response.headers()["x-agroai-legal-localization"]).toBe("static-versioned-snapshot");
      const html = await response.text();
      expect(html).toContain(`name="agroai-legal-locale" content="${locale}"`);
      expect(html).toMatch(/name="agroai-legal-version" content="\d{4}-\d{2}-\d{2}"/);
      expect(html).not.toContain("[object Object]");
      expect(html).not.toMatch(/AGROAI_KEEP|&lt;&lt;&lt;/);
    }
  });
}

test("production verification link restores its language on a clean device", async ({ browser }) => {
  const locale = proofLocales[0];
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  const origin = new URL(APP_URL).origin;
  await page.goto(`${origin}/verify-email?token=invalid-fixture-token&lang=${encodeURIComponent(locale)}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("html")).toHaveAttribute("lang", locale, { timeout: 20_000 });
  await page.waitForTimeout(2500);
  expect(await englishLeaks(page, loadCatalog(locale)), `${locale} verification page renders English`).toEqual([]);
  await context.close();
});
