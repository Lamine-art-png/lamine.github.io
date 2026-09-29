import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const APP_URL = "http://127.0.0.1:4173/settings";
const API_ORIGIN = "https://api.agroai-pilot.com";
const repoRoot = path.resolve(process.cwd(), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared", "supported-locales.json"), "utf8"));

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

const sourceCatalog = JSON.parse(fs.readFileSync(path.join(repoRoot, "shared", "localization", "source.json"), "utf8")).catalog;
function shipped(locale) {
  return JSON.parse(fs.readFileSync(path.join(repoRoot, "shared", "localization", "catalogs", `${locale}.json`), "utf8")).catalog;
}
function sourceKey(value) {
  const entry = Object.entries(sourceCatalog).find(([, text]) => text === value);
  if (!entry) throw new Error(`missing source literal ${value}`);
  return entry[0];
}

// Deterministic release contract: every advertised locale renders the value
// shipped in its release catalog and never asks a translation provider.
test("every advertised locale renders its shipped catalog without runtime generation", async ({ browser }) => {
  test.setTimeout(360_000);
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  const state = await prepare(page);
  await page.goto(APP_URL);

  const selector = languageSelector(page);
  await expect(selector).toHaveValue("en");
  const locales = manifest.enabledUiLocales.filter((code) => code !== "auto" && code !== "en");
  expect(locales.length).toBeGreaterThanOrEqual(50);
  const timezoneKey = sourceKey("Timezone");
  const directions = new Map(manifest.locales.map((row) => [row.code, row.direction || "ltr"]));

  for (const locale of locales) {
    await selector.selectOption(locale);
    await expect(selector).toHaveValue(locale);
    await expect(selector).toBeEnabled();
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.locator("html")).toHaveAttribute("dir", directions.get(locale) || "ltr");
    await expect(page.getByText(shipped(locale)[timezoneKey], { exact: true }).first()).toBeVisible();
  }

  expect(state.catalogs, "advertised locales must not request runtime catalogs").toEqual([]);
  await context.close();
});

test("language switch is atomic and independent of a stalled translation provider", async ({ browser }) => {
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
  }, qaToken());
  const providerCalls = [];
  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const reply = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (req.method() === "GET" && url.pathname === "/v1/auth/me") return reply({ user: { id: "qa", name: "QA", email: "qa@example.com" }, current_organization: { id: "org", name: "QA Org", role: "owner" }, organizations: [{ id: "org", name: "QA Org", role: "owner" }], entitlements: {} });
    if (req.method() === "GET" && url.pathname === "/v1/orgs") return reply({ organizations: [{ id: "org", name: "QA Org", role: "owner" }] });
    if (req.method() === "GET" && url.pathname === "/v1/workspaces") return reply({ workspaces: [{ id: "ws", name: "QA Workspace", status: "active" }] });
    if (req.method() === "GET" && url.pathname === "/v1/settings/preferences") return reply({ preferences: { locale: "en", notifications: {}, ui: {} } });
    if (req.method() === "POST" && url.pathname === "/v1/i18n/catalog") {
      providerCalls.push(url.pathname);
      return; // never answers: a stalled provider must not matter
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
  const de = shipped("de");
  await expect(page.getByText(de[sourceKey("Settings")], { exact: true }).first()).toBeVisible();
  await expect(page.getByText(de[sourceKey("Timezone")], { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Timezone", { exact: true })).toHaveCount(0);
  expect(providerCalls).toEqual([]);
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
