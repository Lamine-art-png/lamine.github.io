// Read-only production browser proof: intercept form submission and Calendly,
// so no prospect email or real meeting is created during verification.
import assert from "node:assert/strict";
import { chromium } from "@playwright/test";

const base = process.env.DEMO_BASE_URL || "https://agroai-pilot.com";
const expectHint = process.env.EXPECT_HINT === "1";
const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const intercepted = [];
    await context.route("**/api/demo-request", async (route) => {
      const request = route.request();
      intercepted.push({ method: request.method(), body: request.postDataJSON() });
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers: { "x-agroai-notification": "delivered" },
        body: JSON.stringify({ id: "browser-proof-only", ok: true, status: "received" }),
      });
    });
    await context.route("https://assets.calendly.com/assets/external/widget.js", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: 'window.Calendly={initInlineWidget:function(args){args.parentElement.setAttribute("data-proof-calendly-loaded","true");args.parentElement.setAttribute("data-proof-email",args.prefill.email);}};',
      });
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const response = await page.goto(base + "/book-a-demo", {
      waitUntil: "domcontentloaded", timeout: 60000,
    });
    assert.equal(response?.status(), 200, "Production demo page must return HTTP 200");
    const form = page.locator('form[data-agroai-authoritative-form="demo"]').first();
    await form.waitFor({ state: "visible", timeout: 45000 });
    assert.equal(await page.evaluate(() => window.__AGROAI_FORMS_RUNTIME__ === true), true);
    if (expectHint) {
      const hint = form.locator('[data-agroai-booking-steps="true"]');
      await hint.waitFor({ state: "visible", timeout: 10000 });
      assert.match(await hint.innerText(), /Choose your demo time immediately/);
      assert.match(await hint.innerText(), /Pick a live calendar slot/);
      assert.equal(await form.locator('[data-agroai-booking-steps="true"]').count(), 1);
    }
    assert.equal(await page.locator('[data-agroai-calendar]').count(), 0,
      "Calendar must not bypass lead collection before submission");
    const email = form.locator('input[type="email"],input[name="email"]').first();
    await email.waitFor({ state: "visible", timeout: 10000 });
    await email.fill("qa-calendar-proof@example.com");
    const nameField = form.locator('input[name="fullName"],input[name="name"],input[type="text"]').first();
    if (await nameField.count()) await nameField.fill("AGRO-AI QA Browser Proof");

    await form.evaluate((element) => {
      element.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    const wrapper = page.locator('[data-agroai-demo-scheduling="true"]');
    await wrapper.waitFor({ state: "visible", timeout: 20000 });
    await wrapper.locator('[data-agroai-calendar][data-proof-calendly-loaded="true"]')
      .waitFor({ state: "attached", timeout: 20000 });
    const fallback = wrapper.getByRole("link", { name: /Open the booking calendar/i });
    assert.equal(new URL(await fallback.getAttribute("href")).pathname, "/agroaicontact/30min");
    assert.equal(intercepted.length, 1, "Exactly one demo lead request must occur");
    assert.equal(intercepted[0].method, "POST");
    assert.equal(intercepted[0].body.email, "qa-calendar-proof@example.com");
    assert.equal(await wrapper.locator('[data-agroai-calendar]').getAttribute("data-proof-email"),
      "qa-calendar-proof@example.com");
    assert.equal(errors.length, 0, "Unexpected browser error(s): " + errors.join("; "));
    console.log("PASS live demo form + Calendly UI, viewport " + viewport.width);
    await context.close();
  }
} finally {
  await browser.close();
}
