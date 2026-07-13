import { expect, test } from "@playwright/test";

const API_ORIGIN = "https://api.agroai-pilot.com";

function qaToken() {
  const body = Buffer.from(JSON.stringify({ sub: "qa", exp: 4102444800 })).toString("base64url");
  return `qa.${body}.sig`;
}

async function prepare(page, { plan = "professional", maxWorkspaces = 5, workspaces } = {}) {
  const state = { creates: [], renames: [] };
  const workspaceRows = workspaces || [
    { id: "ws-1", organization_id: "org", name: "North Ranch", mode: "evaluation" },
    { id: "ws-2", organization_id: "org", name: "South Ranch", mode: "evaluation" },
  ];

  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
  }, qaToken());

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const reply = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (request.method() === "GET" && url.pathname === "/v1/auth/me") {
      return reply({
        user: { id: "qa", name: "QA Owner", email: "qa@example.com" },
        current_organization: { id: "org", name: "QA Agriculture", role: "owner", plan, subscription_status: plan === "free" ? "inactive" : "active" },
        organizations: [{ id: "org", name: "QA Agriculture", role: "owner", plan }],
        entitlements: { max_workspaces: maxWorkspaces, access_profile: "customer", capabilities: {} },
      });
    }
    if (request.method() === "GET" && url.pathname === "/v1/orgs") {
      return reply({ organizations: [{ id: "org", name: "QA Agriculture", role: "owner", plan }] });
    }
    if (request.method() === "GET" && url.pathname === "/v1/workspaces") return reply({ workspaces: workspaceRows });
    if (request.method() === "GET" && url.pathname === "/v1/settings/preferences") return reply({ preferences: {} });
    if (request.method() === "POST" && url.pathname === "/v1/i18n/catalog") {
      const payload = request.postDataJSON();
      return reply({ status: "ok", locale: payload.locale, catalog: payload.source, source: "browser-test" });
    }
    if (request.method() === "POST" && url.pathname === "/v1/workspaces") {
      const payload = request.postDataJSON();
      state.creates.push(payload);
      return reply({
        workspace: { id: "ws-3", organization_id: "org", name: payload.name, crop: payload.crop, region: payload.region, mode: payload.mode },
        entitlements: { max_workspaces: maxWorkspaces, access_profile: "customer", capabilities: {} },
      }, 201);
    }
    if (request.method() === "PATCH" && url.pathname === "/v1/workspaces/ws-1") {
      const payload = request.postDataJSON();
      state.renames.push(payload);
      return reply({ workspace: { ...workspaceRows[0], name: payload.name }, message: "Operation name updated." });
    }
    if (request.method() === "PATCH" && url.pathname === "/v1/settings/preferences") return reply({ status: "saved" });
    return reply({});
  });
  return state;
}

test("new operation creates and activates an isolated workspace", async ({ page }) => {
  const state = await prepare(page);
  await page.goto("http://127.0.0.1:4173/");

  await page.getByRole("link", { name: "New operation" }).first().click();
  await expect(page).toHaveURL(/\/operations\/new$/);
  await expect(page.locator("[data-new-operation-page]")).toBeVisible();
  await page.locator("[data-operation-name-input]").fill("Ventura Avocado Portfolio");
  await page.getByPlaceholder("Avocados, almonds, mixed crops").fill("Avocados");
  await page.getByPlaceholder("Ventura County, California").fill("Ventura County, California");
  await page.locator("[data-create-operation-button]").click();

  await expect(page).toHaveURL("http://127.0.0.1:4173/");
  expect(state.creates).toEqual([{
    organization_id: "org",
    name: "Ventura Avocado Portfolio",
    crop: "Avocados",
    region: "Ventura County, California",
    mode: "evaluation",
  }]);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_active_operation_v1:org"))).toBe("ws-3");
});

test("plan capacity blocks creation without hiding existing operations", async ({ page }) => {
  await prepare(page, {
    plan: "free",
    maxWorkspaces: 1,
    workspaces: [{ id: "ws-1", organization_id: "org", name: "Only operation", mode: "evaluation" }],
  });
  await page.goto("http://127.0.0.1:4173/operations/new");

  await expect(page.locator("[data-operation-limit-reached]")).toBeVisible();
  await expect(page.getByText("Your Free plan includes 1 operation.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Return to current operation" })).toBeVisible();
});

test("desktop sidebar collapses, opens, and persists the preference", async ({ page }) => {
  await prepare(page);
  await page.goto("http://127.0.0.1:4173/");

  const sidebar = page.locator("[data-desktop-sidebar]");
  await expect(sidebar).toHaveAttribute("data-collapsed", "false");
  await page.getByRole("button", { name: "Close sidebar" }).click();
  await expect(sidebar).toHaveAttribute("data-collapsed", "true");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_sidebar_collapsed_v1"))).toBe("true");

  await page.reload();
  await expect(page.locator("[data-desktop-sidebar]")).toHaveAttribute("data-collapsed", "true");
  await page.getByRole("button", { name: "Open sidebar" }).first().click();
  await expect(page.locator("[data-desktop-sidebar]")).toHaveAttribute("data-collapsed", "false");
});

test("settings renames the active operation without creating another workspace", async ({ page }) => {
  const state = await prepare(page);
  await page.goto("http://127.0.0.1:4173/settings");

  const operationCard = page.locator("section").filter({ has: page.getByRole("heading", { name: "Current operation" }) });
  await operationCard.locator("[data-operation-name-setting]").fill("Renamed North Ranch");
  await operationCard.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("Operation name saved.")).toBeVisible();
  expect(state.renames).toEqual([{ name: "Renamed North Ranch" }]);
  await expect(operationCard.locator("[data-operation-name-setting]")).toHaveValue("Renamed North Ranch");
});
