import { expect, test } from "@playwright/test";

// Commercial AGRO-AI Intelligence console (paid advisory API) against the real
// production bundle with a stubbed backend. Covers the money and credential
// paths a customer touches: wallet, one-time key display, Playground, Stripe
// return, and the Portal-session boundary on desktop, mobile and RTL.

const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";
const SECRET = ["agro", "live", "consoleqa0123456789abcdefghijklmnop"].join("_");

function jwt() {
  return `qa.${Buffer.from(JSON.stringify({ sub: "console-user", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url")}.sig`;
}

const PRICING = {
  model: "agroai-intelligence-1",
  currency: "usd",
  billing_unit: "completed_intelligence_run",
  failed_or_degraded_runs_are_refunded: true,
  tasks: [
    { id: "answer", name: "Agricultural answer", price_cents: 5, price: "$0.05" },
    { id: "field_diagnosis", name: "Field diagnosis", price_cents: 15, price: "$0.15" },
    { id: "irrigation_plan", name: "Irrigation plan", price_cents: 20, price: "$0.20" },
  ],
};

function walletBody(balanceCents) {
  return {
    currency: "usd",
    balance_cents: balanceCents,
    balance: `$${(balanceCents / 100).toFixed(2)}`,
    lifetime_funded_cents: balanceCents,
    lifetime_spent_cents: 0,
    minimum_topup_cents: 500,
    suggested_topups_cents: [1000, 2500, 10000],
    auto_reload: { enabled: false, available: false },
    recent_activity: [],
  };
}

async function stubConsole(page, { locale = "en", balanceCents = 1000, walletStatus = 200, minimumTopupCents = 500 } = {}) {
  const state = { walletCalls: 0, bootstrapCalls: 0, runKeys: [], overviewCalls: 0, balanceCents, minimumTopupCents };
  await page.addInitScript(({ token, selected }) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", selected);
  }, { token: jwt(), selected: locale });

  const handler = async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const org = { id: "console-org", name: "Console Farm", role: "owner", plan: "professional", subscription_status: "active", verification_status: "approved" };
    if (path === "/v1/auth/me" || path === "/v1/auth/bootstrap") {
      return json({ user: { id: "console-user", name: "Owner", email: "owner@example.com", email_verified: true }, current_organization: org, organizations: [org], workspaces: [], entitlements: {} });
    }
    if (path === "/v1/platform/developer/overview") {
      // Not enrolled in Advanced Platform: this probe is expected to 401 and
      // must never invalidate the customer's Portal session.
      state.overviewCalls += 1;
      return json({ detail: { code: "platform_developer_required" } }, 401);
    }
    if (path === "/v1/intelligence/pricing") return json(PRICING);
    if (path === "/v1/platform/developer/wallet" || path === "/v1/platform/developer/wallet/sync") {
      state.walletCalls += 1;
      if (walletStatus !== 200) return json({ detail: "Not authenticated" }, walletStatus);
      return json({ ...walletBody(state.balanceCents), minimum_topup_cents: state.minimumTopupCents });
    }
    if (path === "/v1/platform/developer/intelligence/bootstrap") {
      state.bootstrapCalls += 1;
      const first = state.bootstrapCalls === 1;
      return json({
        status: first ? "created" : "exists",
        project: { id: "project-1", name: "AGRO-AI Intelligence", environment: "live" },
        key: { id: "key-1", prefix: "agro_live_", fingerprint: "fp_console_1", scopes: ["intelligence:run"], secret: first ? SECRET : null, one_time_display: first },
        endpoint: "https://api.agroai-pilot.com/v1/intelligence",
        model: "agroai-intelligence-1",
        physical_execution: "not_granted",
      });
    }
    if (path === "/v1/platform/developer/intelligence/run") {
      state.runKeys.push(request.headers()["idempotency-key"]);
      return json({ detail: { code: "insufficient_intelligence_balance", balance_cents: state.balanceCents, required_cents: 15 } }, 402);
    }
    if (request.method() === "GET") return json({});
    return json({ status: "ok" });
  };
  await page.route("https://api.agroai-pilot.com/**", handler);
  await page.route(`${APP}/v1/**`, handler);
  return state;
}

async function expectNoHorizontalScroll(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

async function storageValues(page) {
  return page.evaluate(() => {
    const values = [];
    for (const store of [localStorage, sessionStorage]) {
      for (let i = 0; i < store.length; i += 1) values.push(String(store.getItem(store.key(i))));
    }
    return values.join("\n");
  });
}

test("desktop console keeps the Portal session, shows the key once, and never stores it", async ({ page }) => {
  const state = await stubConsole(page);
  await page.goto(`${APP}/platform/home`);
  await expect(page.getByRole("heading", { name: "Put agricultural intelligence inside your product." })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("$10.00").first()).toBeVisible();
  expect(state.overviewCalls).toBeGreaterThan(0);
  // The Advanced Platform probe's 401 must not clear a valid Portal session.
  expect(await page.evaluate(() => localStorage.getItem("agroai_access_token"))).not.toBeNull();

  await page.getByRole("link", { name: "API Keys" }).click();
  await expect(page.getByText("Your LIVE API key was created")).toBeVisible();
  await expect(page.getByText(SECRET)).toBeVisible();
  await expect(page.getByText("Scope: intelligence:run")).toBeVisible();
  expect(await storageValues(page)).not.toContain(SECRET);

  await page.getByRole("link", { name: "Docs" }).click();
  await expect(page.getByText("POST /v1/intelligence")).toBeVisible();
  await expect(page.getByText("agroai-intelligence-1").first()).toBeVisible();
  await page.getByRole("link", { name: "API Keys" }).click();
  await expect(page.getByText("fp_console_1")).toBeVisible();
  await expect(page.getByText(SECRET)).toHaveCount(0);
  expect(await storageValues(page)).not.toContain(SECRET);
});

test("overview states the server minimum top-up, not a hard-coded amount", async ({ page }) => {
  const state = await stubConsole(page, { balanceCents: 0 });
  await page.goto(`${APP}/platform/home`);
  const steps = page.locator("div.grid.gap-5");
  await expect(steps.getByText("Minimum top-up: $5.00")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Prepay $10 or more.")).toHaveCount(0);
  // $10 stays as the recommended quick-add amount.
  await expect(page.getByRole("button", { name: "Add $10" })).toBeVisible();
  state.minimumTopupCents = 700;
  await page.reload();
  await expect(steps.getByText("Minimum top-up: $7.00")).toBeVisible({ timeout: 20_000 });
});

test("Playground sends a fresh idempotency key per run and explains a low balance", async ({ page }) => {
  const state = await stubConsole(page, { balanceCents: 4 });
  await page.goto(`${APP}/platform/playground`);
  await expect(page.getByRole("heading", { name: "Test real agricultural intelligence." })).toBeVisible({ timeout: 20_000 });
  const runButton = page.getByRole("button", { name: "Run intelligence" });
  await runButton.click();
  await expect(page.getByText("Your intelligence balance is too low for this run. Add funds and retry.")).toBeVisible();
  // A wallet top-up is not a Portal subscription upgrade.
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("Upgrade to continue")).toHaveCount(0);
  await runButton.click();
  await expect.poll(() => state.runKeys.length).toBe(2);
  expect(state.runKeys[0]).toMatch(/^playground-/);
  expect(state.runKeys[0]).not.toBe(state.runKeys[1]);
  expect(await page.evaluate(() => localStorage.getItem("agroai_access_token"))).not.toBeNull();
});

test("Stripe return refreshes the wallet balance", async ({ page }) => {
  const state = await stubConsole(page, { balanceCents: 0 });
  await page.goto(`${APP}/platform/home`);
  await expect(page.getByText("$0.00").first()).toBeVisible({ timeout: 20_000 });
  state.balanceCents = 2500;
  const before = state.walletCalls;
  await page.goto(`${APP}/platform/billing?wallet=success&session_id=cs_wallet_return`);
  // "$25.00" also labels an "Add funds" button, so wait for the refresh call
  // itself and then for the balance to appear more than once (button + balance).
  await expect.poll(() => state.walletCalls, { timeout: 20_000 }).toBeGreaterThan(before);
  await expect.poll(() => page.getByText("$25.00").count(), { timeout: 20_000 }).toBeGreaterThan(1);
});

test("an expired Portal session on a wallet call signs the user out", async ({ page }) => {
  await stubConsole(page, { walletStatus: 401 });
  await page.goto(`${APP}/platform/home`);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_access_token")), { timeout: 20_000 }).toBeNull();
});

for (const locale of ["en", "ar"]) {
  test(`mobile console navigation works without horizontal scroll (${locale})`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await stubConsole(page, { locale });
    await page.goto(`${APP}/platform/home`);
    await expect(page.getByText("$10.00").filter({ visible: true }).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("html")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expectNoHorizontalScroll(page);
    await page.locator("header button").first().click();
    const drawer = page.locator("div.fixed.inset-0 nav");
    await expect(drawer).toBeVisible();
    await drawer.locator('a[href="/platform/billing"]').click();
    await expect(page).toHaveURL(/\/platform\/billing$/);
    await expect(drawer).toHaveCount(0);
    await expectNoHorizontalScroll(page);
    await page.goto(`${APP}/platform/docs`);
    await expect(page.getByText("POST /v1/intelligence")).toBeVisible();
    await expectNoHorizontalScroll(page);
  });
}
