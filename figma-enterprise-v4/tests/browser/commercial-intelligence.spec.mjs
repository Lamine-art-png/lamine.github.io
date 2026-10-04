import { expect, test } from "@playwright/test";

// Commercial Intelligence on the production bundle with a stubbed backend:
// material changes first, provenance, deterministic what-ifs, decisions,
// plain-language onboarding (no provider identifiers), mobile and RTL layout,
// and locale-correct number formatting.
const APP = process.env.AGROAI_APP_ORIGIN || "http://127.0.0.1:4173";

function jwt() {
  return `qa.${Buffer.from(JSON.stringify({ sub: "ci-user", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url")}.sig`;
}

const POSITION = {
  position_id: "pos-br-soy",
  name: "Soja MT 2027",
  commodity: "soybean",
  season: "2027",
  country_code: "BR",
  reporting_currency: "BRL",
  quantity_unit: "saca_60kg",
  expected_production: "10000.00000000",
  marketable_supply: "10000.00000000",
  contracted_quantity: "2000.00000000",
  uncontracted_quantity: "8000.00000000",
  contracted_percent: "20.0000",
  exposed_percent: "80.0000",
  locked_revenue: "280000.00",
  exposed_revenue: "1017600.00",
  projected_revenue: "1297600.00",
  projected_margin: "297600.00",
  break_even_price: "100.00000000",
  current_realizable_price: "127.20000000",
  over_contracted: false,
  data_complete: true,
  missing_inputs: [],
  warnings: [],
  price_state: "DELAYED",
  fx_state: "NOT_REQUIRED",
  data_health: { status: "healthy", sources: [] },
};

const CHANGE = {
  id: "evt-1",
  position_id: "pos-br-soy",
  position_name: "Soja MT 2027",
  kind: "commercial_change",
  level: "HIGH",
  status: "open",
  reasons: [
    { code: "economic_change", metric: "projected_margin", change: "-115200.00", currency: "BRL", impact_percent_of_revenue: "8.32" },
    { code: "price_change", from: "141.60", to: "127.20", percent: "-10.17", unit: "saca_60kg", currency: "BRL" },
    { code: "exposure", uncontracted_quantity: "8000", unit: "saca_60kg", exposed_revenue: "1017600.00", exposed_percent: "80", currency: "BRL" },
  ],
  impact: { change: "-115200.00", currency: "BRL", direction: "down", impact_percent_of_revenue: "8.32", drivers: [{ driver: "price", contribution: "-115200.00" }] },
  created_at: new Date().toISOString(),
};

async function stub(page, { locale = "en", positions = [POSITION], changes = [CHANGE] } = {}) {
  const calls = { acknowledged: [], compare: [], journal: [], onboarding: [], ask: [] };
  await page.addInitScript(({ token, selected }) => {
    localStorage.setItem("agroai_access_token", token);
    localStorage.setItem("agroai_locale_v1", selected);
    localStorage.setItem("agroai_product_tour_product_tour_v2_ci-user", "done");
  }, { token: jwt(), selected: locale });
  const handler = async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const org = { id: "org-ci", name: "CI Farm", role: "owner", plan: "enterprise", subscription_status: "active" };
    if (path === "/v1/auth/me" || path === "/v1/auth/bootstrap") {
      return json({ user: { id: "ci-user", name: "Owner", email: "owner@example.com", email_verified: true }, current_organization: org, organizations: [org], entitlements: { capabilities: { "market_intelligence.read": true } } });
    }
    if (path === "/v1/orgs") return json({ organizations: [org] });
    if (path === "/v1/workspaces") return json({ workspaces: [] });
    if (path === "/v1/market-intelligence/capabilities") return json({ can_write: true, role: "owner", release_state: "general" });
    if (path === "/v1/market-intelligence/overview") return json({ position_count: positions.length, positions, portfolio_by_reporting_currency: [], attention: [], data_health: { status: "healthy" } });
    if (path === "/v1/market-intelligence/providers") return json({ providers: { conab_precos: { name: "CONAB weekly state agricultural prices", access: "public_no_key", status: "DELAYED" }, cme_futures: { name: "CME Group / CBOT futures", access: "commercial_license_required", status: "NOT_CONFIGURED", configuration_hint: "Requires a CME market-data licence." } } });
    if (path === "/v1/market-intelligence/ask") {
      calls.ask.push(request.postDataJSON());
      return json({ position_id: "pos-1", scenarios: [], scenario_parse: { status: "unsupported_language" }, intelligence: {
        status: "deterministic", summary: "SERVER ENGLISH SUMMARY", response_language: "en", client_render_required: true,
        facts: [{ code: "exposed", params: { percent: "80" } }, { code: "stale", params: { items: [{ evidence: "contract_fx:USD-1", state: "UNAVAILABLE" }] } },
                { code: "source", params: { provider: "conab_precos", source_name: "CONAB weekly state agricultural prices", state: "DELAYED", observed: "2026-09-25" } }] } });
    }
    if (path === "/v1/market-intelligence/home") {
      return json({
        status: changes.length ? "attention" : "steady", generated_at: new Date().toISOString(), material_changes: changes, material_change_count: changes.length,
        portfolio_by_reporting_currency: positions.length ? [{ currency: "BRL", positions: 1, locked_revenue: "280000.00", exposed_revenue: "1017600.00", projected_margin: "297600.00", margin_partial: false }] : [],
        positions, deadlines: [], data_health: { positions_with_stale_or_missing_evidence: [], complete_positions: positions.length, total_positions: positions.length },
      });
    }
    if (path === "/v1/market-intelligence/alerts/evt-1/acknowledge") { calls.acknowledged.push(path); changes.splice(0, changes.length); return json({ id: "evt-1", status: "acknowledged" }); }
    if (path.endsWith("/provenance")) {
      return json({ numbers: { current_realizable_price: { value: "127.20", origin: "governed_shared_evidence", state: "DELAYED" }, fx_rate_to_reporting: { value: null, origin: "not_required_or_missing" } },
        sources: [{ evidence_id: "e1", observation_type: "physical_price", provider: "conab_precos", source_name: "CONAB weekly state agricultural prices", state: "DELAYED", value: "2.12", unit: "kg", currency: "BRL", observed_at: "2026-09-25T12:00:00Z", retrieved_at: "2026-10-03T08:00:00Z", market_name: "MT state average", attribution: "Fonte: Conab" }] });
    }
    if (path === "/v1/market-intelligence/scenarios/compare") {
      calls.compare.push(request.postDataJSON());
      return json({ scenarios: [{ label: "x", status: "ok", result: { ...POSITION, projected_margin: "216192.00", exposed_revenue: "936192.00" }, delta: { projected_margin: "-81408.00", exposed_revenue: "-81408.00" } }] });
    }
    if (path === "/v1/market-intelligence/decision-journal" && request.method() === "POST") { calls.journal.push(request.postDataJSON()); return json({ id: "j1" }, 201); }
    if (path === "/v1/market-intelligence/fields") return json({ fields: [] });
    if (path === "/v1/market-intelligence/onboarding/infer") {
      const body = request.postDataJSON();
      const almonds = /almond/i.test(body.crop);
      const known = ["almonds", "corn"].includes(body.crop);
      return json({ pack_id: almonds ? "us_specialty_crops" : known ? "us_row_crops" : "global_physical", commodity: almonds ? "almonds" : body.crop,
        commodity_recognised: known, local_currency: "USD", reporting_currency: "USD", quantity_unit: almonds ? "pound" : "bushel", market_structure: almonds ? "physical" : "hybrid",
        futures_role: almonds ? "none" : "optional_licensed", warnings: known ? [] : ["crop_not_recognised"],
        evidence_plan: [{ role: "physical_price", provider_id: "usda_mymarketnews", status: "NOT_CONFIGURED" }] });
    }
    if (path === "/v1/market-intelligence/onboarding") { calls.onboarding.push(request.postDataJSON()); return json({ id: "new", status: "created" }, 201); }
    if (request.method() === "GET") return json({ items: [], data: [], results: [], positions: [], scenarios: [], entries: [] });
    return json({ status: "ok" });
  };
  await page.route("https://api.agroai-pilot.com/**", handler);
  await page.route(`${APP}/v1/**`, handler);
  return calls;
}

async function noHorizontalScroll(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("home leads with material changes and explains them with evidence", async ({ page }) => {
  const calls = await stub(page);
  await page.goto(`${APP}/market-intelligence`);
  const home = page.getByTestId("commercial-home");
  await expect(home.getByText("Is anything materially affecting your business?")).toBeVisible({ timeout: 25_000 });
  await expect(home.getByText("Material changes need your attention")).toBeVisible();
  const changes = page.getByTestId("material-changes");
  await expect(changes.getByText("High", { exact: true })).toBeVisible();
  await expect(changes.getByText(/Projected margin changed by -115,200 BRL\. This equals 8\.32% of projected revenue\./)).toBeVisible();
  await expect(changes.getByText(/Realizable price changed by -10\.17%: from 141\.6 to 127\.2 BRL\./)).toBeVisible();
  // Units and money render localized, never as identifiers such as saca_60kg.
  await expect(changes.getByText(/Uncontracted volume: 8,000 60 kg sacks \(80%\)\. Its value at current prices is R\$1,017,600\./)).toBeVisible();
  await expect(page.getByText(/saca_60kg/)).toHaveCount(0);

  await page.getByTestId("position-cards").getByRole("button", { name: "Sources" }).click();
  const sources = page.getByTestId("provenance-sources");
  // Provider names are localized from provider_id, never the API's English name.
  await expect(sources.getByText("Weekly state producer prices from CONAB")).toBeVisible();
  await expect(sources.getByText("CONAB weekly state agricultural prices")).toHaveCount(0);
  await expect(sources.getByText("Fonte: Conab")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  await page.getByTestId("position-cards").getByRole("button", { name: "What if" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByTestId("what-if-result")).toBeVisible();
  expect(calls.compare[0].scenarios[0].price_pct).toBe("-8");
  await expect(page.getByText("Scenarios are deterministic what-ifs, not forecasts.")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  await changes.getByRole("button", { name: "Save decision" }).click();
  await page.getByRole("dialog").locator("textarea").first().fill("Hold the remaining volume until harvest.");
  await page.getByRole("dialog").getByRole("button", { name: "Save decision" }).click();
  await expect(page.getByText("Decision saved with the evidence available today.")).toBeVisible();
  expect(calls.journal[0].assumptions.material_change_id).toBe("evt-1");

  await changes.getByRole("button", { name: "Acknowledge" }).click();
  await expect.poll(() => calls.acknowledged.length).toBe(1);
  await expect(home.getByText("No material changes since the last review.")).toBeVisible();
});

test("onboarding asks plain questions and never asks for provider identifiers", async ({ page }) => {
  const calls = await stub(page, { positions: [], changes: [] });
  await page.goto(`${APP}/market-intelligence`);
  const onboarding = page.getByTestId("commercial-onboarding");
  await expect(onboarding.getByText("Set up Commercial Intelligence")).toBeVisible({ timeout: 25_000 });
  await expect(page.getByText(/report slug|USDA MyMarketNews report/i)).toHaveCount(0);
  // Worldwide: every ISO 3166-1 country and ISO 4217 currency is selectable.
  const country = onboarding.getByLabel("Country");
  expect(await country.locator("option").count()).toBeGreaterThanOrEqual(249);
  for (const code of ["NP", "MN", "FJ", "ZW", "BG", "XK"]) await expect(country.locator(`option[value="${code}"]`)).toHaveCount(1);
  expect(await onboarding.getByLabel("Reporting currency").locator("option").count()).toBeGreaterThanOrEqual(150);
  await expect(onboarding.getByLabel("Reporting currency").locator('option[value="ZWG"]')).toHaveCount(1);
  // Canonical crop selector, with free text for anything else.
  await onboarding.getByLabel("What do you grow?").selectOption("__other__");
  await onboarding.getByLabel("Name of your crop").fill("teff");
  await expect(page.getByTestId("onboarding-inference").getByText("Physical market in any country")).toBeVisible();
  await expect(page.getByTestId("onboarding-inference").getByText("This crop has no governed market source yet. AGRO-AI will use prices you verify.")).toBeVisible();
  await onboarding.getByLabel("What do you grow?").selectOption("almonds");
  const inference = page.getByTestId("onboarding-inference");
  await expect(inference.getByText("United States specialty crops")).toBeVisible();
  await expect(inference.getByText("USDA Market News prices")).toBeVisible();
  await expect(inference.getByText("No futures market is required for this crop.")).toBeVisible();
  await expect(inference.getByText("Not configured")).toBeVisible();
  await onboarding.getByLabel("Expected production").fill("2000000");
  await onboarding.getByRole("button", { name: "Add a sale or contract" }).click();
  await onboarding.getByLabel("Quantity").fill("600000");
  await onboarding.getByLabel("Price per unit").fill("2.31");
  await onboarding.getByRole("button", { name: "Add a sale or contract" }).click();
  await onboarding.getByLabel("Quantity").nth(1).fill("100000");
  await onboarding.getByLabel("Price per unit").nth(1).fill("2.10");
  await onboarding.getByLabel("Currency", { exact: true }).nth(1).selectOption("EUR");
  await onboarding.getByRole("button", { name: "Create commercial position" }).click();
  await expect.poll(() => calls.onboarding.length).toBe(1);
  const body = calls.onboarding[0];
  expect(body.crop).toBe("almonds");
  expect(body.quantity_unit).toBe("pound");
  expect(body.contracts).toEqual([{ quantity: "600000", price: "2.31", currency: "USD" }, { quantity: "100000", price: "2.10", currency: "EUR" }]);
  expect(JSON.stringify(body)).not.toMatch(/slug|usda|report_id|source_overrides/i);
});

for (const scenario of [{ locale: "en", dir: "ltr" }, { locale: "ar", dir: "rtl" }]) {
  test(`mobile commercial home is usable without horizontal scroll (${scenario.locale})`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await stub(page, { locale: scenario.locale });
    await page.goto(`${APP}/market-intelligence`);
    await expect(page.getByTestId("commercial-home")).toBeVisible({ timeout: 25_000 });
    await expect(page.locator("html")).toHaveAttribute("dir", scenario.dir);
    await noHorizontalScroll(page);
    await page.getByTestId("position-cards").getByRole("button").first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const box = await dialog.locator("> div").boundingBox();
    expect(box.width).toBeLessThanOrEqual(390);
    await noHorizontalScroll(page);
  });
}

test("numbers follow the customer's locale formatting", async ({ page }) => {
  await stub(page, { locale: "pt-BR" });
  await page.goto(`${APP}/market-intelligence`);
  const summary = page.getByTestId("portfolio-summary");
  await expect(summary).toBeVisible({ timeout: 25_000 });
  await expect(summary.getByText(/R\$\s?280\.000/)).toBeVisible();
});

test("deterministic answers render from facts in the viewer's language, never the server's English", async ({ page }) => {
  const calls = await stub(page);
  await page.goto(`${APP}/market-intelligence`);
  await expect(page.getByTestId("commercial-home")).toBeVisible({ timeout: 25_000 });
  const askBox = page.getByRole("textbox", { name: "Ask AGRO-AI" });
  await askBox.fill("Que se passe-t-il si le prix baisse de 8 % ?");
  await askBox.press("Enter");
  const answer = page.getByTestId("commercial-answer");
  await expect(answer).toContainText("Not yet sold or contracted: 80% of expected production.");
  await expect(answer).toContainText("Evidence needing attention: Contract USD-1 exchange rate: Unavailable.");
  await expect(answer).toContainText("Current price source: Weekly state producer prices from CONAB, Delayed, observed 2026-09-25.");
  await expect(answer).toContainText("Free-text what-if questions are understood in English, Portuguese, Spanish and French.");
  await expect(answer).not.toContainText("SERVER ENGLISH SUMMARY");
  expect(calls.ask.length).toBe(1);
});
