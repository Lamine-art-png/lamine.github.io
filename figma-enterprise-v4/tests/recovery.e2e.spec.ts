import { expect, test } from "@playwright/test";

test("account recovery lifecycle", async ({ page }) => {
  const calls: unknown[] = [];
  await page.route("**/v1/auth/account-recovery/start", async (route) => {
    calls.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "If an account exists, recovery instructions were sent." }) });
  });
  await page.route("**/v1/auth/account-recovery/complete", async (route) => {
    calls.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Account access updated." }) });
  });

  await page.goto("/");
  await expect(page.getByRole("link", { name: "Forgot password?" })).toBeVisible();
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(page).toHaveURL(/recover-account$/);
  await page.getByLabel("Email").fill("operator@example.com");
  await page.getByRole("button", { name: "Send recovery instructions" }).click();
  await expect(page.getByText("If an account exists, recovery instructions were sent.")).toBeVisible();

  await page.goto("/reset-password?token=e2e-one-time-token");
  await page.getByLabel("New sign-in credential").fill("A-strong-new-credential-2026");
  await page.getByLabel("Confirm sign-in credential").fill("A-strong-new-credential-2026");
  await page.getByRole("button", { name: "Update account access" }).click();
  await expect(page.getByRole("heading", { name: "Account access updated" })).toBeVisible();

  expect(calls).toEqual([
    { email: "operator@example.com" },
    { token: "e2e-one-time-token", replacement_credential: "A-strong-new-credential-2026" },
  ]);
});
