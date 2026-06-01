import { test, expect } from "@playwright/test";

test.describe("Truthful states", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
  });

  test("backend status is one of the three truthful states, never hardcoded online", async ({ page }) => {
    const badge = page.locator(".status-row .status-badge").last();
    await expect(badge).toHaveText(/Backend (available|limited|unavailable)/);
    // The forbidden hardcoded phrasing must never appear.
    await expect(page.getByText("Backend intelligence online")).toHaveCount(0);
  });

  test("scenario switching updates the decision", async ({ page }) => {
    await page.locator(".workspace-switcher select").selectOption("almond-orchard");
    await expect(page.locator(".decision-headline")).toHaveText(/Apply 18 mm/);
    await page.locator(".workspace-switcher select").selectOption("partner-validation");
    await expect(page.locator(".decision-headline")).toHaveText(/Validate partner feed/);
  });

  test("recommendation origin is shown and is truthful for representative data", async ({ page }) => {
    await expect(page.locator(".pill--origin")).toHaveText(/Representative fallback|Deterministic engine|Live intelligence engine|Uploaded intelligence engine/);
  });

  test("representative data is marked exactly once in the header", async ({ page }) => {
    await expect(page.locator(".status-row").getByText("Representative data")).toHaveCount(1);
  });
});
