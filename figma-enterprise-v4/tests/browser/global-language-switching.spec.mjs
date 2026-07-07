import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const APP_URL = "http://127.0.0.1:4173/settings";
const API_ORIGIN = "https://api.agroai-pilot.com";
const repoRoot = path.resolve(process.cwd(), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared", "supported-locales.json"), "utf8"));
const REQUEST_CHUNK_SIZE = 36;

function qaToken() {
  const body = Buffer.from(JSON.stringify({ sub: "qa", exp: 4102444800 })).toString("base64url");
  return `qa.${body}.sig`;
}

async function prepare(page) {
  const state = { catalogs: [], patches: [] };
  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
  }, qaToken());

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const reply = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

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
    if (req.method() === "GET" && url.pathname === "/v1/settings/preferences") {
      return reply({ preferences: { locale: "en", notifications: { report_delivery: true, operational_alerts: true, support_updates: true }, ui: { assistant_speed: "balanced" } } });
    }
    if (req.method() === "POST" && url.pathname === "/v1/i18n/catalog") {
      const payload = req.postDataJSON();
      state.catalogs.push({ locale: payload.locale, keyCount: Object.keys(payload.source || {}).length });
      const catalog = Object.fromEntries(Object.entries(payload.source).map(([key, value]) => [key, `⟦${payload.locale}⟧ ${value}`]));
      return reply({ status: "ok", locale: payload.locale, catalog, source: "browser-test" });
    }
    if (req.method() === "PATCH" && url.pathname === "/v1/settings/preferences") {
      state.patches.push(req.postDataJSON());
      return reply({ preferences: req.postDataJSON(), message: "saved" });
    }
    return reply({});
  });
  return state;
}

function languageSelector(page) {
  return page.locator("select").filter({ has: page.locator('option[value="fr-FR"]') }).first();
}

test("every visible non-English UI locale hydrates core first and full literals progressively", async ({ browser }) => {
  test.setTimeout(180_000);
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  const state = await prepare(page);
  await page.goto(APP_URL);

  const selector = languageSelector(page);
  await expect(selector).toHaveValue("en");
  const locales = manifest.enabledUiLocales.filter((code) => code !== "auto" && code !== "en");
  expect(locales.length).toBeGreaterThanOrEqual(50);

  for (const locale of locales) {
    await selector.selectOption(locale);
    await expect(selector).toHaveValue(locale);
    await expect(selector).toBeEnabled();
    const expectedSettings = locale === "fr-FR" ? "Paramètres" : `⟦${locale}⟧ Settings`;
    await expect(page.getByText(expectedSettings, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(`⟦${locale}⟧ Timezone`, { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("combobox", { name: `⟦${locale}⟧ Assistant speed` })).toBeVisible();
    const expectedDir = ["ar", "fa", "ur"].includes(locale.split("-")[0]) ? "rtl" : "ltr";
    await expect(page.locator("html")).toHaveAttribute("dir", expectedDir);
  }

  expect(new Set(state.catalogs.map((item) => item.locale))).toEqual(new Set(locales));
  for (const locale of locales) {
    const requests = state.catalogs.filter((item) => item.locale === locale);
    expect(requests.length).toBeGreaterThanOrEqual(4);
    expect(requests.every((item) => item.keyCount > 0 && item.keyCount <= REQUEST_CHUNK_SIZE)).toBeTruthy();
  }
  await context.close();
});

test("non-French locale visibly translates from core while full literal chunks are still pending", async ({ browser }) => {
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
  }, qaToken());

  let releaseFull;
  const fullGate = new Promise((resolve) => { releaseFull = resolve; });
  const requestScopes = [];
  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const reply = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (req.method() === "GET" && url.pathname === "/v1/auth/me") return reply({ user: { id: "qa", name: "QA", email: "qa@example.com" }, current_organization: { id: "org", name: "QA Org", role: "owner" }, organizations: [{ id: "org", name: "QA Org", role: "owner" }], entitlements: {} });
    if (req.method() === "GET" && url.pathname === "/v1/orgs") return reply({ organizations: [{ id: "org", name: "QA Org", role: "owner" }] });
    if (req.method() === "GET" && url.pathname === "/v1/workspaces") return reply({ workspaces: [{ id: "ws", name: "QA Workspace", status: "active" }] });
    if (req.method() === "GET" && url.pathname === "/v1/settings/preferences") return reply({ preferences: { locale: "en", notifications: {}, ui: {} } });
    if (req.method() === "POST" && url.pathname === "/v1/i18n/catalog") {
      const payload = req.postDataJSON();
      const keys = Object.keys(payload.source || {});
      const isFullLiteralChunk = keys.some((key) => key.startsWith("literal."));
      requestScopes.push(isFullLiteralChunk ? "full" : "core");
      if (isFullLiteralChunk) await fullGate;
      const catalog = Object.fromEntries(Object.entries(payload.source).map(([key, value]) => [key, `⟦${payload.locale}⟧ ${value}`]));
      return reply({ status: "ok", locale: payload.locale, catalog });
    }
    if (req.method() === "PATCH" && url.pathname === "/v1/settings/preferences") return reply({ status: "saved" });
    return reply({});
  });

  await page.goto(APP_URL);
  const selector = languageSelector(page);
  await selector.selectOption("de");
  await expect(selector).toHaveValue("de");
  await expect(selector).toBeEnabled();
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
  await expect(page.getByText("⟦de⟧ Settings", { exact: true }).first()).toBeVisible();
  expect(requestScopes.includes("core")).toBeTruthy();

  releaseFull();
  await expect(page.getByText("⟦de⟧ Timezone", { exact: true }).first()).toBeVisible();
  expect(requestScopes.includes("full")).toBeTruthy();
  await expect(selector).toHaveValue("de");
  await expect(selector).toBeEnabled();
  await context.close();
});

test("catalog failure never traps the language selector", async ({ page }) => {
  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
  }, qaToken());
  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const reply = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (req.method() === "GET" && url.pathname === "/v1/auth/me") return reply({ user: { id: "qa", name: "QA", email: "qa@example.com" }, current_organization: { id: "org", name: "QA Org", role: "owner" }, organizations: [{ id: "org", name: "QA Org", role: "owner" }], entitlements: {} });
    if (req.method() === "GET" && url.pathname === "/v1/orgs") return reply({ organizations: [{ id: "org", name: "QA Org", role: "owner" }] });
    if (req.method() === "GET" && url.pathname === "/v1/workspaces") return reply({ workspaces: [{ id: "ws", name: "QA Workspace", status: "active" }] });
    if (req.method() === "GET" && url.pathname === "/v1/settings/preferences") return reply({ preferences: { locale: "en", notifications: {}, ui: {} } });
    if (req.method() === "POST" && url.pathname === "/v1/i18n/catalog") return reply({ detail: { code: "ui_catalog_generation_unavailable" } }, 503);
    if (req.method() === "PATCH" && url.pathname === "/v1/settings/preferences") return reply({ status: "saved" });
    return reply({});
  });

  await page.goto(APP_URL);
  const selector = languageSelector(page);
  await selector.selectOption("de");
  await expect(selector).toHaveValue("de");
  await expect(selector).toBeEnabled();
  await selector.selectOption("en");
  await expect(selector).toHaveValue("en");
  await expect(selector).toBeEnabled();
});
