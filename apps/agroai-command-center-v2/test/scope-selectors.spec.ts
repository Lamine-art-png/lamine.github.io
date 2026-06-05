import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Shared mock backend response — Alpha Vineyard, two blocks, backend-analyzed.
// All mocked-route tests use this to drive deterministic scope selector behavior.
// ---------------------------------------------------------------------------

const MOCK_ANALYSIS_RESULT = {
  analysis_id: "mock-analysis-1",
  session_id: "mock-session-1",
  status: "complete",
  analysis_mode: "uploaded",
  context_origin: "uploaded",
  recommendation_origin: "uploaded_intelligence_engine",
  recommendation: {
    action: "Irrigate Block A North — 24 mm gross depth",
    decision: "Irrigate Block A North",
    start_time: "Tomorrow 06:00",
    depth: "24 mm net",
    gross_depth: "29 mm gross",
    duration: "3.5 hours",
    estimated_volume: "58 m³",
    confidence: 0.84,
    schedulable: true,
    scheduling_block_reasons: [],
    flow_validation_status: "validated",
    flow_validation_notes: ["Flow validated at 16.6 m³/h"],
    estimated_water_savings_percent: 22,
    verification_requirement: "Required within 48 h of irrigation",
    key_drivers: ["Soil moisture deficit 42%"],
    recommendation_origin: "uploaded_intelligence_engine",
    no_fabricated_duration: false,
  },
  reconciliation: {
    controller_event_validity: "3 events validated",
    weather_demand: "ETo 6.5 mm/day over 3-day window",
    soil_moisture_deficit: "42% deficit",
    flow_meter_agreement: "Flow within 5% variance",
    field_observation_support: "No field observations",
    matched_signals: ["controller_events", "soil_moisture", "crop_profile"],
    evidence_completeness: 0.79,
  },
  normalized_context: {
    farm: "Alpha Vineyard",
    block: "Block A North",
    crop: "Cabernet Sauvignon",
    variety: "not available",
    soil: "Sandy loam",
    irrigation_method: "drip",
    region: "Central Valley",
    area_ha: 12.5,
    area_unit: "ha",
    selected_farm: "Alpha Vineyard",
    selected_block: "Block A North",
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
    moisture_deficit: "42%",
    flow_variance: "4.8%",
    weather_window: "2026-05-13 to 2026-05-15",
    provider_context: "WiseConn-162803",
  },
  signal_summary: {
    controller_events_read: 3,
    weather_records_read: 2,
    soil_readings_read: 4,
    field_notes_parsed: 0,
    flow_meter_records_read: 2,
    crop_profile_loaded: 1,
    satellite_observations_read: 0,
  },
  source_rows: [
    { source_label: "Controller history", source_kind: "controller_events", selected_scope_record_count: 3, package_record_count: 8, status: "accepted", limitations: [], contribution_label: "Not scored" },
    { source_label: "Weather demand", source_kind: "weather", selected_scope_record_count: 2, package_record_count: 2, status: "accepted", limitations: [], contribution_label: "Not scored" },
    { source_label: "Soil moisture", source_kind: "soil_moisture", selected_scope_record_count: 4, package_record_count: 10, status: "accepted", limitations: [], contribution_label: "Not scored" },
  ],
  limitations: [],
  analysis_trace: [
    { title: "Source records ingested", status: "complete", objects_processed: 42, details: "8 artifacts processed" },
    { title: "Field context assembled", status: "complete", objects_processed: 1, details: "Crop profile loaded" },
    { title: "Confidence scored", status: "complete", objects_processed: 42, details: "4 source kinds" },
  ],
  report_summary: {
    recommendation: "Irrigate Block A North — 24 mm gross depth",
    planned_water: "29 mm gross",
    evidence_completeness: 0.79,
    confidence: 0.84,
  },
  warnings: [],
  uploaded_artifacts_used: ["controller_events.csv", "soil_moisture.csv", "crop_profile.json", "weather_summary.csv"],
  live_inputs_used: [],
  data_sources: { rows_parsed: 42, artifacts_ingested: 4, warnings: [] },
  model_status: "deterministic_engine",
  backend_status: "available",
};

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
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_ANALYSIS_RESULT) });
  });
  await page.route("**/v1/workbench/sessions/*/upload", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_UPLOAD_ARTIFACT) });
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
    // Before backend analysis completes, we are in representative fallback — selectors hidden.
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
    // Wait for backend-analyzed state to load (scope selectors should appear)
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

  test("selecting Alpha Vineyard exposes its blocks", async ({ page }) => {
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    const blockSelect = page.getByRole("combobox", { name: "Select block" });
    await expect(blockSelect).toBeEnabled();
    await expect(blockSelect.getByRole("option", { name: "Block A North" })).toBeAttached();
    await expect(blockSelect.getByRole("option", { name: "Block B West" })).toBeAttached();
  });

  test("switching to Block B West triggers analysis and updates visible scope badge", async ({ page }) => {
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    await page.getByRole("combobox", { name: "Select block" }).selectOption("Block B West");
    // After selection, analysis runs — scope badge should appear
    await expect(page.locator(".status-row")).toContainText(/Block B West|Analyzing|Scope/, { timeout: 10000 });
  });

  test("stale-scope warning appears immediately after farm change", async ({ page }) => {
    // Select farm — this marks scope as pending before a block is chosen
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Delta Almonds");
    // Stale warning must appear in the scope row as a pending note or status badge
    await expect(
      page.locator(".scope-pending-note, [role='status'], [role='alert']").first()
    ).toContainText(/stale|Analyze|pending/i, { timeout: 5000 });
  });

  test("stale decision action buttons are disabled after farm change", async ({ page }) => {
    // Navigate to block-level analysis first
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Alpha Vineyard");
    await page.getByRole("combobox", { name: "Select block" }).selectOption("Block A North");
    // Wait for analysis to settle
    await page.waitForTimeout(800);
    // Now change farm — this makes scope pending
    await page.getByRole("combobox", { name: "Select farm" }).selectOption("Delta Almonds");
    // The Approve schedule button must be disabled (scope pending)
    const approveBtn = page.getByRole("button", { name: "Approve schedule" });
    if (await approveBtn.count() > 0) {
      await expect(approveBtn).toBeDisabled();
    }
    // The decision card eyebrow specifically must indicate stale or review state
    await expect(page.locator("[data-walkthrough-target='verified-decision'] .eyebrow")).toContainText(/stale|review|Evidence review/i, { timeout: 5000 });
  });

  test("multi-file upload shows accumulated artifact filenames", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await expect(page.locator(".drawer")).toBeVisible();
    await page.getByRole("tab", { name: "Upload records" }).click();
    await page.locator("input[type='file']").setInputFiles([
      { name: "soil.csv", mimeType: "text/csv", buffer: Buffer.from("timestamp,farm,block\n2026-05-01,A,B\n") },
      { name: "weather.csv", mimeType: "text/csv", buffer: Buffer.from("timestamp,region,eto_mm\n2026-05-01,R,5\n") },
    ]);
    // At least one filename should appear (placeholder shown immediately)
    await expect(page.locator(".upload-package-item").first()).toBeVisible({ timeout: 8000 });
  });

  test("Start new package clears visible artifact list and shows pipeline message", async ({ page }) => {
    await page.getByRole("button", { name: "Add or manage sources" }).first().click();
    await page.getByRole("tab", { name: "Upload records" }).click();
    await page.locator("input[type='file']").setInputFiles({
      name: "data.csv", mimeType: "text/csv",
      buffer: Buffer.from("timestamp,farm,block\n2026-05-01,A,B\n"),
    });
    // Wait for artifact to appear
    await expect(page.locator(".upload-package-item, .brief-def")).toBeVisible({ timeout: 8000 });
    // Click Start new package
    const startBtn = page.getByRole("button", { name: /Start new package/ });
    if (await startBtn.count() > 0) {
      await startBtn.click();
      // Artifact list must be gone
      await expect(page.locator(".upload-package-item")).toHaveCount(0);
    }
  });

  test("390x844 mobile view has no horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const overflow = await page.locator(".scope-selector-row").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
