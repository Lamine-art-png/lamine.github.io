import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const APP_URL = process.env.AGROAI_PRODUCTION_APP || "https://app.agroai-pilot.com/?mode=register";
const repoRoot = path.resolve(process.cwd(), "..");
const sourceEnvelope = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared/localization/source.json"), "utf8"));
const ptEnvelope = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared/localization/catalogs/pt-BR.json"), "utf8"));

function expectedForEnglish(sourceText) {
  const entry = Object.entries(sourceEnvelope.catalog).find(([, value]) => value === sourceText);
  if (!entry) throw new Error(`Canonical source does not contain: ${sourceText}`);
  const [key] = entry;
  const translated = ptEnvelope.catalog[key];
  if (!translated || translated === sourceText) throw new Error(`pt-BR release catalog did not translate: ${sourceText}`);
  return translated;
}

test("production anonymous signup actually switches atomically to Brazilian Portuguese", async ({ browser }) => {
  test.setTimeout(90_000);
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  await page.goto(APP_URL, { waitUntil: "domcontentloaded" });

  const selector = page.locator('select').filter({ has: page.locator('option[value="pt-BR"]') }).first();
  await expect(selector).toBeVisible({ timeout: 20_000 });
  await selector.selectOption("pt-BR");
  await expect(selector).toHaveValue("pt-BR");
  await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");

  for (const sourceText of [
    "Create account",
    "Create your AGRO-AI account",
    "Full name",
    "Password",
    "Legal organization name",
    "Organization type",
    "Continue",
  ]) {
    const translated = expectedForEnglish(sourceText);
    await expect(page.getByText(translated, { exact: true }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(sourceText, { exact: true })).toHaveCount(0);
  }

  const terms = page.locator('a[href*="/terms-of-service"]').first();
  const privacy = page.locator('a[href*="/privacy-policy"]').first();
  await expect(terms).toHaveAttribute("href", /lang=pt-BR/);
  await expect(privacy).toHaveAttribute("href", /lang=pt-BR/);

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(selector).toHaveValue("pt-BR");
  await expect(page.getByText(expectedForEnglish("Create account"), { exact: true }).first()).toBeVisible();

  const errors = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  expect((await page.locator("body").innerText()).toLowerCase()).not.toContain("[object object]");
  await context.close();
});

test("production localized legal pages resolve as pt-BR static snapshots", async ({ request }) => {
  for (const slug of ["terms-of-service", "privacy-policy"]) {
    const response = await request.get(`https://agroai-pilot.com/${slug}?lang=pt-BR`);
    expect(response.ok()).toBeTruthy();
    expect(response.headers()["content-language"]).toBe("pt-BR");
    expect(response.headers()["x-agroai-legal-localization"]).toBe("static-versioned-snapshot");
    const html = await response.text();
    expect(html).toContain('name="agroai-legal-locale" content="pt-BR"');
    expect(html).not.toContain("[object Object]");
  }
});
