import { expect, test } from "@playwright/test";

const APP_URL = "http://127.0.0.1:4173/settings";
const API_ORIGIN = "https://api.agroai-pilot.com";
const REQUEST_CHUNK_SIZE = 48;

function qaToken() {
  const body = Buffer.from(JSON.stringify({ sub: "qa", exp: 4102444800 })).toString("base64url");
  return `qa.${body}.sig`;
}

async function prepare(page, storedLocale) {
  const state = { patches: 0, catalogs: [] };
  await page.addInitScript(({ token, locale }) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", locale);
  }, { token: qaToken(), locale: storedLocale });

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const reply = (body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (req.method() === "GET" && url.pathname === "/v1/auth/me") {
      return reply({
        user: { id: "qa", name: "QA", email: "qa@example.com" },
        current_organization: { id: "org", name: "QA Org", role: "owner" },
        organizations: [{ id: "org", name: "QA Org", role: "owner" }],
        entitlements: {},
      });
    }
    if (req.method() === "GET" && url.pathname === "/v1/orgs") return reply({ organizations: [{ id: "org", name: "QA Org", role: "owner" }] });
    if (req.method() === "GET" && url.pathname === "/v1/workspaces") return reply({ workspaces: [{ id: "ws", name: "QA Workspace", status: "active" }] });
    if (req.method() === "POST" && url.pathname === "/v1/i18n/catalog") {
      const payload = req.postDataJSON();
      state.catalogs.push({ locale: payload.locale, keyCount: Object.keys(payload.source || {}).length });
      const catalog = { ...payload.source };
      if (Object.prototype.hasOwnProperty.call(catalog, "language")) {
        catalog.language = payload.locale === "de"
          ? "Sprache"
          : payload.locale === "ar"
            ? "اللغة"
            : payload.locale === "fr-FR"
              ? "Langue"
              : catalog.language;
      }
      if (payload.locale === "sw" && Object.prototype.hasOwnProperty.call(catalog, "intelligence.reportEmailed")) {
        catalog["intelligence.reportEmailed"] = "Imetumwa kwa " + "{" + "{recipient}" + "}";
      }
      return reply({ status: "ok", locale: payload.locale, catalog, source: "browser-test" });
    }
    if (req.method() === "PATCH" && url.pathname === "/v1/settings/preferences") {
      state.patches += 1;
      return reply({ status: "saved" });
    }
    return reply({});
  });
  return state;
}

function languageSelector(page) {
  return page.locator("select").filter({ has: page.locator('option[value="fr-FR"]') }).first();
}

const cases = [
  ["legacy fr", "fr", "fr-FR", "fr-FR", "fr-FR", "Langue", true],
  ["regional fr-CA", "fr-CA", "fr-FR", "fr-FR", "fr-FR", "Langue", true],
  ["global de", "de", "de", "de", "de", "Sprache", true],
  ["global ar", "ar", "ar", "ar", "ar", "اللغة", true],
  ["unknown locale", "nonsense-value", "auto", "en", "auto", "Language", false],
];

for (const [name, stored, selected, effective, rewritten, translatedLabel, expectsCatalogActivity] of cases) {
  test(`${name} canonicalization`, async ({ browser }) => {
    const context = await browser.newContext({ locale: "en-US" });
    const page = await context.newPage();
    const state = await prepare(page, stored);
    await page.goto(APP_URL);

    await expect(languageSelector(page)).toHaveValue(selected);
    await expect(page.locator("html")).toHaveAttribute("lang", effective);
    await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_locale_v1"))).toBe(rewritten);
    await expect(page.getByText(translatedLabel, { exact: true }).first()).toBeVisible();
    if (expectsCatalogActivity) {
      await expect.poll(() => state.catalogs.length).toBeGreaterThanOrEqual(1);
      expect(state.catalogs.every((item) => item.keyCount > 0 && item.keyCount <= REQUEST_CHUNK_SIZE)).toBeTruthy();
    } else {
      expect(state.catalogs).toHaveLength(0);
    }
    expect(state.patches).toBe(0);
    await context.close();
  });
}

test("malformed dynamic placeholder catalog is rejected and not cached", async ({ browser }) => {
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  const state = await prepare(page, "sw");
  await page.goto(APP_URL);

  await expect(languageSelector(page)).toHaveValue("sw");
  await expect(page.locator("html")).toHaveAttribute("lang", "sw");
  await expect.poll(() => state.catalogs.length).toBeGreaterThanOrEqual(1);
  expect(state.catalogs.every((item) => item.keyCount > 0 && item.keyCount <= REQUEST_CHUNK_SIZE)).toBeTruthy();
  await expect(page.getByText("Language", { exact: true }).first()).toBeVisible();
  const cached = await page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith("agroai_ui_catalog_v5:sw:")));
  expect(cached).toBe(false);
  await context.close();
});
