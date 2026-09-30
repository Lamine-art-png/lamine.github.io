import { expect, test } from "@playwright/test";

// A verification link is single-use. The page must confirm it exactly once and
// show success even though confirming signs the user in (session bootstrap).
const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";

function jwt() {
  return `qa.${Buffer.from(JSON.stringify({ sub: "u1", org_id: "o1", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url")}.sig`;
}

test("verification link is confirmed once and shows success", async ({ page }) => {
  let confirms = 0;
  const org = { id: "o1", name: "Verify Farm", role: "owner", plan: "free", subscription_status: "inactive" };
  const handler = async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/v1/auth/email-verification/confirm") {
      confirms += 1;
      if (confirms > 1) return json({ detail: "Verification link is invalid or expired" }, 400);
      return json({ access_token: jwt(), token_type: "bearer", user: { id: "u1", email: "v@example.com", name: "V" }, current_organization: org, verification: { status: "verified" } });
    }
    if (path === "/v1/auth/bootstrap" || path === "/v1/auth/me") return json({ user: { id: "u1", email: "v@example.com", name: "V", email_verified: true }, current_organization: org, organizations: [org], workspaces: [], entitlements: {} });
    if (request.method() === "GET") return json({});
    return json({ status: "ok" });
  };
  await page.route("https://api.agroai-pilot.com/**", handler);
  await page.route(`${APP}/v1/**`, handler);
  await page.goto(`${APP}/verify-email?token=single-use-token-1234567890&lang=en`);
  await expect(page.getByRole("heading", { name: "Email verified" })).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(1500);
  expect(confirms, "the single-use token must be submitted exactly once").toBe(1);
  await expect(page.getByText("Verification link unavailable")).toHaveCount(0);
});
