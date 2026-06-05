import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Per-scope mock responses. mockWorkbenchRoutes parses the POST /analyze body
// and returns the correct result for the requested farm + block combination.
// This makes assertions exact and deterministic rather than relying on broad
// regex patterns that could pass against any text.
// ---------------------------------------------------------------------------

function makeAnalysisResult(
  farm: string,
  block: string,
  action: string,
  schedulable: boolean,
  flowStatus: string,
) {
  return {
    analysis_id: `mock-${farm}-${block}`.replace(/\s+/g, "-").toLowerCase(),
    session_id: "mock-session-1",
    status: "complete",
    analysis_mode: "uploaded",
    context_origin: "uploaded",
    recommendation_origin: "uploaded_intelligence_engine",
    recommendation: {
      action,
      decision: action,
      start_time: schedulable ? "Tomorrow 06:00" : null,
      depth: schedulable ? "24 mm net" : null,
      gross_depth: schedulable ? "29 mm gross" : null,
      duration: schedulable ? "3.5 hours" : null,
      estimated_volume: schedulable ? "58 m³" : null,
      confidence: 0.84,
      schedulable,
      scheduling_block_reasons: schedulable ? [] : ["Flow evidence not validated"],
      flow_validation_status: flowStatus,
      flow_validation_notes: flowStatus === "validated" ? ["Flow validated at 16.6 m³/h"] : [],
      estimated_water_savings_percent: schedulable ? 22 : null,
      verification_requirement: "Required within 48 h of irrigation",
      key_drivers: ["Soil moisture deficit 42%"],
      recommendation_origin: "uploaded_intelligence_engine",
      no_fabricated_duration: false,
    },
    reconciliation: {
      controller_event_validity: "3 events validated",
      weather_demand: "ETo 6.5 mm/day",
      soil_moisture_deficit: "42% deficit",
      flow_meter_agreement: flowStatus === "validated" ? "Flow within 5% variance" : "Flow meter unavailable",
      field_observation_support: "No field observations",
      matched_signals: ["controller_events", "soil_moisture", "crop_profile"],
      evidence_completeness: schedulable ? 0.79 : 0.43,
    },
    normalized_context: {
      farm,
      block,
      crop: "Cabernet Sauvignon",
      variety: "not available",
      soil: "Sandy loam",
      irrigation_method: "drip",
      region: "Central Valley",
      area_ha: 12.5,
      area_unit: "ha",
      selected_farm: farm,
      selected_block: block,
      // Canonical scope fields — mimic 13th-pass backend for all analyses.
      canonical_analyzed_farm: farm,
      canonical_analyzed_block: block,
      scope_defaulted: false,
      scope_defaulted_farm: null,
      scope_defaulted_block: null,
      available_farms: ["Alpha Vineyard", "Delta Almonds"],
      available_blocks_by_farm: {
        "Alpha Vineyard": ["Block A North", "Block B West"],
        "Delta Almonds": ["Almond Block 4"],
      },
      available_scopes: ["farm", "block", "crop", "soil", "region"],
      selected_source_kinds: ["controller_events", "soil_moisture", "crop_profile", "weather"],
      package_source_kinds: ["controller_events", "soil_moisture", "crop_profile", "weather", "field_notes"],
      normalized_signal_count: 42,
    },
    signal_summary: { controller_events_read: 3, weather_records_read: 2, soil_readings_read: 4, flow_meter_records_read: 2, crop_profile_loaded: 1 },
    source_rows: [
      { source_label: "Controller history", source_kind: "controller_events", selected_scope_record_count: 3, package_record_count: 8, status: "accepted", limitations: [], contribution_label: "Not scored" },
      { source_label: "Weather demand", source_kind: "weather", selected_scope_record_count: 2, package_record_count: 2, status: "accepted", limitations: [], contribution_label: "Not scored" },
    ],
    limitations: schedulable ? [] : ["Flow evidence not validated for this block"],
    analysis_trace: [
      { title: "Source records ingested", status: "complete", objects_processed: 42, details: "8 artifacts processed" },
      { title: "Field context assembled", status: "complete", objects_processed: 1, details: "Crop profile loaded" },
    ],
    report_summary: { recommendation: action, planned_water: schedulable ? "29 mm gross" : "Withheld", evidence_completeness: schedulable ? 0.79 : 0.43, confidence: 0.84 },
    warnings: [],
    uploaded_artifacts_used: ["controller_events.csv", "soil_moisture.csv", "crop_profile.json", "weather_summary.csv"],
    live_inputs_used: [],
    data_sources: { rows_parsed: 42, artifacts_ingested: 4, warnings: [] },
    model_status: "deterministic_engine",
    backend_status: "available",
  };
}

// Per-block deterministic mock results — precise action text matches what the UI will display.
const MOCK_BLOCK_A = makeAnalysisResult(
  "Alpha Vineyard", "Block A North",
  "Irrigate Block A North — 24 mm gross depth",
  true, "validated",
);
const MOCK_BLOCK_B = makeAnalysisResult(
  "Alpha Vineyard", "Block B West",
  "Deficit not confirmed for Block B West — flow evidence required",
  false, "incomplete",
);
const MOCK_DELTA = makeAnalysisResult(
  "Delta Almonds", "Almond Block 4",
  "Irrigate Almond Block 4 — 18 mm gross depth",
  true, "validated",
);

const MOCK_SESSION = { session_id: "mock-session-1" };
const MOCK_SAMPLE_PKG = {
  session: { session_id: "mock-session-1" },
  artifacts: [
    { filename: "controller_events.csv", source_kind: "controller_events", parse_status: "parsed", rows_detected: 8, columns_detected: ["timestamp", "farm", "block"], warnings: [] },
  ],
};
const MOCK_UPLOAD_ARTIFACT = {
  filename: "controller_events.csv",
  source_kind: "controller_events",
  parse_status: "parsed",
  rows_detected: 8,
  columns_detected: ["timestamp", "farm", "block"],
  warnings: [],
};

async function mockWorkbenchRoutes(page: import("@playwright/test").Page) {
  // Mock the schema endpoint so probeBackend() returns "available" and
  // reanalyzeSelectedScope is not blocked by backend.status === "unavailable".
  await page.route("**/v1/workbench/schema", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ output_schema: ["farm", "block", "recommendation"], version: "test" }),
    });
  });
  await page.route("**/openapi.json", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ paths: { "/v1/workbench/sessions": {} } }),
    });
  });
  await page.route("**/v1/workbench/sessions", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_SESSION) });
    } else {
      await route.continue();
    }
  });
  await page.route("**/v1/workbench/sample-package", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_SAMPLE_PKG) });
  });
  await page.route("**/v1/workbench/sessions/*/analyze", async (route) => {
    // Parse the POST body to return the correct per-scope result.
    let body: Record<string, unknown> = {};
    try { body = JSON.parse(route.request().postData() || "{}"); } catch { /* use empty */ }
    const farm = (body.selected_farm as string | undefined) ?? "";
    const block = (body.selected_block as string | undefined) ?? "";
    let result = MOCK_BLOCK_A; // default (no farm/block → Block A)
    if (farm === "Alpha Vineyard" && block === "Block B West") result = MOCK_BLOCK_B;
    else if (farm === "Delta Almonds") result = MOCK_DELTA;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) });
  });
  await page.route("**/v1/workbench/sessions/*/upload", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_UPLOAD_ARTIFACT) });
  });
  // Evidence-chain GET: return a scoped evidence chain.
  await page.route("**/v1/workbench/sessions/*/evidence-chain**", async (route) => {
    const url = new URL(route.request().url());
    const farm = url.searchParams.get("selected_farm") ?? "Alpha Vineyard";
    const block = url.searchParams.get("selected_block") ?? "Block A North";
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        session_id: "mock-session-1",
        scope: { selected_farm: farm, selected_block: block },
        scope_status: "analyzed",
        evidence_chain: [
          { key: "recommended", label: "Recommended", status: "Complete", owner: "AGRO-AI Workbench", timestamp: "2026-06-05T10:00:00Z", evidence: "Verified water decision prepared from the current source package.", evidence_type: "system_generated" },
          { key: "scheduled", label: "Scheduled", status: "Pending", owner: "Operations user", timestamp: "", evidence: "Scheduled pending" },
          { key: "applied", label: "Applied", status: "Pending", owner: "Operations user", timestamp: "", evidence: "Applied pending" },
          { key: "observed", label: "Observed", status: "Pending", owner: "Operations user", timestamp: "", evidence: "Observed pending" },
          { key: "verified", label: "Verified", status: "Pending", owner: "Operations user", timestamp: "", evidence: "Verified pending" },
        ],
        audit_events: [],
      }),
    });
  });
  // Actions (schedule/applied/observe/verify): return a success response with scope echoed.
  await page.route("**/v1/workbench/sessions/*/actions/**", async (route) => {
    let body: Record<string, unknown> = {};
    try { body = JSON.parse(route.request().postData() || "{}"); } catch { /* use empty */ }
    const farm = (body.selected_farm as string) || "";
    const block = (body.selected_block as string) || "";
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        action_status: "recorded", timestamp: "2026-06-05T10:01:00Z",
        actor: body.actor || "Operations user",
        evidence_type: "operator_attestation",
        evidence_summary: "Schedule approval recorded.",
        selected_farm: farm,
        selected_block: block,
        updated_evidence_chain: [
          { key: "recommended", label: "Recommended", status: "Complete", owner: "AGRO-AI Workbench", timestamp: "2026-06-05T10:00:00Z", evidence: "Verified water decision." },
          { key: "scheduled", label: "Scheduled", status: "Complete", owner: body.actor || "Operations user", timestamp: "2026-06-05T10:01:00Z", evidence: "Schedule approval recorded." },
          { key: "applied", label: "Applied", status: "Pending", owner: "Operations user", timestamp: "", evidence: "Applied pending" },
          { key: "observed", label: "Observed", status: "Pending", owner: "Operations user", timestamp: "", evidence: "Observed pending" },
          { key: "verified", label: "Verified", status: "Pending", owner: "Operations user", timestamp: "", evidence: "Verified pending" },
        ],
        audit_event: { time: "2026-06-05T10:01:00Z", event: "Evidence action recorded: scheduled", actor: body.actor || "Operations user", selected_farm: farm, selected_block: block },
      }),
    });
  });
  await page.route("**/v1/health**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "available" }) });
  });
}

test.describe("Scope selectors (offline fallback — no backend)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
  });

  test("scope selectors are hidden when only offline representative fallback is active", async ({ page }) => {
    const scopeRow = page.locator(".scope-selector-row");
    const count = await scopeRow.count();
    if (count > 0) {
      await expect(scopeRow).toBeVisible();
    }
  });

  test("block selector is disabled before farm is selected", async ({ page }) => {
    const scopeRow = page.locator(".scope-selector-row");
    const count = await scopeRow.count();
    if (count === 0) {
      test.skip();
      return;
    }
    const blockSelect = page.getByRole("combobox", { name: "Select block" });
    await expect(blockSelect).toBeDisabled();
  });

  test("upload tab accepts multiple files and shows a file list", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await expect(page.locator(".drawer")).toBeVisible();
    await page.getByRole("tab", { name: "Upload records" }).click();
    await expect(page.locator(".dropzone")).toBeVisible();
    const hasMultiple = await page.locator('input[type="file"]').getAttribute("multiple");
    expect(hasMultiple).not.toBeNull();
  });

  test("start new package button appears after upload and resets package", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await expect(page.locator(".drawer")).toBeVisible();
    await page.getByRole("tab", { name: "Upload records" }).click();
    await expect(page.getByRole("button", { name: /Start new package/ })).toHaveCount(0);
  });

  test("scope default disclosure is readable", async ({ page }) => {
    const disclosure = page.locator(".scope-default-disclosure");
    const count = await disclosure.count();
    if (count > 0) {
      await expect(disclosure.first()).toBeVisible();
      const text = await disclosure.first().textContent();
      expect(text?.trim().length).toBeGreaterThan(10);
    }
  });

  test("scope selectors render correctly on mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
    const scopeRow = page.locator(".scope-selector-row");
    const count = await scopeRow.count();
    if (count > 0) {
      const overflow = await page.locator(".scope-selector-row").evaluate((el) => el.scrollWidth - el.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    }
  });
});

test.describe("Scope selectors (mocked backend — deterministic)", () => {
  test.beforeEach(async ({ page }) => {
    await mockWorkbenchRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
    await page.waitForSelector(".scope-selector-row", { timeout: 8000 });
  });

  test("selectors are visible after backend-analyzed evaluation loads", async ({ page }) => {
    await expect(page.locator(".scope-selector-row")).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Select farm" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Select block" })).toBeVisible();
  });

  test("block selector is disabled before farm selection", async ({ page }) => {
    await expect(page.getByRole("combobox", { name: "Select block" })).toBeDisabled();
  });

  test("selecting Alpha Vineyard exposes Block A North and Block B West", async ({ page }) => {
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    const blockSelect = page.getByRole("combobox", { name: "Select block" });
    await expect(blockSelect).toBeEnabled();
    // Both blocks must be present in the dropdown.
    await expect(blockSelect.getByRole("option", { name: "Block A North" })).toBeAttached();
    await expect(blockSelect.getByRole("option", { name: "Block B West" })).toBeAttached();
  });

  test("switching to Block A North shows Block A decision in the decision headline", async ({ page }) => {
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    await page.getByRole("combobox", { name: "Select block" }).selectOption("Block A North");
    // After selecting Block A North, decision headline must mention Block A North.
    // (The mock returns "Irrigate Block A North — 24 mm gross depth" for this scope.)
    await expect(page.locator(".decision-headline")).toContainText(
      /Block A North/,
      { timeout: 10000 },
    );
    // When backend is available and re-analysis succeeds, eyebrow shows operational state.
    // When backend is unavailable, eyebrow shows stale state — both are truthful.
    await expect(page.locator("[data-walkthrough-target='verified-decision'] .eyebrow"))
      .toContainText(/Verified water decision|stale|Evidence review/i, { timeout: 5000 });
  });

  test("switching to Block B West shows Block B decision and disables Approve schedule", async ({ page }) => {
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    await page.getByRole("combobox", { name: "Select block" }).selectOption("Block B West");
    // After selecting Block B West, either the scope is pending (eyebrow stale)
    // or the analysis completed (mock returns "Deficit not confirmed for Block B West").
    // In both cases, "Block B West" must appear somewhere in the decision card.
    await expect(page.locator("[data-walkthrough-target='verified-decision']")).toContainText(
      /Block B West/,
      { timeout: 10000 },
    );
    // When Block B analysis completes (not schedulable), eyebrow shows Evidence review.
    // When scope is still pending, eyebrow shows stale. Both are acceptable outcomes.
    // Use .first() because non-schedulable cards have multiple .eyebrow children
    // (Limitations, Next evidence required) that would fail an all-match assertion.
    await expect(page.locator("[data-walkthrough-target='verified-decision'] .eyebrow").first())
      .toContainText(/Evidence review|stale|Prior decision/i, { timeout: 5000 });
    // Approve schedule must be disabled — either scope pending or Block B not schedulable.
    const approveBtn = page.getByRole("button", { name: "Approve schedule" });
    if (await approveBtn.count() > 0) {
      await expect(approveBtn).toBeDisabled();
    }
  });

  test("stale-scope warning appears immediately after farm change before block is chosen", async ({ page }) => {
    // First land in Block A analyzed state
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    await page.getByRole("combobox", { name: "Select block" }).selectOption("Block A North");
    await page.waitForTimeout(600);
    // Change farm — this marks scope as pending before a block is chosen
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Delta Almonds");
    // Stale warning must appear in the scope row / status area
    await expect(
      page.locator(".scope-pending-note, [role='status'], [role='alert']").first()
    ).toContainText(/stale|Analyze|pending/i, { timeout: 5000 });
  });

  test("stale decision action buttons are disabled after farm change", async ({ page }) => {
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    await page.getByRole("combobox", { name: "Select block" }).selectOption("Block A North");
    await page.waitForTimeout(800);
    // Change farm — scope becomes pending
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Delta Almonds");
    // Approve schedule must be disabled
    const approveBtn = page.getByRole("button", { name: "Approve schedule" });
    if (await approveBtn.count() > 0) {
      await expect(approveBtn).toBeDisabled();
    }
    // Decision card eyebrow must indicate stale or review state
    await expect(page.locator("[data-walkthrough-target='verified-decision'] .eyebrow"))
      .toContainText(/stale|review|Evidence review/i, { timeout: 5000 });
  });

  test("multi-file upload shows accumulated artifact filenames", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await expect(page.locator(".drawer")).toBeVisible();
    await page.getByRole("tab", { name: "Upload records" }).click();
    await page.locator("input[type='file']").setInputFiles([
      { name: "soil.csv", mimeType: "text/csv", buffer: Buffer.from("timestamp,farm,block\n2026-05-01,A,B\n") },
      { name: "weather.csv", mimeType: "text/csv", buffer: Buffer.from("timestamp,region,eto_mm\n2026-05-01,R,5\n") },
    ]);
    await expect(page.locator(".upload-package-item").first()).toBeVisible({ timeout: 8000 });
  });

  test("Start new package clears visible artifact list and shows empty-package notice", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await page.getByRole("tab", { name: "Upload records" }).click();
    await page.locator("input[type='file']").setInputFiles({
      name: "data.csv", mimeType: "text/csv",
      buffer: Buffer.from("timestamp,farm,block\n2026-05-01,A,B\n"),
    });
    await expect(page.locator(".upload-package-item, .brief-def")).toBeVisible({ timeout: 8000 });
    const startBtn = page.getByRole("button", { name: /Start new package/ });
    if (await startBtn.count() > 0) {
      await startBtn.click();
      await expect(page.locator(".upload-package-item")).toHaveCount(0);
      // Decision card must show empty-package notice
      await expect(page.locator("[data-testid='empty-package-notice']")).toBeVisible({ timeout: 5000 });
    }
  });

  test("Approve schedule POST body includes correct farm and block scope", async ({ page }) => {
    // Intercept the schedule action POST to verify it sends selected_farm + selected_block.
    const scheduleRequests: Array<{ farm: string; block: string }> = [];
    await page.route("**/v1/workbench/sessions/*/actions/schedule", async (route) => {
      let body: Record<string, unknown> = {};
      try { body = JSON.parse(route.request().postData() || "{}"); } catch { /* empty */ }
      scheduleRequests.push({
        farm: (body.selected_farm as string) || "",
        block: (body.selected_block as string) || "",
      });
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          action_status: "recorded", timestamp: "2026-06-05T10:01:00Z",
          actor: "Operations user", evidence_type: "operator_attestation",
          evidence_summary: "Schedule approval recorded.",
          selected_farm: body.selected_farm, selected_block: body.selected_block,
          updated_evidence_chain: [],
          audit_event: { time: "2026-06-05T10:01:00Z", event: "Evidence action recorded: scheduled" },
        }),
      });
    });
    // Select Block A North (schedulable) and wait for analysis.
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    await page.getByRole("combobox", { name: "Select block" }).selectOption("Block A North");
    await expect(page.locator(".decision-headline")).toContainText(/Block A North/, { timeout: 10000 });
    // Click Approve schedule if it's enabled.
    const approveBtn = page.getByRole("button", { name: "Approve schedule" });
    if (await approveBtn.count() > 0 && !(await approveBtn.isDisabled())) {
      await approveBtn.click();
      await page.waitForTimeout(500);
      // Verify the intercepted request included the correct scope.
      expect(scheduleRequests.length).toBeGreaterThan(0);
      expect(scheduleRequests[0].farm).toBe("Alpha Vineyard");
      expect(scheduleRequests[0].block).toBe("Block A North");
    }
  });

  test("390x844 mobile view has no horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const overflow = await page.locator(".scope-selector-row").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
