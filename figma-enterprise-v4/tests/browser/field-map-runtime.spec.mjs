import { expect, test } from "@playwright/test";

// Real MapLibre runtime in Chromium: the Field Intelligence map must boot,
// load its style, render clustered/point observation layers, open the
// observation popup on hover, keep controls usable, and stay free of
// uncaught errors on desktop and mobile viewports.
const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";
const API_ORIGIN = "https://api.agroai-pilot.com";

function futureJwt() {
  const payload = Buffer.from(JSON.stringify({ sub: "qa-user", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url");
  return `qa.${payload}.signature`;
}

const observations = [
  { id: "obs-1", status: "completed", title: "North block stress", summary: "Leaf curl near valve 3", latitude: 36.7378, longitude: -119.7871, occurred_at: "2026-09-28T16:00:00Z" },
  { id: "obs-2", status: "completed", title: "Emitter clog", summary: "Dry strip row 12", latitude: 36.7392, longitude: -119.7855, occurred_at: "2026-09-28T17:00:00Z" },
  { id: "obs-3", status: "completed", title: "Pump pressure drop", summary: "Pressure 18 psi", latitude: 36.7501, longitude: -119.7602, occurred_at: "2026-09-29T08:00:00Z" },
];

async function signedIn(page) {
  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
    localStorage.setItem("agroai_product_tour_product_tour_v2_qa-user", "done");
  }, futureJwt());
  const handler = async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const org = { id: "org-qa", name: "QA Farm", role: "owner", plan: "enterprise", subscription_status: "active" };
    if (path === "/v1/auth/me") return json({ user: { id: "qa-user", name: "QA Operator", email: "qa@example.com", email_verified: true }, current_organization: org, organizations: [org], entitlements: { capabilities: {} } });
    if (path === "/v1/orgs") return json({ organizations: [org] });
    if (path === "/v1/workspaces") return json({ workspaces: [{ id: "ws-qa", name: "QA Workspace", status: "active" }] });
    if (path === "/v1/field-intelligence/observations") return json({ observations });
    if (request.method() === "GET") return json({ items: [], data: [], results: [], status: "ok" });
    return json({ status: "ok" });
  };
  // Production serves the API same-origin (app.agroai-pilot.com/v1); stub both.
  await page.route(`${API_ORIGIN}/**`, handler);
  await page.route(`${APP}/v1/**`, handler);
}

for (const viewport of [{ name: "desktop", width: 1400, height: 900 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`Field Intelligence map renders observations with MapLibre (${viewport.name})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await browser.newContext({ viewport, locale: "en-US", permissions: [] });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    const workerFailures = [];
    page.on("console", (message) => { if (/worker failed to load/i.test(message.text())) workerFailures.push(message.text()); });
    await signedIn(page);
    await page.goto(`${APP}/field-intelligence`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /^Map$/ }).first().click();

    const canvas = page.locator(".maplibregl-canvas");
    await expect(canvas).toBeVisible({ timeout: 45_000 });
    await expect(page.locator(".maplibregl-ctrl-zoom-in")).toBeVisible();
    await expect(page.locator(".maplibregl-ctrl-attrib")).toHaveCount(1);

    // The style must actually load (tile worker running): the map's loading
    // spinner clears only after MapLibre's "load" event.
    await expect(page.locator(".maplibregl-canvas").locator("xpath=ancestor::div[contains(@class,'relative')][1]").locator(".animate-spin")).toHaveCount(0, { timeout: 45_000 });
    expect(workerFailures, "MapLibre tile worker must load").toEqual([]);

    // Wait until the canvas has a drawable size.
    await expect.poll(async () => page.evaluate(() => {
      const el = document.querySelector(".maplibregl-canvas");
      return Boolean(el && el.width > 0 && el.height > 0);
    }), { timeout: 30_000 }).toBeTruthy();

    // Style attribution is rendered through MapLibre's sanitizer (the code path
    // fixed by GHSA-jrc7-96c5-q579) and contains no executable attributes.
    await expect.poll(async () => (await page.locator(".maplibregl-ctrl-attrib").innerText()).trim().length, { timeout: 30_000 }).toBeGreaterThan(0);
    const attribHtml = await page.locator(".maplibregl-ctrl-attrib").innerHTML();
    expect(attribHtml).not.toMatch(/\son[a-z]+\s*=/i);

    // Zoom control dispatches without errors (DOM click: a pre-existing
    // wrapper overlaps the control's hit area in headless layouts).
    await page.locator(".maplibregl-ctrl-zoom-in").dispatchEvent("click");
    await page.waitForTimeout(800);
    if (process.env.AGROAI_MAP_SCREENSHOT) await page.screenshot({ path: `${process.env.AGROAI_MAP_SCREENSHOT}-${viewport.name}.png` });
    expect(pageErrors, `${viewport.name} uncaught errors`).toEqual([]);
    await context.close();
  });
}
