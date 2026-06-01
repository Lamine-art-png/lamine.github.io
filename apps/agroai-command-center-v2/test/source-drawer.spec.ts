import { test, expect } from "@playwright/test";
import { Buffer } from "node:buffer";

test.describe("Source drawer", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector(".command-page");
  });

  test("opens and shows the four tabs", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await expect(page.locator(".drawer")).toBeVisible();
    for (const tab of ["Connected systems", "Upload records", "API access", "Partner feeds"]) {
      await expect(page.getByRole("tab", { name: tab })).toBeVisible();
    }
  });

  test("connected systems uses truthful states and opens a setup brief", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    const drawer = page.locator(".drawer");
    await expect(drawer.getByText("Live-ready", { exact: true })).toBeVisible();
    await expect(drawer.getByText("Runtime reachable", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Connect or configure" }).click();
    await expect(page.getByText("Integration setup brief")).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy brief" })).toBeVisible();
  });

  test("upload tab accepts a file and surfaces parse status", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await page.getByRole("tab", { name: "Upload records" }).click();
    await expect(page.locator(".dropzone")).toBeVisible();
    await page.locator("input[type='file']").setInputFiles({
      name: "controller_events.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("timestamp,farm,block\n2026-05-14T21:00:00Z,Alpha Vineyard,Block A North\n"),
    });
    await expect(page.getByText("controller_events.csv")).toBeVisible({ timeout: 10_000 });
  });

  test("partner feeds never claim a live integration", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await page.getByRole("tab", { name: "Partner feeds" }).click();
    await expect(page.getByText("Partner feed authorization required for production use.")).toBeVisible();
    await expect(page.getByText(/EarthDaily/)).toHaveCount(0);
  });
});
