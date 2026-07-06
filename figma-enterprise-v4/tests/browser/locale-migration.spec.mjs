import { expect, test } from "@playwright/test";

const APP_URL = "http://127.0.0.1:4173/settings";
const API_ORIGIN = "https://api.agroai-pilot.com";

function qaToken() {
  const body = Buffer.from(JSON.stringify({ sub: "qa", exp: 4102444800 })).toString("base64url");
  return `qa.${body}.sig`;
}

async function prepare(page, storedLocale) {
  const state = { patches: 0, catalogs: 0 };
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
      state.catalogs += 1;
      const payload = req.postDataJSON();
      const translatedLanguage = payload.locale === "de" ? "Sprache" : payload.locale === "ar" ? "اللغة" : payload.source.language;
      return reply({ status: "ok", locale: payload.locale, catalog: { ...payload.source, language: translatedLanguage }, source: "browser-test" });
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
  ["legacy fr", "fr", "fr-FR", "fr-FR", "fr-FR", "Langue", 0],
  ["regional fr-CA", "fr-CA", "fr-FR", "fr-FR", "fr-FR", "Langue", 0],
  ["global de", "de", "de", "de", "de", "Sprache", 1],
  ["global ar", "ar", "ar", "ar", "ar", "اللغة", 1],
  ["unknown locale", "nonsense-value", "auto", "en", "auto", "Language", 0],
];

for (const [name, stored, selected, effective, rewritten, translatedLabel, expectedCatalogCalls] of cases) {
  test(`${name} canonicalization`, async ({ browser }) => {
    const context = await browser.newContext({ locale: "en-US" });
    const page = await context.newPage();
    const state = await prepare(page, stored);
    await page.goto(APP_URL);

    await expect(languageSelector(page)).toHaveValue(selected);
    await expect(page.locator("html")).toHaveAttribute("lang", effective);
    await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_locale_v1"))).toBe(rewritten);
    await expect(page.getByText(translatedLabel, { exact: true }).first()).toBeVisible();
    await expect.poll(() => state.catalogs).toBe(expectedCatalogCalls);
    expect(state.patches).toBe(0);
    await context.close();
  });
}
