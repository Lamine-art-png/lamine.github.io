import { expect, test } from "@playwright/test";

const APP_URL = "http://127.0.0.1:4173/settings";
const API_ORIGIN = "https://api.agroai-pilot.com";

function qaToken() {
  const body = Buffer.from(JSON.stringify({ sub: "qa", exp: 4102444800 })).toString("base64url");
  return `qa.${body}.sig`;
}

async function prepare(page, patchStatus = 200) {
  const state = { patches: 0, payloads: [] };
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
    if (req.method() === "PATCH" && url.pathname === "/v1/settings/preferences") {
      state.patches += 1;
      try { state.payloads.push(req.postDataJSON()); } catch { state.payloads.push({}); }
      return reply(patchStatus >= 400 ? { detail: "sync failed" } : { status: "saved" }, patchStatus);
    }
    return reply({});
  });
  return state;
}

function languageSelector(page) {
  return page.locator("select").filter({ has: page.locator('option[value="fr-FR"]') }).first();
}

test("render and locale event rerender cause zero preference PATCH calls", async ({ page }) => {
  const state = await prepare(page);
  await page.goto(APP_URL);
  await expect(languageSelector(page)).toHaveValue("en");
  expect(state.patches).toBe(0);

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("agroai:locale-change", {
      detail: { selectedLocale: "fr-FR", locale: "fr-FR", effectiveLocale: "fr-FR" },
    }));
  });
  await expect(languageSelector(page)).toHaveValue("fr-FR");
  await page.waitForTimeout(150);
  expect(state.patches).toBe(0);
});

test("failed preference PATCH preserves local switch and does not recurse", async ({ page }) => {
  const state = await prepare(page, 500);
  await page.goto(APP_URL);
  const language = languageSelector(page);
  await expect(language).toHaveValue("en");

  await language.selectOption("fr-FR");
  await expect(language).toHaveValue("fr-FR");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_locale_v1"))).toBe("fr-FR");
  await page.waitForTimeout(250);

  expect(state.patches).toBe(1);
  expect(state.payloads).toEqual([{ locale: "fr-FR" }]);
});
