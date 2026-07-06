import { expect, test } from "@playwright/test";

const APP_URL = "http://127.0.0.1:4173/intelligence";
const API_ORIGIN = "https://api.agroai-pilot.com";
const CONVERSATION_ID = "conv-block-7";

const seededConversation = {
  id: CONVERSATION_ID,
  title: "Block 7 evidence",
  workspace_id: "ws-qa",
  status: "active",
  preview: "Persisted conversation for locale-switch acceptance",
  message_count: 3,
  created_at: "2026-07-04T18:00:00Z",
  updated_at: "2026-07-04T18:03:00Z",
};

const seededMessages = [
  {
    id: "msg-user-first",
    role: "user",
    content: "Initial Block 7 irrigation evidence request",
    created_at: "2026-07-04T18:00:00Z",
  },
  {
    id: "msg-assistant-first",
    role: "assistant",
    content: "Initial verified Block 7 evidence response",
    created_at: "2026-07-04T18:01:00Z",
  },
  {
    id: "msg-user-last",
    role: "user",
    content: "Last persisted Block 7 note",
    created_at: "2026-07-04T18:03:00Z",
  },
];

function futureJwt() {
  const payload = Buffer.from(
    JSON.stringify({ sub: "qa-user", exp: Math.floor(Date.now() / 1000) + 3600 }),
  )
    .toString("base64url");
  return `qa.${payload}.signature`;
}

async function installPortalMocks(page, { initialLocale = "en" } = {}) {
  const counters = {
    conversationPost: 0,
    messagePost: 0,
    intelligenceRequest: 0,
    preferencePatch: 0,
    conversationReads: [],
    preferencePayloads: [],
  };
  let brainAttempt = 0;

  await page.addInitScript(
    ({ token, locale }) => {
      localStorage.setItem("agroai_access_token", token);
      localStorage.setItem("agroai_locale_v1", locale);
    },
    { token: futureJwt(), locale: initialLocale },
  );

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const postData = () => {
      try {
        return request.postDataJSON();
      } catch {
        return {};
      }
    };

    if (method === "GET" && path === "/v1/auth/me") {
      return json({
        user: { id: "qa-user", name: "QA Operator", email: "qa@example.com" },
        current_organization: { id: "org-qa", name: "QA Farm", role: "owner" },
        organizations: [{ id: "org-qa", name: "QA Farm", role: "owner" }],
        entitlements: {},
      });
    }
    if (method === "GET" && path === "/v1/orgs") {
      return json({ organizations: [{ id: "org-qa", name: "QA Farm", role: "owner" }] });
    }
    if (method === "GET" && path === "/v1/workspaces") {
      return json({ workspaces: [{ id: "ws-qa", name: "QA Workspace", status: "active" }] });
    }
    if (method === "PATCH" && path === "/v1/settings/preferences") {
      counters.preferencePatch += 1;
      counters.preferencePayloads.push(postData());
      return json({ status: "saved" });
    }
    if (method === "GET" && path === "/v1/intelligence/brain/conversations") {
      return json({ conversations: [seededConversation] });
    }
    if (method === "POST" && path === "/v1/intelligence/brain/conversations") {
      counters.conversationPost += 1;
      return json({ conversation: { ...seededConversation, id: "conv-created" } });
    }
    if (method === "GET" && path === `/v1/intelligence/brain/conversations/${CONVERSATION_ID}`) {
      counters.conversationReads.push(CONVERSATION_ID);
      return json({ conversation: seededConversation, messages: seededMessages });
    }
    if (method === "POST" && path === `/v1/intelligence/brain/conversations/${CONVERSATION_ID}/messages`) {
      counters.messagePost += 1;
      return json({ conversation: { ...seededConversation, message_count: 5 } });
    }
    if (method === "POST" && path === "/v1/intelligence/brain/run") {
      counters.intelligenceRequest += 1;
      brainAttempt += 1;
      if (brainAttempt === 1) {
        return json({ status: "language_generation_failed", model_status: "language_generation_failed" });
      }
      return json({
        status: "success",
        model_status: "live",
        result: { answer: "Validated retry response without duplicating the user turn." },
      });
    }
    if (method === "POST" && path === "/v1/intelligence/run") {
      counters.intelligenceRequest += 1;
      return json({
        status: "success",
        model_status: "live",
        result: { answer: "Legacy fallback response." },
      });
    }
    if (method === "POST" && path === "/v1/agents/actions/plan") {
      return json({ actions: [] });
    }
    if (method === "DELETE" && path.startsWith("/v1/intelligence/brain/conversations/")) {
      return route.fulfill({ status: 204, body: "" });
    }

    return json({});
  });

  return counters;
}

function languageSelector(page) {
  return page.locator("select").filter({ has: page.locator('option[value="fr-FR"]') }).first();
}

test("locale switches preserve exact drafts, persisted chat state, network invariants, and component identity", async ({ page }) => {
  const counters = await installPortalMocks(page, { initialLocale: "en" });
  await page.goto(APP_URL);

  const textarea = page.locator("textarea");
  const selector = languageSelector(page);
  await expect(textarea).toBeVisible();
  await expect(selector).toBeVisible();

  const block7Draft = "Check irrigation evidence for Block 7";
  await textarea.fill(block7Draft);
  await textarea.evaluate((node) => node.setAttribute("data-browser-acceptance-sentinel", "same-node"));

  const beforeBlock7 = {
    conversationPost: counters.conversationPost,
    messagePost: counters.messagePost,
    intelligenceRequest: counters.intelligenceRequest,
    preferencePatch: counters.preferencePatch,
  };

  await selector.selectOption("fr-FR");
  await expect(textarea).toHaveValue(block7Draft);
  await expect(textarea).toHaveAttribute("data-browser-acceptance-sentinel", "same-node");
  await selector.selectOption("en");
  await expect(textarea).toHaveValue(block7Draft);
  await expect(textarea).toHaveAttribute("data-browser-acceptance-sentinel", "same-node");

  expect(counters.conversationPost).toBe(beforeBlock7.conversationPost);
  expect(counters.messagePost).toBe(beforeBlock7.messagePost);
  expect(counters.intelligenceRequest).toBe(beforeBlock7.intelligenceRequest);
  expect(counters.preferencePatch - beforeBlock7.preferencePatch).toBe(2);
  expect(counters.preferencePayloads.slice(-2)).toEqual([{ locale: "fr-FR" }, { locale: "en" }]);

  const multilineDraft = "Review the missing evidence.\n\nDo not send yet.";
  await textarea.fill(multilineDraft);
  await selector.selectOption("fr-FR");
  await expect(textarea).toHaveValue(multilineDraft);
  await selector.selectOption("en");
  await expect(textarea).toHaveValue(multilineDraft);

  const conversationButton = page.getByRole("button", { name: /Block 7 evidence/ }).first();
  await conversationButton.click();
  expect(counters.conversationReads).toEqual([CONVERSATION_ID]);

  const messageArticles = page.locator("article");
  await expect(messageArticles).toHaveCount(3);
  const beforeMessages = await messageArticles.allTextContents();
  expect(beforeMessages[0]).toContain(seededMessages[0].content);
  expect(beforeMessages[1]).toContain(seededMessages[1].content);
  expect(beforeMessages[2]).toContain(seededMessages[2].content);

  const beforePersistedSwitch = {
    conversationPost: counters.conversationPost,
    messagePost: counters.messagePost,
    intelligenceRequest: counters.intelligenceRequest,
    preferencePatch: counters.preferencePatch,
  };
  await selector.selectOption("fr-FR");
  await selector.selectOption("en");
  await expect(messageArticles).toHaveCount(3);
  expect(await messageArticles.allTextContents()).toEqual(beforeMessages);
  expect(counters.conversationPost).toBe(beforePersistedSwitch.conversationPost);
  expect(counters.messagePost).toBe(beforePersistedSwitch.messagePost);
  expect(counters.intelligenceRequest).toBe(beforePersistedSwitch.intelligenceRequest);
  expect(counters.preferencePatch - beforePersistedSwitch.preferencePatch).toBe(2);
});

test("French shell has no known English leakage or raw translation keys", async ({ page }) => {
  await installPortalMocks(page, { initialLocale: "en" });
  await page.goto(APP_URL);
  const selector = languageSelector(page);
  await expect(selector).toBeVisible();
  await selector.selectOption("fr-FR");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");

  const body = page.locator("body");
  for (const englishShell of [
    "Workspace intelligence",
    "Ask a question or import files.",
    "Start a workspace thread",
    "Search chats",
    "No saved chats yet.",
    "Enter to send. Shift + Enter for a new line.",
  ]) {
    await expect(body).not.toContainText(englishShell);
  }

  for (const rawKey of [
    "newChat",
    "askAgroAi",
    "fieldQueue",
    "intelligence.newChat",
    "intelligence.history",
    "common.retry",
  ]) {
    await expect(page.getByText(rawKey, { exact: true })).toHaveCount(0);
  }
});

test("auto remains the selected preference under fr-CA browser resolution and PATCH persists auto exactly once", async ({ browser }) => {
  const context = await browser.newContext({ locale: "fr-CA" });
  const page = await context.newPage();
  const counters = await installPortalMocks(page, { initialLocale: "auto" });
  await page.goto(APP_URL);

  const selector = languageSelector(page);
  await expect(selector).toHaveValue("auto");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");

  await selector.selectOption("en");
  const beforeAuto = counters.preferencePatch;
  await selector.selectOption("auto");
  await expect(selector).toHaveValue("auto");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");
  expect(counters.preferencePatch - beforeAuto).toBe(1);
  expect(counters.preferencePayloads.at(-1)).toEqual({ locale: "auto" });

  await context.close();
});

test("failed language generation persists no fake answer and retry does not duplicate the user turn", async ({ page }) => {
  const counters = await installPortalMocks(page, { initialLocale: "en" });
  await page.goto(APP_URL);
  await page.getByRole("button", { name: /Block 7 evidence/ }).first().click();
  await expect(page.locator("article")).toHaveCount(3);

  const prompt = "Preserve this retry user turn exactly.";
  const textarea = page.locator("textarea");
  await textarea.fill(prompt);
  await textarea.press("Enter");

  await expect.poll(() => counters.intelligenceRequest).toBe(1);
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  expect(counters.messagePost).toBe(0);
  await expect(page.getByText(prompt, { exact: true })).toHaveCount(1);
  await expect(page.getByText("Validated retry response without duplicating the user turn.", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Retry" }).click();
  await expect.poll(() => counters.intelligenceRequest).toBe(2);
  await expect.poll(() => counters.messagePost).toBe(1);
  await expect(page.getByText("Validated retry response without duplicating the user turn.", { exact: true })).toBeVisible();
  await expect(page.getByText(prompt, { exact: true })).toHaveCount(1);
});
