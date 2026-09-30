import { expect, test } from "@playwright/test";

// A transient API failure while loading the session must not sign the
// customer out; only an authentication rejection may.
const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";

function jwt() {
  return `qa.${Buffer.from(JSON.stringify({ sub: "u1", org_id: "o1", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url")}.sig`;
}

const org = { id: "o1", name: "Resilient Farm", role: "owner", plan: "team", subscription_status: "active" };
const session = { user: { id: "u1", email: "r@example.com", name: "R", email_verified: true }, current_organization: org, organizations: [org], workspaces: [], entitlements: {} };

async function routeApi(page, bootstrap) {
  const handler = async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/v1/auth/bootstrap" || path === "/v1/auth/me") return bootstrap(json);
    if (request.method() === "GET") return json({});
    return json({ status: "ok" });
  };
  await page.route("https://api.agroai-pilot.com/**", handler);
  await page.route(`${APP}/v1/**`, handler);
}

test("server errors while loading the session keep the customer signed in", async ({ page }) => {
  let healthy = false;
  await routeApi(page, (json) => (healthy ? json(session) : json({ detail: "upstream unavailable" }, 503)));
  const token = jwt();
  await page.addInitScript((value) => window.localStorage.setItem("agroai_access_token", value), token);
  await page.goto(`${APP}/?lang=en`);
  await expect(page.getByRole("heading", { name: "AGRO-AI is temporarily unreachable" })).toBeVisible({ timeout: 20_000 });
  expect(await page.evaluate(() => window.localStorage.getItem("agroai_access_token"))).toBe(token);
  await expect(page.getByRole("button", { name: /^Sign in$/ })).toHaveCount(0);

  healthy = true;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "AGRO-AI is temporarily unreachable" })).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByRole("button", { name: /^Sign in$/ })).toHaveCount(0);
});

test("an authentication rejection still ends the session", async ({ page }) => {
  await routeApi(page, (json) => json({ detail: "Invalid token" }, 401));
  await page.addInitScript((value) => window.localStorage.setItem("agroai_access_token", value), jwt());
  await page.goto(`${APP}/?lang=en`);
  await expect(page.getByRole("button", { name: /^Sign in$/ })).toBeVisible({ timeout: 15_000 });
  expect(await page.evaluate(() => window.localStorage.getItem("agroai_access_token"))).toBeNull();
});
