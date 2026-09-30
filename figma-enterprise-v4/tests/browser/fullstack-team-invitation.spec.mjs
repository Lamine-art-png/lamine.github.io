import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Full-stack: the real API (agroai_api/scripts/e2e_fullstack_server.py) behind
// a portal build whose VITE_API_BASE_URL points at it. The invitee follows the
// exact link captured from the invitation email.
const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:5173";
const OUTBOX = process.env.AGROAI_E2E_OUTBOX;
const SEED = process.env.AGROAI_E2E_SEED;

test.skip(!OUTBOX || !SEED, "requires the full-stack e2e server (AGROAI_E2E_OUTBOX, AGROAI_E2E_SEED)");

// The first-run product tour opens asynchronously; dismiss it whenever it
// appears, as a customer would.
async function skipProductTour(page) {
  await page.addLocatorHandler(page.getByRole("dialog", { name: "AGRO-AI product tour" }), async () => {
    await page.getByRole("button", { name: "Skip product tour" }).click();
  });
}

function invitationLinkFor(email) {
  const messages = readFileSync(OUTBOX, "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line));
  const message = messages.reverse().find((row) => row.to_email === email);
  if (!message) return null;
  const match = message.text_body.match(/https?:\/\/\S*\/accept-invite\?token=[A-Za-z0-9_-]+/);
  return match ? new URL(match[0]) : null;
}

test("owner invites a new teammate who accepts from the emailed link and appears in Members", async ({ browser, page }) => {
  const owner = JSON.parse(readFileSync(SEED, "utf8"));
  const invitee = `grower.${Date.now()}@e2e.agroai.test`;

  await page.goto(`${APP}/?lang=en`);
  await page.getByLabel("Email").first().fill(owner.email);
  await page.getByLabel("Password").first().fill(owner.password);
  const login = page.waitForResponse((response) => response.url().endsWith("/v1/auth/login") && response.request().method() === "POST");
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForFunction(() => Boolean(window.localStorage.getItem("agroai_access_token")), null, { timeout: 15_000 });
  await expect(page.getByRole("button", { name: /^Sign in$/ })).toHaveCount(0, { timeout: 15_000 });

  await skipProductTour(page);
  await page.goto(`${APP}/team`);
  await page.getByPlaceholder(/teammate@/).fill(invitee);
  await page.getByRole("combobox").filter({ hasText: "Operator" }).selectOption("operator");
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByText(`Invitation email sent to ${invitee}.`)).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-invitation-status="pending"]').filter({ hasText: invitee })).toBeVisible();

  const link = invitationLinkFor(invitee);
  expect(link, "the invitation email must carry a single-use accept link").not.toBeNull();
  const token = link.searchParams.get("token");

  const inviteeContext = await browser.newContext();
  const inviteePage = await inviteeContext.newPage();
  await skipProductTour(inviteePage);
  await inviteePage.goto(`${APP}/accept-invite?token=${token}&lang=en`);
  await expect(inviteePage.getByRole("heading", { name: owner.organization })).toBeVisible({ timeout: 15_000 });
  await inviteePage.getByLabel("Full name").fill("E2E Grower");
  await inviteePage.getByLabel("Password").fill("Canal-Orchard-Valve-2026");
  await inviteePage.getByRole("checkbox").check();
  await inviteePage.getByRole("button", { name: "Create account and join" }).click();
  await inviteePage.waitForURL(`${APP}/team`, { timeout: 20_000 });
  await expect(inviteePage.getByText("E2E Grower").first()).toBeVisible({ timeout: 15_000 });
  await inviteeContext.close();

  const replayContext = await browser.newContext();
  const replayPage = await replayContext.newPage();
  await replayPage.goto(`${APP}/accept-invite?token=${token}&lang=en`);
  await expect(replayPage.getByRole("heading", { name: "Invitation unavailable" })).toBeVisible({ timeout: 15_000 });
  await replayContext.close();

  await page.reload();
  await expect(page.getByText("E2E Grower").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-invitation-status="accepted"]').filter({ hasText: invitee })).toBeVisible();
});
