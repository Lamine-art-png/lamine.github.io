import { chromium } from "playwright";
import path from "node:path";

const baseUrl = process.env.AGROAI_MARKETING_URL || "https://agroai-pilot.com";
const proofEmail = process.env.AGROAI_FORM_PROOF_EMAIL || "contact@agroai-pilot.com";
const resumePath = path.resolve(process.env.AGROAI_FORM_PROOF_RESUME || "resume.pdf");

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: "Mozilla/5.0 AGROAIProductionFormProof",
});

async function fillForm(form, marker) {
  const fields = form.locator("input,textarea,select");
  const radioGroups = new Set();

  for (let index = 0; index < (await fields.count()); index += 1) {
    const field = fields.nth(index);
    if (await field.isDisabled().catch(() => true)) continue;

    const name = (await field.getAttribute("name")) || "";
    const id = (await field.getAttribute("id")) || "";
    const key = name || id;
    const type = ((await field.getAttribute("type")) || "").toLowerCase();
    const tag = await field.evaluate((node) => node.tagName.toLowerCase());
    if (!key || ["hidden", "button", "submit", "reset"].includes(type)) continue;

    if (type === "file") {
      await field.setInputFiles(resumePath);
      continue;
    }

    if (type === "radio") {
      const group = name || id;
      if (!radioGroups.has(group)) {
        radioGroups.add(group);
        await field.check().catch(() => {});
      }
      continue;
    }

    if (type === "checkbox") {
      await field.check().catch(() => {});
      continue;
    }

    if (tag === "select") {
      const values = await field.locator("option").evaluateAll((nodes) =>
        nodes
          .filter((node) => node.value && !node.disabled)
          .map((node) => node.value),
      );
      if (values[0]) await field.selectOption(values[0]);
      continue;
    }

    const lower = key.toLowerCase();
    let text = marker;
    if (type === "email" || lower.includes("email")) text = proofEmail;
    else if (type === "tel" || lower.includes("phone")) text = "4155550100";
    else if (type === "url") text = baseUrl;
    else if (type === "number" || lower.includes("acre")) text = "1";
    else if (
      lower.includes("fullname") ||
      lower === "name" ||
      lower.includes("contactname") ||
      lower.includes("first_name") ||
      lower.includes("firstname")
    ) {
      text = "AGRO-AI production browser verification";
    } else if (lower.includes("company") || lower.includes("farmname")) {
      text = "AGRO-AI Inc.";
    } else if (lower.includes("location") || lower.includes("city")) {
      text = "San Francisco, California";
    } else if (lower.includes("linkedin")) {
      text = "https://www.linkedin.com/company/agro-ai-inc/";
    } else if (
      lower.includes("portfolio") ||
      lower.includes("proof") ||
      lower.includes("github") ||
      lower.includes("website")
    ) {
      text = baseUrl;
    }
    await field.fill(text);
  }
}

function captureTraffic(page) {
  const legacyLeaks = [];
  const posts = [];
  page.on("request", (request) => {
    if (request.method() !== "POST") return;
    posts.push(request.url());
    if (/formspree\.io|agroai-demo-request\..*workers\.dev/i.test(request.url())) {
      legacyLeaks.push(request.url());
    }
  });
  return { legacyLeaks, posts };
}

async function describeForms(page) {
  return page.locator("form").evaluateAll((forms) =>
    forms.map((form, index) => ({
      index,
      visible: !!(form.offsetWidth || form.offsetHeight || form.getClientRects().length),
      authoritative: form.dataset.agroaiAuthoritativeForm || "",
      action: form.action,
      method: form.method,
      noValidate: form.noValidate,
      fieldCount: form.querySelectorAll("input,textarea,select").length,
      fields: Array.from(form.querySelectorAll("input,textarea,select")).map((field) => ({
        tag: field.tagName.toLowerCase(),
        type: field.type || "",
        name: field.name || "",
        id: field.id || "",
        required: !!field.required,
        value: field.value || "",
      })),
      submitControls: Array.from(
        form.querySelectorAll('button, input[type="submit"]'),
      ).map((control) => ({
        type: control.type || "",
        text: (control.textContent || control.value || "").trim(),
        disabled: !!control.disabled,
      })),
    })),
  );
}

async function chooseDemoForm(page) {
  await page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll("form")).some(
        (form) => form.dataset.agroaiAuthoritativeForm === "demo",
      ),
    null,
    { timeout: 30_000 },
  );

  const forms = page.locator('form[data-agroai-authoritative-form="demo"]');
  const count = await forms.count();
  if (!count) throw new Error("No form was marked as the authoritative demo form.");

  let selectedIndex = 0;
  let selectedScore = -1;
  for (let index = 0; index < count; index += 1) {
    const form = forms.nth(index);
    if (!(await form.isVisible())) continue;
    const score = await form.evaluate((node) => {
      const fields = node.querySelectorAll("input,textarea,select").length;
      const submitText = Array.from(
        node.querySelectorAll('button, input[type="submit"]'),
      )
        .map((control) => (control.textContent || control.value || "").toLowerCase())
        .join(" ");
      const intentScore = /demo|consultation|request|submit/.test(submitText) ? 100 : 0;
      return intentScore + fields;
    });
    if (score > selectedScore) {
      selectedScore = score;
      selectedIndex = index;
    }
  }

  return forms.nth(selectedIndex);
}

async function verifyCareers() {
  const page = await context.newPage();
  const traffic = captureTraffic(page);
  await page.goto(`${baseUrl}/careers`, {
    waitUntil: "networkidle",
    timeout: 60_000,
  });

  const applyLink = page
    .getByRole("link", { name: /apply now|apply for this role/i })
    .first();
  await applyLink.waitFor({ state: "visible", timeout: 30_000 });
  await applyLink.click();
  await page.waitForLoadState("networkidle").catch(() => {});

  const currentPath = new URL(page.url()).pathname;
  if (currentPath !== "/apply" && !currentPath.startsWith("/apply/")) {
    throw new Error(`Unexpected Careers application path: ${currentPath}`);
  }

  const form = page.locator('form[data-agroai-authoritative-form="careers"]').first();
  await form.waitFor({ state: "visible", timeout: 45_000 });
  const runtimeActive = await page.evaluate(
    () => window.__AGROAI_FORMS_RUNTIME__ === true,
  );
  if (!runtimeActive) throw new Error("Careers runtime is inactive on /apply.");

  const marker = `careers-real-ui-${Date.now()}`;
  await fillForm(form, marker);

  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/apply",
    { timeout: 60_000 },
  );
  await form.locator('button[type="submit"],input[type="submit"]').first().click();
  const response = await responsePromise;
  const body = await response.text();
  if (
    response.status() !== 200 ||
    response.headers()["x-agroai-notification"] !== "delivered"
  ) {
    throw new Error(`Careers delivery failed: HTTP ${response.status()} ${body}`);
  }
  await page
    .getByText("Application received", { exact: true })
    .waitFor({ timeout: 20_000 });
  if (traffic.legacyLeaks.length) {
    throw new Error(`Careers leaked to: ${traffic.legacyLeaks.join(", ")}`);
  }

  console.log(`CAREERS_PATH=${currentPath}`);
  console.log(`CAREERS_MARKER=${marker}`);
  await page.close();
}

async function verifyDemo() {
  const page = await context.newPage();
  const traffic = captureTraffic(page);
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto(`${baseUrl}/book-a-demo`, {
    waitUntil: "networkidle",
    timeout: 60_000,
  });

  const runtimeActive = await page.evaluate(
    () => window.__AGROAI_FORMS_RUNTIME__ === true,
  );
  if (!runtimeActive) throw new Error("Book a Demo runtime is inactive.");

  const form = await chooseDemoForm(page);
  await form.waitFor({ state: "visible", timeout: 45_000 });
  const marker = `demo-real-ui-${Date.now()}`;
  await fillForm(form, marker);

  const formState = await form.evaluate((node) => ({
    authoritative: node.dataset.agroaiAuthoritativeForm || "",
    noValidate: node.noValidate,
    valid: node.checkValidity(),
    fieldCount: node.querySelectorAll("input,textarea,select").length,
    values: Array.from(node.querySelectorAll("input,textarea,select")).map((field) => ({
      key: field.name || field.id || "",
      value: field.value || "",
    })),
    submitText: Array.from(node.querySelectorAll('button,input[type="submit"]'))
      .map((control) => (control.textContent || control.value || "").trim())
      .join(" | "),
  }));
  console.log(`DEMO_FORM_STATE=${JSON.stringify(formState)}`);

  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/demo-request",
    { timeout: 30_000 },
  );

  const submit = form.locator('button[type="submit"],input[type="submit"]').first();
  if (!(await submit.count())) {
    throw new Error(
      `Demo form has no submit control. Forms=${JSON.stringify(await describeForms(page))}`,
    );
  }
  await submit.click();

  let response;
  try {
    response = await responsePromise;
  } catch (error) {
    throw new Error(
      `Demo click produced no /api/demo-request response. ` +
        `Posts=${JSON.stringify(traffic.posts)} ` +
        `Console=${JSON.stringify(consoleErrors)} ` +
        `Forms=${JSON.stringify(await describeForms(page))} ` +
        `Original=${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const body = await response.text();
  if (
    response.status() !== 201 ||
    response.headers()["x-agroai-notification"] !== "delivered"
  ) {
    throw new Error(`Demo delivery failed: HTTP ${response.status()} ${body}`);
  }
  await page
    .getByText("Demo request received", { exact: true })
    .waitFor({ timeout: 20_000 });
  if (traffic.legacyLeaks.length) {
    throw new Error(`Demo leaked to: ${traffic.legacyLeaks.join(", ")}`);
  }

  console.log(`DEMO_MARKER=${marker}`);
  await page.close();
}

try {
  await verifyCareers();
  await verifyDemo();
} finally {
  await browser.close();
}
