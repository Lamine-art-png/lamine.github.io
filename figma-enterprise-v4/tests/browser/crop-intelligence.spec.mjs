import { expect, test } from "@playwright/test";

// Crop Intelligence on the production bundle with a stubbed backend (clearly
// synthetic records): navigation, overview, crop health with a link back to
// Field Intelligence, the three calculators with exact request contracts, the
// reviewed hand-off to Market Intelligence (never applied silently), plan
// locks, empty and error states, mobile layout, and a translated locale.
test.describe.configure({ timeout: 90_000 });

const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";
const API_ORIGIN = "https://api.agroai-pilot.com";

function jwt() {
  return `qa.${Buffer.from(JSON.stringify({ sub: "crop-user", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url")}.sig`;
}

const NOW = new Date().toISOString();
const OVERVIEW = {
  status: "ok", overview_version: "crop-overview/1", generated_at: NOW, window_truncated: false,
  note: "Each field shows its newest records only; fields are not compared with each other.",
  totals: { fields: 2, fields_needing_attention: 1, supported_crops: ["almond", "corn"], observations_considered: 5, unassigned_observations: 1 },
  fields: [
    {
      field_id: "field-synthetic-north", field_name: "Synthetic North Orchard", crop: "Almonds", observations: 3, blocks: 2,
      open_reviews: 1, pending_processing: 0, failed_processing: 0, future_dated_excluded: 0,
      latest_record: { observation_id: "obs-syn-2", observed_at: NOW, freshness: "fresh" },
      latest_assessment: { observation_id: "obs-syn-2", observed_at: NOW, freshness: "fresh", severity: "high", status: "needs_review", block_name: "B2", method: "visual", summary: "SYNTHETIC: leaf spotting on west rows", crop_condition: "stressed", review_required: true },
      crop_profile: { crop_id: "almond", display_name: "Almond", validation_status: "unvalidated", benchmark_only: false, has_maturity_stages: true, has_degree_day_method: false },
      attention: ["high_severity", "needs_review"],
    },
    {
      field_id: "field-synthetic-south", field_name: "Synthetic South Corn", crop: "Corn", observations: 2, blocks: 1,
      open_reviews: 0, pending_processing: 0, failed_processing: 0, future_dated_excluded: 0,
      latest_record: { observation_id: "obs-syn-3", observed_at: "2026-01-01T00:00:00Z", freshness: "stale" },
      latest_assessment: { observation_id: "obs-syn-3", observed_at: "2026-01-01T00:00:00Z", freshness: "stale", severity: "low", status: "completed", block_name: null, method: "report", summary: "SYNTHETIC: even stand", crop_condition: null, review_required: false },
      crop_profile: { crop_id: "corn", display_name: "Corn (maize)", validation_status: "unvalidated", benchmark_only: false, has_maturity_stages: true, has_degree_day_method: true },
      attention: ["stale_evidence"],
    },
  ],
};

const CONDITION = {
  status: "ok", summary_status: "ok", observations_considered: 3, total_observations: 3,
  latest: { observation_id: "obs-syn-2", observed_at: NOW, freshness: "fresh", block_name: "B2", method: "visual", event_type: "observation", severity: "high", status: "needs_review", summary: "SYNTHETIC: leaf spotting on west rows", review_required: true,
    visual: { analysis_state: "structured", crop_condition: "stressed", confidence: 0.62, media_analyzed: 2 }, detections: [] },
  comparison: { basis: "same_block_same_method", gap_hours: 26.5, spatial_coverage: "not_established" },
  changes: [
    { kind: "severity_differs", from: "low", to: "high", trend: false, reason: "spatial_coverage_not_established" },
    { kind: "issue_seen_only_in_latest", issues: ["leaf spotting"], trend: false },
  ],
  field_snapshot: { blocks: [{ block_key: "name:b2", block_name: "B2", observation_id: "obs-syn-2", observed_at: NOW, severity: "high", method: "visual", status: "needs_review" }] },
  timeline: [{ observation_id: "obs-syn-2", observed_at: NOW, block_key: "name:b2", method: "visual", event_type: "observation", severity: "high", status: "needs_review" }],
  open_reviews: 1, pending_processing: 0, records_without_evidence: 0,
};

const PROFILES = { status: "ok", profiles: [
  { crop_id: "corn", display_name: "Corn (maize)", detection_labels: [], maturity_scale: "leaf-collar V/R staging", maturity_stages: ["VE", "V(n)", "VT", "R1", "R2", "R3", "R4", "R5", "R6"], degree_day_method: { method: "modified_average_86_50", base_c: 10, upper_cutoff_c: 30, source: "Conventional 86/50 method" }, validation_status: "unvalidated", benchmark_only: false, notes: [] },
  { crop_id: "almond", display_name: "Almond", detection_labels: [], maturity_scale: "visible hull split", maturity_stages: ["hull_intact", "hull_split", "hull_open_dry"], degree_day_method: null, validation_status: "unvalidated", benchmark_only: false, notes: [] },
] };

const POSITION = { position_id: "pos-synthetic", name: "Synthetic Almond 2026", commodity: "almonds", season: "2026", country_code: "US", reporting_currency: "USD", quantity_unit: "pound" };

async function stub(page, { locale = "en", capabilities = {}, overview = OVERVIEW, productionStatus = 200, canWrite = true } = {}) {
  const calls = { production: [], harvest: [], maturity: [], yieldEstimates: [], positionWrites: [], condition: [] };
  await page.addInitScript(({ token, selected }) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", selected);
    localStorage.setItem("agroai_product_tour_product_tour_v2_crop-user", "done");
  }, { token: jwt(), selected: locale });
  const handler = async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const org = { id: "org-synthetic", name: "Synthetic Farm", role: "owner", plan: "professional", subscription_status: "active" };
    if (path === "/v1/auth/me" || path === "/v1/auth/bootstrap") {
      return json({ user: { id: "crop-user", name: "Synthetic Owner", email: "owner@example.com", email_verified: true }, current_organization: org, organizations: [org], entitlements: { capabilities } });
    }
    if (path === "/v1/orgs") return json({ organizations: [org] });
    if (path === "/v1/workspaces") return json({ workspaces: [{ id: "ws-synthetic", name: "Synthetic Workspace", organization_id: "org-synthetic", status: "active" }] });
    if (path === "/v1/field-intelligence/crop-intelligence/overview") return json(overview);
    if (path === "/v1/field-intelligence/crop-profiles") return json(PROFILES);
    if (path.startsWith("/v1/field-intelligence/fields/") && path.endsWith("/crop-condition")) { calls.condition.push(path); return json(CONDITION); }
    if (path === "/v1/field-intelligence/observations/obs-syn-2") {
      return json({ status: "ok", observation: { id: "obs-syn-2", status: "needs_review", summary: "SYNTHETIC: leaf spotting on west rows", field_name: "Synthetic North Orchard", block_name: "B2", event_type: "observation", severity: "high", occurred_at: NOW, structured: {}, assets: [], audit_history: [], task_ids: [] } });
    }
    if (path === "/v1/field-intelligence/observations") return json({ observations: [] });
    if (path === "/v1/field-intelligence/crop-intelligence/production-estimate") {
      calls.production.push(request.postDataJSON());
      if (productionStatus !== 200) return json({ detail: { code: "upgrade_required", message: "Upgrade required" } }, productionStatus);
      return json({
        status: "estimated", estimation_version: "crop-estimation/1", unit: "tree", object_label: "nut", design: "simple_random", count_source: "manual_count",
        sampled_units: 5, population_units: 100, directly_counted_objects: 50, interval_reliability: "design_based",
        visible_density_per_unit: { value: 10, standard_error: 0.7, interval_95: [8.1, 11.9] },
        extrapolated_visible_objects: { value: 1000, interval_95: [810, 1190] },
        estimated_total_objects: { value: 1250, interval_95: [990, 1510] },
        expected_production_kg: { value: 187.5, interval_95: [140.1, 234.9], relative_standard_error: 0.12 },
        expected_production_kg_per_hectare: "375.00", estimate_id: "crop-est-synthetic",
        market_yield_proposal: { yield_per_area: "375.00", quantity_unit: "kg", area_unit: "hectare", source: "crop_intelligence", apply_to_production: false, note: "Crop Intelligence estimate crop-est-synthetic (simple_random, n=5, manual_count)" },
      });
    }
    if (path === "/v1/field-intelligence/crop-intelligence/harvest-window") {
      calls.harvest.push(request.postDataJSON());
      return json({ status: "projected", crop_id: "corn", accumulated_gdd: 512.3, progress_to_target_low: 0.512, analog_years_used: 5, analog_years_rejected: [{ year: 2018, reasons: ["weather_series_missing_days:3"] }], analog_years_unusable: [],
        window: { earliest: "2026-07-09", latest: "2026-07-29", median_entry: "2026-07-14", median_exit: "2026-07-24", interval: "x" }, reasons: [],
        suggested_actions: [{ action_code: "verify_maturity_by_sampling", due_by: "2026-07-02", requires_approval: true, creates_task: false }] });
    }
    if (path === "/v1/field-intelligence/crop-intelligence/maturity-stages") {
      calls.maturity.push(request.postDataJSON());
      return json({ status: "estimated", crop_id: "almond", sampled_units: 5, objects_observed: 100, scope: "block_estimate",
        stage_shares: { hull_intact: { share: 0.4, interval_95: [0.25, 0.57] }, hull_split: { share: 0.5, interval_95: [0.34, 0.66] }, hull_open_dry: { share: 0.1, interval_95: [0.03, 0.27] } },
        readiness: { ready_stages: ["hull_split", "hull_open_dry"], threshold_share: 0.9, threshold_source: "SYNTHETIC handler guide", observed_share: 0.6, interval_95: [0.43, 0.75], status: "not_ready" } });
    }
    if (path === "/v1/market-intelligence/capabilities") return json({ can_write: canWrite, role: canWrite ? "owner" : "viewer", release_state: "general" });
    if (path === "/v1/market-intelligence/overview") return json({ position_count: 1, positions: [POSITION], portfolio_by_reporting_currency: [], attention: [], data_health: { status: "healthy" } });
    if (path === "/v1/market-intelligence/providers") return json({ providers: {} });
    if (path === "/v1/market-intelligence/home") return json({ status: "steady", generated_at: NOW, material_changes: [], material_change_count: 0, portfolio_by_reporting_currency: [], positions: [POSITION], deadlines: [], data_health: { positions_with_stale_or_missing_evidence: [], complete_positions: 1, total_positions: 1 } });
    if (path === "/v1/market-intelligence/positions/pos-synthetic/yield-estimates") {
      calls.yieldEstimates.push(request.postDataJSON());
      return json({ position_id: "pos-synthetic", evidence_id: "ev-1", yield_per_hectare: "375.0000", linked_area_hectares: "0", fields: [], applied_to_expected_production: false, previous_expected_production: "1000", expected_production: "1000", materiality: null, reason: "not_requested" }, 201);
    }
    if (path.startsWith("/v1/market-intelligence/positions/") && ["PATCH", "PUT", "POST"].includes(method)) { calls.positionWrites.push(`${method} ${path}`); return json({ status: "ok" }); }
    if (path === "/v1/market-intelligence/refresh") return json({ status: "ok" });
    if (method === "GET") return json({ items: [], data: [], results: [], status: "ok" });
    return json({ status: "ok" });
  };
  await page.route(`${API_ORIGIN}/**`, handler);
  await page.route(`${APP}/v1/**`, handler);
  return calls;
}

async function noHorizontalOverflow(page) {
  return page.evaluate(() => {
    const main = document.querySelector("[data-portal-content]");
    return !main || main.scrollWidth <= main.clientWidth + 1;
  });
}

for (const viewport of [{ name: "desktop", width: 1400, height: 900 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`Crop Intelligence is reachable from navigation and renders every workspace (${viewport.name})`, async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await browser.newContext({ viewport, locale: "en-US" });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    await stub(page);
    await page.goto(`${APP}/field-intelligence`, { waitUntil: "domcontentloaded" });
    if (viewport.name === "mobile") await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("link", { name: "Crop Intelligence" }).first().click();
    await expect(page).toHaveURL(/\/crop-intelligence/);
    await expect(page.getByRole("heading", { level: 1, name: "Crop Intelligence" })).toBeVisible();

    // Overview: synthetic fields, attention first, no cross-field trend.
    await expect(page.getByText("Synthetic North Orchard")).toBeVisible();
    await expect(page.getByText("Waiting for review").first()).toBeVisible();
    await expect(page.getByText("Evidence older than 14 days")).toBeVisible();
    expect(await noHorizontalOverflow(page), "overview fits the viewport").toBe(true);
    for (const tab of ["Crop health", "Production", "Harvest window", "Maturity", "Overview"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
      expect(await noHorizontalOverflow(page), `${tab} fits the viewport`).toBe(true);
    }
    await expect(page.locator("body")).not.toContainText("literal.");
    expect(errors, `${viewport.name} uncaught errors`).toEqual([]);
    await context.close();
  });
}

test("crop health explains comparable scope and links back to Field Intelligence evidence", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const calls = await stub(page);
  await page.goto(`${APP}/crop-intelligence`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /View crop health/ }).first().click();
  await expect(page).toHaveURL(/tab=health/);
  await expect(page).toHaveURL(/field=field-synthetic-north/);
  await expect(page.getByText("SYNTHETIC: leaf spotting on west rows").first()).toBeVisible();
  await expect(page.getByText("Confidence is reported by the model and is not calibrated.")).toBeVisible();
  await expect(page.getByText("Not a trend: the records may cover different parts of the block.").first()).toBeVisible();
  await expect(page.getByText("A person must confirm this before acting on it.")).toBeVisible();
  expect(calls.condition).toEqual(["/v1/field-intelligence/fields/field-synthetic-north/crop-condition"]);
  await page.getByRole("link", { name: "Open in Field Intelligence" }).click();
  await expect(page).toHaveURL(/\/field-intelligence\?observation=obs-syn-2/);
  await expect(page.getByText("SYNTHETIC: leaf spotting on west rows").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("production estimate sends a manual probability sample and hands a reviewed proposal to Market Intelligence without applying it", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const calls = await stub(page);
  await page.goto(`${APP}/crop-intelligence?tab=production`, { waitUntil: "domcontentloaded" });
  await page.getByLabel(/What you counted/).fill("nut");
  await page.getByLabel(/Sample unit/).fill("tree");
  await page.getByLabel(/Units in the block/).fill("100");
  await page.getByLabel(/Count for each sampled unit/).fill("10, 12, 8, 11, 9");
  await page.getByLabel("Share of objects visible (0–1)").fill("0.8");
  await page.locator("#prod-visibleShare-se").fill("0.04");
  await page.getByLabel("Average weight per object (kg)").fill("0.15");
  await page.locator("#prod-unitWeight-se").fill("0.0075");
  await page.getByLabel(/Block area/).fill("0.5");
  await page.getByRole("button", { name: "Calculate estimate" }).click();
  await expect(page.getByText("Estimate ready")).toBeVisible();
  expect(calls.production).toHaveLength(1);
  expect(calls.production[0]).toMatchObject({
    unit: "tree", object_label: "nut", design: "simple_random", population_units: 100, count_source: "manual_count",
    sample_counts: [10, 12, 8, 11, 9], detection_rate: { value: 0.8, standard_error: 0.04 }, unit_weight_kg: { value: 0.15, standard_error: 0.0075 },
    area_hectares: "0.5", include_market_proposal: true,
  });
  await expect(page.getByText("This is an agricultural estimate, not commercially verified volume.")).toBeVisible();
  await page.getByRole("button", { name: "Review in Market Intelligence" }).click();
  await expect(page).toHaveURL(/\/market-intelligence/);
  const review = page.locator("[data-crop-yield-proposal]");
  await expect(review).toBeVisible();
  await expect(review.getByRole("checkbox")).not.toBeChecked();
  await review.getByRole("button", { name: "Record reviewed estimate" }).click();
  await expect(page.getByText("Recorded as evidence. Expected production was not changed.")).toBeVisible();
  expect(calls.yieldEstimates).toHaveLength(1);
  expect(calls.yieldEstimates[0]).toMatchObject({ yield_per_area: "375.00", quantity_unit: "kg", area_unit: "hectare", source: "crop_intelligence", apply_to_production: false });
  expect(calls.positionWrites, "no other commercial write").toEqual([]);
  await expect(page.locator("[data-crop-yield-proposal]")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a read-only Market Intelligence member can review but not record a crop proposal", async ({ page }) => {
  const calls = await stub(page, { canWrite: false });
  await page.goto(`${APP}/crop-intelligence?tab=production`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => sessionStorage.setItem("agroai_crop_yield_proposal_v1", JSON.stringify({ version: 1, created_at: new Date().toISOString(), estimate_id: "crop-est-x", yield_per_area: "375.00", quantity_unit: "kg", area_unit: "hectare", note: "x", basis: "total", interval: [1, 2], design: "simple_random", sampled_units: 5, object_label: "nut" })));
  await page.goto(`${APP}/market-intelligence`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("You can review this proposal, but recording it needs write access.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Record reviewed estimate" })).toHaveCount(0);
  expect(calls.yieldEstimates).toEqual([]);
});

test("harvest window sends only the season window and complete analog seasons, and shows limitations", async ({ page }) => {
  const calls = await stub(page);
  await page.goto(`${APP}/crop-intelligence?tab=harvest`, { waitUntil: "domcontentloaded" });
  await page.getByLabel(/^Crop/).selectOption("corn");
  await page.getByLabel(/Season start/).fill("2026-04-01");
  await page.getByLabel(/Assessment date/).fill("2026-04-10");
  await page.getByLabel(/lower degree days/).fill("1000");
  await page.getByLabel(/upper degree days/).fill("1200");
  await page.getByLabel(/Target source/).fill("SYNTHETIC hybrid sheet");
  const observed = ["date,tmax,tmin", "2026-03-31,20,5", ...Array.from({ length: 10 }, (_, i) => `2026-04-${String(i + 1).padStart(2, "0")},28,12`), "garbage"].join("\n");
  await page.locator("#hw-observed").fill(observed);
  await expect(page.getByText("11 days read")).toBeVisible();
  await expect(page.getByText("2 lines could not be read")).toBeVisible();
  const analog = [];
  for (const year of [2021, 2022, 2023, 2024, 2025]) for (let day = 0; day < 5; day += 1) analog.push(`${year}-04-${String(11 + day).padStart(2, "0")},27,12`);
  await page.locator("#hw-analog").fill(analog.join("\n"));
  await expect(page.getByText("5 earlier seasons read")).toBeVisible();
  await page.getByLabel(/Weather source \(station/).fill("SYNTHETIC station");
  await page.getByLabel(/Earlier seasons source/).fill("SYNTHETIC station history");
  await page.getByRole("button", { name: "Calculate harvest window" }).click();
  await expect(page.getByText("Projected harvest window")).toBeVisible();
  await expect(page.getByText("Limitations")).toBeVisible();
  await expect(page.getByText("Confirm maturity by sampling in the field", { exact: false })).toBeVisible();
  const body = calls.harvest[0];
  expect(body.crop).toBe("corn");
  expect(body.observed).toHaveLength(10); // the day before the season start is not sent
  expect(Object.keys(body.analog_years)).toEqual(["2021", "2022", "2023", "2024", "2025"]);
  expect(body.target).toMatchObject({ low_gdd: 1000, high_gdd: 1200, source: "SYNTHETIC hybrid sheet", source_type: "supplier_published" });
  expect(body.degree_day_method).toBeUndefined(); // the crop profile's conventional method applies
});

test("maturity stages report shares with intervals and a qualified readiness call", async ({ page }) => {
  const calls = await stub(page);
  await page.goto(`${APP}/crop-intelligence?tab=maturity`, { waitUntil: "domcontentloaded" });
  await page.getByLabel(/^Crop/).selectOption("almond");
  for (let row = 1; row <= 5; row += 1) {
    await page.getByLabel(`${row} Hull intact`).fill("8");
    await page.getByLabel(`${row} Hull split`).fill("10");
    await page.getByLabel(`${row} Hull open and dry`).fill("2");
  }
  await page.getByLabel("Hull split", { exact: true }).check();
  await page.getByLabel("Threshold (%)").fill("90");
  await page.getByLabel("Threshold source").fill("SYNTHETIC handler guide");
  await page.getByRole("button", { name: "Calculate stage shares" }).click();
  await expect(page.getByText("Not ready: the whole interval is below the threshold")).toBeVisible();
  await expect(page.getByText("Estimate for the whole block")).toBeVisible();
  expect(calls.maturity[0]).toMatchObject({ crop: "almond", design: "simple_random", count_source: "manual_count", readiness: { ready_stages: ["hull_split"], threshold_share: 0.9, source: "SYNTHETIC handler guide" } });
  expect(calls.maturity[0].samples).toHaveLength(5);
});

test("calculators stay locked without the paid capability and on a server 402", async ({ page }) => {
  const calls = await stub(page, { capabilities: { "intelligence.deep_analysis": "locked" } });
  await page.goto(`${APP}/crop-intelligence?tab=production`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Crop calculators are included in the Professional plan and above.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Calculate estimate" })).toHaveCount(0);
  expect(calls.production).toEqual([]);

  const page2 = await page.context().newPage();
  const calls2 = await stub(page2, { productionStatus: 402 });
  await page2.goto(`${APP}/crop-intelligence?tab=production`, { waitUntil: "domcontentloaded" });
  await page2.getByLabel(/What you counted/).fill("nut");
  await page2.getByLabel(/Sample unit/).fill("tree");
  await page2.getByLabel(/Units in the block/).fill("100");
  await page2.getByLabel(/Count for each sampled unit/).fill("1,2,3,4,5");
  await page2.getByRole("button", { name: "Calculate estimate" }).click();
  await expect(page2.getByText("Crop calculators are included in the Professional plan and above.")).toBeVisible();
  expect(calls2.production).toHaveLength(1);
});

test("an empty workspace explains how to start, and missing calibration is explained rather than estimated", async ({ page }) => {
  await stub(page, { overview: { ...OVERVIEW, fields: [], totals: { ...OVERVIEW.totals, fields: 0, fields_needing_attention: 0, supported_crops: [] } } });
  await page.goto(`${APP}/crop-intelligence`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("No field records in this workspace yet")).toBeVisible();
  await page.getByRole("tab", { name: "Production" }).click();
  await page.getByLabel(/What you counted/).fill("nut");
  await page.getByLabel(/Sample unit/).fill("tree");
  await page.getByLabel("Share of objects visible (0–1)").fill("0.8");
  await page.getByRole("button", { name: "Calculate estimate" }).click();
  await expect(page.getByText("Enter how many units are in the block; it must be at least the number sampled.")).toBeVisible();
  await expect(page.getByText("Check the calibration: shares must be between 0 and 1 and weights above 0.")).toBeVisible();
});

test("Crop Intelligence is localized in a bundled locale with no English or key leakage in its navigation", async ({ page }) => {
  await stub(page, { locale: "pt-BR" });
  await page.goto(`${APP}/crop-intelligence`, { waitUntil: "domcontentloaded" });
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toBeVisible();
  await expect.poll(async () => (await heading.innerText()).trim(), { timeout: 20_000 }).not.toBe("Crop Intelligence");
  await expect(page.getByRole("tab").first()).not.toHaveText("Overview");
  await expect(page.locator("body")).not.toContainText("literal.");
});
