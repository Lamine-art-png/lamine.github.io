import { test, expect } from "@playwright/test";

test.describe("Entry screen", () => {
  test("launches the evaluation workspace without credentials", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "AGRO-AI Water Command Center" })).toBeVisible();
    await expect(page.getByText("Turn scattered irrigation data into verified water decisions.")).toBeVisible();
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await expect(page.locator(".command-page")).toBeVisible();
  });

  test("production sign-in is honest about provisioning", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Sign in for production access" }).click();
    await expect(page.getByText("Production identity provisioning is required for this workspace.")).toBeVisible();
  });

  test("enterprise onboarding opens the brief", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Request enterprise onboarding" }).click();
    await expect(page.getByText("Production workspace requirements")).toBeVisible();
  });
});
