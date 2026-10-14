import { expect, request as playwrightRequest, test } from "@playwright/test";

// Authenticated Crop Intelligence journey against a DEPLOYED, isolated staging
// portal and API. It runs only from the staging workflow (deploy mode), which
// supplies a canary-organization bearer token from GitHub secrets. Every record
// it creates is clearly labelled SYNTHETIC, lives only in staging, and is
// deleted at the end. Without the staging environment it skips itself.
const PORTAL = (process.env.AGROAI_STAGING_PORTAL_URL || "").replace(/\/$/, "");
const API = (process.env.AGROAI_STAGING_API_URL || "").replace(/\/$/, "");
const TOKEN = process.env.AGROAI_STAGING_TOKEN || "";
const RESTRICTED_TOKEN = process.env.AGROAI_STAGING_RESTRICTED_TOKEN || "";
const RUN = process.env.AGROAI_STAGING_RUN_ID || String(Date.now());
const FIELD_ID = `synthetic-crop-e2e-${RUN}`;
const FIELD_NAME = `SYNTHETIC E2E ${RUN}`;
const PRODUCTION = /(^|\.)agroai-pilot\.com$|agroai-api-preview\.onrender\.com$/i;

test.describe.configure({ mode: "serial", timeout: 180_000 });
test.skip(!PORTAL || !API || !TOKEN, "staging portal, API and canary token are required");

const created = [];
let api;

function refuseProduction(url) {
  const host = new URL(url).hostname;
  if (PRODUCTION.test(host) && !/staging/i.test(host)) throw new Error(`refusing to run against a production host: ${host}`);
}

test.beforeAll(async () => {
  refuseProduction(PORTAL);
  refuseProduction(API);
  api = await playwrightRequest.newContext({ baseURL: API, extraHTTPHeaders: { Authorization: `Bearer ${TOKEN}` } });
  const notes = [
    "SYNTHETIC E2E record: leaves show small brown spots on the west rows of block SYN-A.",
    "SYNTHETIC E2E record: spotting now visible on more leaves on the west rows of block SYN-A.",
  ];
  for (const [index, note] of notes.entries()) {
    const initiated = await api.post("/v1/field-intelligence/captures/initiate", { data: {
      client_capture_id: `syn-crop-${RUN}-${index}`, idempotency_key: `syn-crop-${RUN}-${index}`, capture_source: "typed",
      note_text: note, field_id: FIELD_ID, field_name: FIELD_NAME, block_name: "SYN-A", crop: "Almonds",
    } });
    expect(initiated.ok(), await initiated.text()).toBeTruthy();
    const capture = (await initiated.json()).capture;
    const completed = await api.post(`/v1/field-intelligence/captures/${capture.id}/complete`, { data: {} });
    expect(completed.ok(), await completed.text()).toBeTruthy();
    created.push((await completed.json()).observation.id);
  }
  // Wait for the staging worker to finish processing (read back, never assumed).
  await expect.poll(async () => {
    const states = await Promise.all(created.map(async (id) => (await (await api.get(`/v1/field-intelligence/observations/${id}`)).json()).observation?.status));
    return states.every((state) => ["completed", "needs_review"].includes(state));
  }, { timeout: 150_000, intervals: [3_000] }).toBeTruthy();
});

test.afterAll(async () => {
  for (const id of created) await api?.delete(`/v1/field-intelligence/observations/${id}`).catch(() => undefined);
  await api?.dispose();
});

async function signIn(page, { locale = "en", token = TOKEN } = {}) {
  await page.addInitScript(({ value, selected }) => {
    localStorage.setItem("agroai_access_token", value);
    localStorage.setItem("agroai_locale_v1", selected);
  }, { value: token, selected: locale });
  // Product tours are per-user; dismiss if shown so they do not cover the page.
  page.on("dialog", (dialog) => dialog.dismiss().catch(() => undefined));
}

test("the deployed portal is staging and talks only to the staging API", async ({ request }) => {
  const meta = await (await request.get(`${PORTAL}/deployment-meta.json`)).json();
  expect(meta.environment).toBe("staging");
  expect(meta.api_url.replace(/\/$/, "")).toBe(API);
});

test("unauthenticated visitors cannot read crop data", async ({ page, request }) => {
  expect((await request.get(`${API}/v1/field-intelligence/crop-intelligence/overview`)).status()).toBe(401);
  expect((await request.post(`${API}/v1/field-intelligence/crop-intelligence/production-estimate`, { data: {} })).status()).toBe(401);
  await page.goto(`${PORTAL}/crop-intelligence`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Crop Intelligence" })).toHaveCount(0);
});

test("an authorized user navigates Field → Crop → Market Intelligence and back without errors", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await signIn(page);
  await page.goto(`${PORTAL}/field-intelligence`, { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: "Crop Intelligence" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Crop Intelligence" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(FIELD_NAME).first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("link", { name: "Market Intelligence" }).first().click();
  await expect(page).toHaveURL(/\/market-intelligence/);
  await page.getByRole("link", { name: "Crop Intelligence" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Crop Intelligence" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("crop health shows the synthetic field's evidence and links back to Field Intelligence", async ({ page }) => {
  await signIn(page);
  await page.goto(`${PORTAL}/crop-intelligence?tab=health&field=${encodeURIComponent(FIELD_ID)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("SYNTHETIC E2E record", { exact: false }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Compared with the previous assessment|No earlier assessment|not compared/).first()).toBeVisible();
  await page.getByRole("link", { name: "Open in Field Intelligence" }).click();
  await expect(page).toHaveURL(/\/field-intelligence\?observation=/);
});

test("production, harvest window and maturity calculators run on the real staging backend", async ({ page }) => {
  await signIn(page);
  await page.goto(`${PORTAL}/crop-intelligence?tab=production&field=${encodeURIComponent(FIELD_ID)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByLabel(/What you counted/), "the staging canary organization must be on a Professional-or-higher plan").toBeVisible({ timeout: 30_000 });
  await page.getByLabel(/What you counted/).fill("cluster");
  await page.getByLabel(/Sample unit/).fill("vine");
  await page.getByLabel(/Units in the block/).fill("100");
  await page.getByLabel(/Count for each sampled unit/).fill("10, 12, 8, 11, 9");
  await page.getByLabel("Share of objects visible (0–1)").fill("0.8");
  await page.locator("#prod-visibleShare-se").fill("0.04");
  await page.getByLabel("Average weight per object (kg)").fill("0.15");
  await page.locator("#prod-unitWeight-se").fill("0.0075");
  await page.getByLabel(/Block area/).fill("0.5");
  await page.getByRole("button", { name: "Calculate estimate" }).click();
  await expect(page.getByText("Estimate ready")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("188", { exact: false }).first()).toBeVisible(); // 187.5 kg, hand-checked in the API suite

  await page.getByRole("tab", { name: "Harvest window" }).click();
  await page.getByLabel(/^Crop/).selectOption("corn");
  await page.getByLabel(/Season start/).fill("2026-04-01");
  await page.getByLabel(/Assessment date/).fill("2026-04-30");
  await page.getByLabel(/lower degree days/).fill("1000");
  await page.getByLabel(/upper degree days/).fill("1200");
  await page.getByLabel(/Target source/).fill("SYNTHETIC hybrid sheet");
  const day = (date) => date.toISOString().slice(0, 10);
  const series = (start, count) => Array.from({ length: count }, (_, i) => `${day(new Date(start.getTime() + i * 86_400_000))},30,10`);
  await page.locator("#hw-observed").fill(series(new Date("2026-04-01T00:00:00Z"), 30).join("\n"));
  await page.locator("#hw-analog").fill([2019, 2020, 2021, 2022, 2023].flatMap((year) => series(new Date(`${year}-01-01T00:00:00Z`), 365)).join("\n"));
  await page.getByLabel(/Weather source \(station/).fill("SYNTHETIC station");
  await page.getByLabel(/Earlier seasons source/).fill("SYNTHETIC station history");
  await page.getByRole("button", { name: "Calculate harvest window" }).click();
  await expect(page.getByText("Projected harvest window")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Limitations")).toBeVisible();

  await page.getByRole("tab", { name: "Maturity" }).click();
  await page.getByLabel(/^Crop/).selectOption("almond");
  for (let row = 1; row <= 5; row += 1) {
    await page.getByLabel(`${row} Hull intact`).fill("8");
    await page.getByLabel(`${row} Hull split`).fill("10");
    await page.getByLabel(`${row} Hull open and dry`).fill("2");
  }
  await page.getByRole("button", { name: "Calculate stage shares" }).click();
  await expect(page.getByText("Estimate for the whole block")).toBeVisible({ timeout: 30_000 });
});

test("a reviewed yield proposal reaches Market Intelligence without changing commercial data", async ({ page }) => {
  await signIn(page);
  await page.goto(`${PORTAL}/crop-intelligence?tab=production`, { waitUntil: "domcontentloaded" });
  await page.getByLabel(/What you counted/).fill("cluster");
  await page.getByLabel(/Sample unit/).fill("vine");
  await page.getByLabel(/Units in the block/).fill("100");
  await page.getByLabel(/Count for each sampled unit/).fill("10, 12, 8, 11, 9");
  await page.getByLabel("Share of objects visible (0–1)").fill("0.8");
  await page.locator("#prod-visibleShare-se").fill("0.04");
  await page.getByLabel("Average weight per object (kg)").fill("0.15");
  await page.locator("#prod-unitWeight-se").fill("0.0075");
  await page.getByLabel(/Block area/).fill("0.5");
  await page.getByRole("button", { name: "Calculate estimate" }).click();
  await page.getByRole("button", { name: "Review in Market Intelligence" }).click();
  const review = page.locator("[data-crop-yield-proposal]");
  await expect(review).toBeVisible({ timeout: 30_000 });
  await expect(review.getByText("This is an agricultural estimate, not commercially verified volume.", { exact: false })).toBeVisible();
  // Recording is a deliberate action; it is not taken by this test so staging commercial data stays untouched.
  await review.getByRole("button", { name: "Discard proposal" }).click();
  await expect(review).toHaveCount(0);
});

test("crop intelligence fits a phone screen and is localized", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await signIn(page, { locale: "pt-BR" });
  await page.goto(`${PORTAL}/crop-intelligence`, { waitUntil: "domcontentloaded" });
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => (await heading.innerText()).trim(), { timeout: 30_000 }).not.toBe("Crop Intelligence");
  expect(await page.evaluate(() => { const main = document.querySelector("[data-portal-content]"); return !main || main.scrollWidth <= main.clientWidth + 1; })).toBe(true);
  await context.close();
});

test("a restricted user cannot read another organization's synthetic field", async () => {
  test.skip(!RESTRICTED_TOKEN, "no restricted staging token configured");
  const restricted = await playwrightRequest.newContext({ baseURL: API, extraHTTPHeaders: { Authorization: `Bearer ${RESTRICTED_TOKEN}` } });
  const response = await restricted.get(`/v1/field-intelligence/fields/${encodeURIComponent(FIELD_ID)}/crop-condition`);
  if (response.ok()) expect((await response.json()).summary_status).toBe("no_observations");
  else expect([401, 403, 404]).toContain(response.status());
  await restricted.dispose();
});
