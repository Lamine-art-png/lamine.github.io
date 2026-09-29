import { expect, test } from "@playwright/test";
import { englishLeaks, loadCatalog, manifest, untranslatedEnglishProse } from "./support/localeLeakScan.mjs";

// Authenticated portal rendered from the shipped deterministic catalogs.
// Only identity and business data are stubbed (a signed-in owner with empty
// workspaces); the localization endpoint is NOT mocked and must never be
// called — any request to it fails the test.
const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";
const API_ORIGIN = "https://api.agroai-pilot.com";
const ROUTES = ["/", "/field-intelligence", "/field-queue", "/tasks", "/operations", "/evidence", "/assurance", "/reports",
  "/integrations", "/intelligence", "/market-intelligence", "/readiness", "/sources", "/settings", "/profile", "/billing", "/security", "/support"];
const LOCALES = ["pt-BR", "ja", "ar", "de", "hi", "sw"].filter((code) => (manifest.enabledUiLocales || []).includes(code));

function futureJwt() {
  const payload = Buffer.from(JSON.stringify({ sub: "qa-user", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url");
  return `qa.${payload}.signature`;
}

async function signedInOwner(page, locale) {
  const catalogCalls = [];
  await page.addInitScript(({ token, locale: selected }) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", selected);
    localStorage.setItem("agroai_product_tour_product_tour_v2_qa-user", "done");
  }, { token: futureJwt(), locale });
  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/v1/i18n/catalog") {
      catalogCalls.push(path);
      return route.abort();
    }
    if (path === "/v1/i18n/events") return json({ status: "accepted" }, 202);
    const org = { id: "org-qa", name: "QA Farm", role: "owner", plan: "enterprise", subscription_status: "active" };
    if (path === "/v1/auth/me") {
      return json({ user: { id: "qa-user", name: "QA Operator", email: "qa@example.com", email_verified: true }, current_organization: org, organizations: [org], entitlements: { capabilities: {} } });
    }
    if (path === "/v1/orgs") return json({ organizations: [org] });
    if (path === "/v1/workspaces") return json({ workspaces: [{ id: "ws-qa", name: "QA Workspace", status: "active" }] });
    if (path === "/v1/settings/preferences") return json({ preferences: { locale } });
    // Empty business data for every other read; accept writes.
    if (request.method() === "GET") return json({ items: [], data: [], results: [], status: "ok" });
    return json({ status: "ok" });
  });
  return catalogCalls;
}

for (const locale of LOCALES) {
  test(`authenticated portal routes render ${locale} from shipped catalogs`, async ({ browser }) => {
    test.setTimeout(180_000);
    const context = await browser.newContext({ locale: "en-US", viewport: { width: 1400, height: 900 } });
    const page = await context.newPage();
    const catalogCalls = await signedInOwner(page, locale);
    const catalog = loadCatalog(locale);
    const findings = [];
    for (const route of ROUTES) {
      await page.goto(`${APP}${route}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1200);
      await expect(page.locator("html")).toHaveAttribute("lang", locale);
      for (const text of await englishLeaks(page, catalog)) findings.push(`${route} :: ${text}`);
      for (const text of await untranslatedEnglishProse(page)) findings.push(`${route} :: (uninventoried) ${text}`);
    }
    expect(catalogCalls, `${locale} requested runtime catalogs`).toEqual([]);
    expect(findings, `${locale} authenticated English leakage`).toEqual([]);
    await context.close();
  });
}
