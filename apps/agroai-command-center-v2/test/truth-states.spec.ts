import { test, expect } from "@playwright/test";

test.describe("Truthful states", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
  });

  test("backend status is one of the three truthful states, never hardcoded online", async ({ page }) => {
    // Backend badge is the first badge in the status row.
    const backendBadge = page.locator(".status-row .status-badge").first();
    await expect(backendBadge).toHaveText(/Backend (available|limited|unavailable)/);
    // The forbidden hardcoded phrasing must never appear.
    await expect(page.getByText("Backend intelligence online")).toHaveCount(0);
  });

  test("scenario switching updates the decision", async ({ page }) => {
    // Switch to incomplete-evidence scenario (the two evaluation scenarios).
    await page.locator(".scenario-selector select").selectOption("incomplete-evidence");
    await expect(page.locator(".decision-headline")).toHaveText(/Evidence review required/);
    // Switch back to validated operating block.
    await page.locator(".scenario-selector select").selectOption("alpha-vineyard");
    await expect(page.locator(".decision-headline")).toHaveText(/Irrigate Block A North/);
  });

  test("recommendation origin is shown and is truthful for representative data", async ({ page }) => {
    await expect(page.locator(".pill--origin")).toHaveText(
      /Representative evaluation mode|Calibrated agronomic context|Live connected analysis|Evaluation package analysis|Evidence incomplete/
    );
  });

  test("representative data is marked exactly once in the header", async ({ page }) => {
    await expect(page.locator(".status-row").getByText("Representative data")).toHaveCount(1);
  });
});
