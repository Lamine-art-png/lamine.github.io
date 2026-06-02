import assert from "node:assert/strict";

const playwrightModule = process.env.PLAYWRIGHT_MODULE || "playwright";
const { chromium } = await import(playwrightModule);
const baseUrl = process.env.VELIA_MOBILE_URL || "http://127.0.0.1:4174";
const screenshotDir = new URL("../screenshots/", import.meta.url);

const browser = await chromium.launch({
  headless: process.env.HEADLESS !== "0",
  executablePath: process.env.CHROME_EXECUTABLE || undefined,
});
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true });

async function clearPwaState() {
  await page.evaluate(async () => {
    localStorage.clear();
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((reg) => reg.unregister()));
    }
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    }
  });
}

async function expectText(text) {
  await page.getByText(text, { exact: false }).first().waitFor({ timeout: 7000 });
}

async function screenshot(name) {
  await page.screenshot({ path: new URL(`${name}.png`, screenshotDir).pathname, fullPage: true });
}

await page.goto(`${baseUrl}/?acceptance=${Date.now()}`);
await clearPwaState();
await page.reload();
await expectText("Set up my farm");
await page.getByText("Set up my farm").click();
await page.getByText("Farmer").click();
await page.locator("[data-onboard-continue]").click();
await page.locator("#farmName").fill("Silverado Vineyard");
await page.locator("#farmLocation").fill("Napa");
await page.locator("[data-onboard-continue]").click();
await page.locator("#fieldName").fill("North Block");
await page.locator("#fieldLocation").fill("North bench");
await page.locator("#crop").fill("Grapes");
await page.locator("#acreage").fill("10");
await page.locator("[data-onboard-continue]").click();
await page.getByText("Drip").click();
await page.locator("#soilType").fill("Loam");
await page.locator("#waterSource").fill("Well");
await page.locator("[data-onboard-continue]").click();
await expectText("Good morning");
await expectText("Silverado Vineyard");
await expectText("North Block");
await expectText("Grapes");
await screenshot("onboarding-completed-stabilized");
await screenshot("today-manual-onboarding-stabilized");

await page.goto(`${baseUrl}/?demo=1&acceptance=${Date.now()}`);
await expectText("Demo preview");
await expectText("Record field check");
assert.equal(await page.getByText("Log irrigation").count(), 0);
await screenshot("today-demo-stabilized");

await page.locator(".bottom-nav [data-nav='fields']").click();
await expectText("North Cabernet Block");
await expectText("West Chardonnay Block");
await screenshot("fields-stabilized");
await page.locator("[data-open-field]").first().click();
await expectText("Map-ready field");
await screenshot("field-detail-stabilized");

await page.goto(`${baseUrl}/?demo=1&screen=alerts&acceptance=${Date.now()}`);
await expectText("Act now");
await expectText("South Merlot Block");
const firstResolve = page.locator('[data-resolve-alert="verification:block-c"]').first();
const resolvedKey = await firstResolve.getAttribute("data-resolve-alert");
await firstResolve.click();
await page.waitForTimeout(200);
assert.equal(await page.locator(`[data-resolve-alert="${resolvedKey}"]`).count(), 0);
await page.reload();
assert.equal(await page.locator(`[data-resolve-alert="${resolvedKey}"]`).count(), 0);
await screenshot("alerts-stabilized");

await page.goto(`${baseUrl}/?demo=1&screen=assistant&acceptance=${Date.now()}`);
await expectText("Field intelligence, in conversation");
await expectText("Should I irrigate today?");
await screenshot("ask-velia-stabilized");

await page.goto(`${baseUrl}/?demo=1&screen=more&acceptance=${Date.now()}`);
await expectText("Farm controls");
await screenshot("more-stabilized");

await page.goto(`${baseUrl}/?demo=1&acceptance=${Date.now()}`);
await page.waitForLoadState("networkidle");
await page.reload();
await expectText("Demo preview");
await page.context().setOffline(true);
await page.reload({ waitUntil: "domcontentloaded" });
await expectText("Offline mode active");
await expectText("Silverado Vineyard");

await browser.close();
console.log("Velia mobile browser acceptance passed");
