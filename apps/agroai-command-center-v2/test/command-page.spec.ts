import { test, expect } from "@playwright/test";

test.describe("Command page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
  });

  test("shows the product story above the fold", async ({ page }) => {
    await expect(page.locator("h1")).toHaveText(/Water Command Center/);
    await expect(page.locator(".header-subtitle")).toHaveText(/Scattered irrigation data becomes a verified water decision\./);
    await expect(page.locator(".status-row")).toHaveText(/Representative data/);
    // Executive strip: four metrics visible.
    await expect(page.locator(".executive-strip .metric")).toHaveCount(4);
    // Verified decision is present and readable.
    await expect(page.locator(".decision-headline")).toBeVisible();
  });

  test("header is not duplicated", async ({ page }) => {
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator(".app-header")).toHaveCount(1);
  });

  test("decision headline does not wrap one character per line", async ({ page }) => {
    const box = await page.locator(".decision-headline").boundingBox();
    expect(box).not.toBeNull();
    // A per-letter-wrapped column collapses to a few ch wide; require a real width.
    expect(box!.width).toBeGreaterThan(180);
    const overflow = await page.locator(".decision-headline").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("refresh intelligence runs and reports a truthful outcome", async ({ page }) => {
    await page.getByRole("button", { name: /Refresh intelligence/ }).click();
    await expect(page.locator(".pipeline-message")).toHaveText(/Decision refreshed|Representative analysis remains active/, { timeout: 20000 });
  });

  test("evidence chain actions complete the chain", async ({ page }) => {
    await page.getByRole("button", { name: "Approve schedule" }).click();
    await page.getByRole("button", { name: "Confirm applied water" }).click();
    await page.getByRole("button", { name: "Add field observation" }).click();
    await page.getByRole("button", { name: "Verify outcome" }).click();
    const done = page.locator(".evidence-step.done");
    await expect(done).toHaveCount(5);
  });

  test("report preview is present and CSV export is wired", async ({ page }) => {
    await expect(page.locator(".report-table")).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export CSV" }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
  });

  test("guided walkthrough runs through the sales-call steps", async ({ page }) => {
    await page.getByRole("button", { name: "Start guided walkthrough" }).click();
    await expect(page.locator(".walkthrough")).toHaveText(/Source intelligence/);
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.locator(".walkthrough")).toHaveText(/Decision pipeline/);
    await page.getByRole("button", { name: "Reset walkthrough" }).click();
    await expect(page.locator(".walkthrough")).toHaveCount(0);
  });
});
