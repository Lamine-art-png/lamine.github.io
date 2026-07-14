import { expect, test } from "@playwright/test";

const API_ORIGIN = "https://api.agroai-pilot.com";

function qaToken() {
  const body = Buffer.from(JSON.stringify({ sub: "qa", exp: 4102444800 })).toString("base64url");
  return `qa.${body}.sig`;
}

async function prepare(page, { plan = "professional", maxWorkspaces = 5, workspaces, failUploadNumber = 0, sources = [] } = {}) {
  const sourceRows = sources.map((source) => ({ ...source }));
  const state = { creates: [], renames: [], uploads: [], deletes: [], jobPolls: 0, sourceRows };
  const workspaceRows = workspaces || [
    { id: "ws-1", organization_id: "org", name: "North Ranch", mode: "evaluation" },
    { id: "ws-2", organization_id: "org", name: "South Ranch", mode: "evaluation" },
  ];

  await page.addInitScript((token) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", "en");
    localStorage.setItem("agroai_product_tour_product_tour_v2_qa", "done");
  }, qaToken());

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const reply = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (request.method() === "GET" && url.pathname === "/v1/auth/me") {
      return reply({
        user: { id: "qa", name: "QA Owner", email: "qa@example.com" },
        current_organization: { id: "org", name: "QA Agriculture", role: "owner", plan, subscription_status: plan === "free" ? "inactive" : "active" },
        organizations: [{ id: "org", name: "QA Agriculture", role: "owner", plan }],
        entitlements: { max_workspaces: maxWorkspaces, access_profile: "customer", capabilities: {} },
      });
    }
    if (request.method() === "GET" && url.pathname === "/v1/orgs") {
      return reply({ organizations: [{ id: "org", name: "QA Agriculture", role: "owner", plan }] });
    }
    if (request.method() === "GET" && url.pathname === "/v1/workspaces") return reply({ workspaces: workspaceRows });
    if (request.method() === "GET" && url.pathname === "/v1/settings/preferences") return reply({ preferences: {} });
    if (request.method() === "POST" && url.pathname === "/v1/i18n/catalog") {
      const payload = request.postDataJSON();
      return reply({ status: "ok", locale: payload.locale, catalog: payload.source, source: "browser-test" });
    }
    if (request.method() === "POST" && url.pathname === "/v1/workspaces") {
      const payload = request.postDataJSON();
      state.creates.push(payload);
      return reply({
        workspace: { id: "ws-3", organization_id: "org", name: payload.name, crop: payload.crop, region: payload.region, mode: payload.mode },
        entitlements: { max_workspaces: maxWorkspaces, access_profile: "customer", capabilities: {} },
      }, 201);
    }
    if (request.method() === "POST" && url.pathname === "/v1/evidence/upload") {
      state.uploads.push({ workspaceId: url.searchParams.get("workspace_id"), provider: url.searchParams.get("provider") });
      if (failUploadNumber && state.uploads.length === failUploadNumber) {
        return reply({ detail: { code: "test_upload_failure", message: "Synthetic upload failure" } }, 500);
      }
      const jobId = `job-${state.uploads.length}`;
      sourceRows.push({
        id: `source-${state.uploads.length}`,
        job_id: jobId,
        filename: `uploaded-${state.uploads.length}.csv`,
        provider: url.searchParams.get("provider") || "manual_csv",
        source_type: "pending_upload",
        processing_status: "queued",
        evidence_count: 0,
        rows_parsed: 0,
        intelligence_ready: false,
        pending: true,
      });
      return reply({
        status: "queued",
        phase: "stored",
        durable_stored: true,
        processing_pending: true,
        job_id: jobId,
        queue_publication: { published: 1, failed: 0 },
      });
    }
    if (request.method() === "GET" && url.pathname === "/v1/source-library") {
      return reply({ status: "ok", source_count: sourceRows.length, sources: sourceRows });
    }
    if (request.method() === "GET" && url.pathname.startsWith("/v1/source-library/")) {
      const id = decodeURIComponent(url.pathname.split("/").pop() || "");
      const source = sourceRows.find((item) => item.id === id);
      return source ? reply({ status: "ok", source, evidence: [] }) : reply({ detail: "Source not found" }, 404);
    }
    if (request.method() === "DELETE" && url.pathname.startsWith("/v1/source-library/")) {
      const id = decodeURIComponent(url.pathname.split("/").pop() || "");
      const index = sourceRows.findIndex((item) => item.id === id);
      if (index < 0) return reply({ detail: "Source not found" }, 404);
      const [deleted] = sourceRows.splice(index, 1);
      state.deletes.push(id);
      return reply({ status: "deleted", source_id: id, filename: deleted.filename, evidence_deleted: deleted.evidence_count || 0 });
    }
    if (request.method() === "GET" && url.pathname.startsWith("/v1/connectors/jobs/")) {
      state.jobPolls += 1;
      return reply({ job: { status: "queued" } });
    }
    if (request.method() === "PATCH" && url.pathname === "/v1/workspaces/ws-1") {
      const payload = request.postDataJSON();
      state.renames.push(payload);
      return reply({ workspace: { ...workspaceRows[0], name: payload.name }, message: "Operation name updated." });
    }
    if (request.method() === "PATCH" && url.pathname === "/v1/settings/preferences") return reply({ status: "saved" });
    return reply({});
  });
  return state;
}

test("new operation creates and activates an isolated workspace", async ({ page }) => {
  const state = await prepare(page);
  await page.goto("http://127.0.0.1:4173/");

  await page.getByRole("link", { name: "New operation" }).first().click();
  await expect(page).toHaveURL(/\/operations\/new$/);
  await expect(page.locator("[data-new-operation-page]")).toBeVisible();
  await page.locator("[data-operation-name-input]").fill("Ventura Avocado Portfolio");
  await page.getByPlaceholder("Avocados, almonds, mixed crops").fill("Avocados");
  await page.getByPlaceholder("Ventura County, California").fill("Ventura County, California");
  await page.locator("[data-create-operation-button]").click();

  await expect(page).toHaveURL("http://127.0.0.1:4173/");
  expect(state.creates).toEqual([{
    organization_id: "org",
    name: "Ventura Avocado Portfolio",
    crop: "Avocados",
    region: "Ventura County, California",
    mode: "evaluation",
  }]);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_active_operation_v1:org"))).toBe("ws-3");
});

test("new operation stages every selected file without waiting on each processing job", async ({ page }) => {
  const state = await prepare(page, { failUploadNumber: 3 });
  await page.goto("http://127.0.0.1:4173/operations/new");
  await page.locator("[data-operation-name-input]").fill("Eight-file operation");
  await page.locator("[data-operation-file-input]").setInputFiles(
    Array.from({ length: 8 }, (_, index) => ({
      name: `${String(index + 1).padStart(2, "0")}_source.csv`,
      mimeType: "text/csv",
      buffer: Buffer.from("field,value\nA,1\n"),
    })),
  );

  await page.locator("[data-create-operation-button]").click();
  await expect(page).toHaveURL(/\/evidence$/);
  await expect.poll(() => state.uploads.length).toBe(8);
  expect(state.uploads.every((upload) => upload.workspaceId === "ws-3")).toBe(true);
  expect(state.jobPolls).toBe(0);
});

test("source library accepts repeated upload batches in the same operation", async ({ page }) => {
  const state = await prepare(page);
  await page.goto("http://127.0.0.1:4173/sources");
  const input = page.locator("[data-source-repeat-file-input]");

  await input.setInputFiles([
    { name: "first.csv", mimeType: "text/csv", buffer: Buffer.from("field,value\nA,1\n") },
    { name: "second.csv", mimeType: "text/csv", buffer: Buffer.from("field,value\nB,2\n") },
  ]);
  await expect.poll(() => state.uploads.length).toBe(2);
  await expect(page.getByText("Upload more files", { exact: true })).toBeVisible();

  await input.setInputFiles([
    { name: "third.csv", mimeType: "text/csv", buffer: Buffer.from("field,value\nC,3\n") },
  ]);
  await expect.poll(() => state.uploads.length).toBe(3);
  expect(state.uploads.every((upload) => upload.workspaceId === "ws-1")).toBe(true);
});

test("source library permanently deletes a stored file after confirmation", async ({ page }) => {
  const state = await prepare(page, {
    sources: [{
      id: "source-delete-me",
      filename: "delete-me.csv",
      provider: "manual_csv",
      source_type: "telemetry_csv",
      processing_status: "succeeded",
      evidence_count: 2,
      rows_parsed: 4,
      intelligence_ready: true,
      pending: false,
    }],
  });
  await page.goto("http://127.0.0.1:4173/sources");

  const row = page.locator('[data-tour="source-library-table"] article').filter({ hasText: "delete-me.csv" }).first();
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("alertdialog", { name: "Confirm file deletion" })).toBeVisible();
  await page.getByRole("button", { name: "Delete permanently" }).click();

  await expect.poll(() => state.deletes).toEqual(["source-delete-me"]);
  await expect(page.getByText("delete-me.csv was deleted with 2 linked evidence record(s).")).toBeVisible();
});

test("operation switcher changes and persists the active workspace", async ({ page }) => {
  await prepare(page);
  await page.goto("http://127.0.0.1:4173/");

  const operationSwitcher = page.getByRole("combobox", { name: "Switch operation" });
  await expect(operationSwitcher).toHaveValue("ws-1");
  await operationSwitcher.selectOption("ws-2");
  await expect(operationSwitcher).toHaveValue("ws-2");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_active_operation_v1:org"))).toBe("ws-2");

  await page.reload();
  await expect(page.getByRole("combobox", { name: "Switch operation" })).toHaveValue("ws-2");
});

test("plan capacity blocks creation without hiding existing operations", async ({ page }) => {
  await prepare(page, {
    plan: "free",
    maxWorkspaces: 1,
    workspaces: [{ id: "ws-1", organization_id: "org", name: "Only operation", mode: "evaluation" }],
  });
  await page.goto("http://127.0.0.1:4173/operations/new");

  await expect(page.locator("[data-operation-limit-reached]")).toBeVisible();
  await expect(page.getByText("Your Free plan includes 1 operation.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Return to current operation" })).toBeVisible();
});

test("desktop sidebar collapses, opens, and persists the preference", async ({ page }) => {
  await prepare(page);
  await page.goto("http://127.0.0.1:4173/");

  const sidebar = page.locator("[data-desktop-sidebar]");
  await expect(sidebar).toHaveAttribute("data-collapsed", "false");
  await page.getByRole("button", { name: "Close sidebar" }).click();
  await expect(sidebar).toHaveAttribute("data-collapsed", "true");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("agroai_sidebar_collapsed_v1"))).toBe("true");

  await page.reload();
  await expect(page.locator("[data-desktop-sidebar]")).toHaveAttribute("data-collapsed", "true");
  await page.getByRole("button", { name: "Open sidebar" }).first().click();
  await expect(page.locator("[data-desktop-sidebar]")).toHaveAttribute("data-collapsed", "false");
});

test("settings renames the active operation without creating another workspace", async ({ page }) => {
  const state = await prepare(page);
  await page.goto("http://127.0.0.1:4173/settings");

  const operationCard = page.locator("section").filter({ has: page.getByRole("heading", { name: "Current operation" }) });
  await operationCard.locator("[data-operation-name-setting]").fill("Renamed North Ranch");
  await operationCard.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("Operation name saved.")).toBeVisible();
  expect(state.renames).toEqual([{ name: "Renamed North Ranch" }]);
  await expect(operationCard.locator("[data-operation-name-setting]")).toHaveValue("Renamed North Ranch");
});
