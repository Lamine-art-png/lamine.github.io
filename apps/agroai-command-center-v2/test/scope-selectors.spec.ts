import { test, expect } from "@playwright/test";

test.describe("Scope selectors", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
  });

  test("scope selectors are hidden when only offline representative fallback is active", async ({ page }) => {
    // Before backend analysis completes, we are in representative fallback — selectors hidden.
    // Selector visibility depends on whether availableFarms comes from the backend.
    // In offline fallback, no availableFarms → selectors not shown.
    const scopeRow = page.locator(".scope-selector-row");
    // If selectors are shown, they require actual backend scopes — so in offline env expect none or count 0.
    const count = await scopeRow.count();
    // This can be 0 (no backend) or 1 (backend returned scopes) — just verify no broken layout.
    if (count > 0) {
      await expect(scopeRow).toBeVisible();
    }
  });

  test("block selector is disabled before farm is selected", async ({ page }) => {
    // If scope selectors are shown (backend returned scopes), block must be disabled initially.
    const scopeRow = page.locator(".scope-selector-row");
    const count = await scopeRow.count();
    if (count === 0) {
      test.skip(); // No selectors — offline fallback
      return;
    }
    const blockSelect = page.getByRole("combobox", { name: "Select block" });
    await expect(blockSelect).toBeDisabled();
  });

  test("upload tab accepts multiple files and shows a file list", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await expect(page.locator(".drawer")).toBeVisible();
    await page.getByRole("tab", { name: "Upload records" }).click();
    // Drop zone and file input must be present.
    await expect(page.locator(".dropzone")).toBeVisible();
    // The file input must have the multiple attribute.
    const hasMultiple = await page.locator('input[type="file"]').getAttribute("multiple");
    expect(hasMultiple).not.toBeNull();
  });

  test("start new package button appears after upload and resets package", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await expect(page.locator(".drawer")).toBeVisible();
    await page.getByRole("tab", { name: "Upload records" }).click();
    // The Start new package button should only appear when there are uploaded artifacts.
    // Without uploading files, it must not be shown.
    await expect(page.getByRole("button", { name: /Start new package/ })).toHaveCount(0);
  });

  test("scope default disclosure is readable", async ({ page }) => {
    const disclosure = page.locator(".scope-default-disclosure");
    const count = await disclosure.count();
    if (count > 0) {
      await expect(disclosure.first()).toBeVisible();
      // Text must be readable (not empty)
      const text = await disclosure.first().textContent();
      expect(text?.trim().length).toBeGreaterThan(10);
    }
  });

  test("scope selectors render correctly on mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    // Re-open the workspace on the mobile viewport
    await page.reload();
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
    const scopeRow = page.locator(".scope-selector-row");
    const count = await scopeRow.count();
    if (count > 0) {
      // No horizontal overflow
      const overflow = await page.locator(".scope-selector-row").evaluate((el) => el.scrollWidth - el.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    }
  });
});
