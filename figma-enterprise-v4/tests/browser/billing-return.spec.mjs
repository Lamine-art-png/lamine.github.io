import { expect, test } from "@playwright/test";

const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";

function jwt() {
  return `qa.${Buffer.from(JSON.stringify({ sub: "billing-user", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url")}.sig`;
}

test("Checkout return waits for authoritative activation and refreshes the plan", async ({ page }) => {
  let reconcileCalls = 0;
  let active = false;
  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
  }, jwt());

  const handler = async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const org = { id: "billing-org", name: "Billing Farm", role: "owner", plan: active ? "professional" : "free", subscription_status: active ? "active" : "inactive" };
    if (path === "/v1/auth/me" || path === "/v1/auth/bootstrap") {
      return json({ user: { id: "billing-user", name: "Owner", email: "owner@example.com", email_verified: true }, current_organization: org, organizations: [org], workspaces: [], entitlements: {} });
    }
    if (path === "/v1/billing/commercial-summary") {
      const plan = active ? "professional" : "free";
      return json({ current_plan: { id: plan, name: active ? "Professional" : "Free", public_price_monthly: "$299", public_price_annual: "$2,990" }, plan_id: plan, billing_status: active ? "active" : "inactive", quota_rows: [], upgrade_options: [], can_manage_billing: true });
    }
    if (path === "/v1/billing/reconcile-checkout") {
      const submitted = route.request().postDataJSON();
      expect(submitted).toEqual({ organization_id: "billing-org", session_id: "cs_return" });
      reconcileCalls += 1;
      if (reconcileCalls === 1) return json({ status: "confirming" });
      active = true;
      return json({ status: "active", plan: "professional" });
    }
    if (path === "/v1/orgs") return json({ organizations: [org] });
    if (path === "/v1/workspaces") return json({ workspaces: [] });
    if (route.request().method() === "GET") return json({});
    return json({ status: "ok" });
  };
  await page.route("https://api.agroai-pilot.com/**", handler);
  await page.route(`${APP}/v1/**`, handler);
  await page.goto(`${APP}/billing?checkout=success&session_id=cs_return`);
  await expect(page.getByText("Confirming your subscription…")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Your subscription is active.")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Professional", { exact: true }).first()).toBeVisible();
  expect(reconcileCalls).toBe(2);
  expect(new URL(page.url()).searchParams.has("checkout")).toBe(false);
});
