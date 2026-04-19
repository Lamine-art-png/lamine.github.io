import { ApiClient } from "./apiClient.js";

const api = new ApiClient();

const state = {
  farms: [],
  zonesByFarm: new Map(),
  selectedFarmId: "",
  selectedZoneId: "",
};

const tabsEl = document.getElementById("tabs");
const titleEl = document.getElementById("page-title");
const authBadgeEl = document.getElementById("auth-badge");
const farmSelectEl = document.getElementById("farm-select");
const zoneSelectEl = document.getElementById("zone-select");

const panels = {
  overview: document.getElementById("overview"),
  recommendations: document.getElementById("recommendations"),
  verification: document.getElementById("verification"),
  reports: document.getElementById("reports"),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setMessage(text = "", type = "") {
  const el = document.getElementById("global-message");
  if (!text) {
    el.className = "message hidden";
    el.textContent = "";
    return;
  }
  el.className = `message ${type}`.trim();
  el.textContent = text;
}

function setAuthBadge({ ok, text }) {
  authBadgeEl.className = `pill ${ok ? "ok" : "error"}`;
  authBadgeEl.textContent = text;
}

function formatDate(value) {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function toArray(payload) {
  return Array.isArray(payload) ? payload : [];
}

function getSelectedZones() {
  return state.zonesByFarm.get(state.selectedFarmId) || [];
}

function selectedZone() {
  return getSelectedZones().find((z) => String(z.id) === String(state.selectedZoneId));
}

function getBlockIdFromZone(zone) {
  if (!zone) return "";
  if (zone.block_id) return String(zone.block_id);

  const providerId = zone.provider_id || zone.id;
  if (!providerId) return "";

  const providerValue = String(providerId);
  return providerValue.startsWith("wc-") ? providerValue : `wc-${providerValue}`;
}

function deriveControllerSource(farm, zones) {
  const sourceSet = new Set();

  if (farm?.provider) sourceSet.add(String(farm.provider));
  zones.forEach((zone) => {
    if (zone.provider) sourceSet.add(String(zone.provider));
    if (zone.source) sourceSet.add(String(zone.source));
  });

  if (!sourceSet.size) {
    return zones.length > 0 ? "WiseConn" : "unknown";
  }

  return Array.from(sourceSet).join(", ");
}

function updateSelectors() {
  farmSelectEl.innerHTML = state.farms
    .map((farm) => `<option value="${escapeHtml(farm.id)}">${escapeHtml(farm.name || farm.id)}</option>`)
    .join("");

  if (!state.selectedFarmId && state.farms.length) {
    state.selectedFarmId = String(state.farms[0].id);
  }

  farmSelectEl.value = state.selectedFarmId;

  const zones = getSelectedZones();
  zoneSelectEl.innerHTML = zones.length
    ? zones
        .map((zone) => `<option value="${escapeHtml(zone.id)}">${escapeHtml(zone.name || zone.id)}</option>`)
        .join("")
    : '<option value="">No zones available</option>';

  if (zones.length && !zones.some((z) => String(z.id) === String(state.selectedZoneId))) {
    state.selectedZoneId = String(zones[0].id);
  }

  zoneSelectEl.value = state.selectedZoneId || "";
}

function renderTable(panel, headers, rows, emptyText) {
  if (!rows.length) {
    panel.innerHTML = `<section class="card empty">${escapeHtml(emptyText)}</section>`;
    return;
  }

  const head = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("");
  const body = rows
    .map(
      (row) =>
        `<tr>${row.map((cell) => `<td>${escapeHtml(cell ?? "n/a")}</td>`).join("")}</tr>`
    )
    .join("\n");

  panel.innerHTML = `<table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function bootstrapFarmsAndZones() {
  const farmsRes = await api.getFarms();
  if (!farmsRes.ok) {
    setMessage(`Unable to load farms (${farmsRes.status || "network"}).`, "error");
    state.farms = [];
    return;
  }

  state.farms = toArray(farmsRes.data);

  await Promise.all(
    state.farms.map(async (farm) => {
      const zonesRes = await api.getZones(farm.id);
      state.zonesByFarm.set(String(farm.id), zonesRes.ok ? toArray(zonesRes.data) : []);
    })
  );

  if (state.farms.length && !state.selectedFarmId) {
    state.selectedFarmId = String(state.farms[0].id);
    const zones = state.zonesByFarm.get(state.selectedFarmId) || [];
    state.selectedZoneId = zones.length ? String(zones[0].id) : "";
  }

  updateSelectors();
}

async function renderOverview() {
  const panel = panels.overview;
  panel.innerHTML = '<section class="card">Loading portfolio overview…</section>';

  const farms = state.farms;
  const allZones = farms.flatMap((farm) => state.zonesByFarm.get(String(farm.id)) || []);
  const sources = farms
    .map((farm) => deriveControllerSource(farm, state.zonesByFarm.get(String(farm.id)) || []))
    .filter(Boolean);
  const portfolioSource = [...new Set(sources)].join(", ") || "unknown";

  const selectedFarm = farms.find((f) => String(f.id) === String(state.selectedFarmId));
  const zones = getSelectedZones();

  const cards = farms
    .slice(0, 8)
    .map((farm) => {
      const farmZones = state.zonesByFarm.get(String(farm.id)) || [];
      return `
      <section class="card">
        <h3>${escapeHtml(farm.name || `Farm ${farm.id}`)}</h3>
        <p class="kv"><span>Farm ID:</span>${escapeHtml(farm.id)}</p>
        <p class="kv"><span>Zones:</span>${escapeHtml(farmZones.length)}</p>
        <p class="kv"><span>Controller source:</span>${escapeHtml(deriveControllerSource(farm, farmZones))}</p>
      </section>`;
    })
    .join("\n");

  panel.innerHTML = `
    <section class="kpi-row">
      <article class="card"><p class="kpi-value">${escapeHtml(farms.length)}</p><p class="kpi-label">Farms</p></article>
      <article class="card"><p class="kpi-value">${escapeHtml(allZones.length)}</p><p class="kpi-label">Zones</p></article>
      <article class="card"><p class="kpi-value">${escapeHtml(portfolioSource)}</p><p class="kpi-label">Controller source</p></article>
      <article class="card"><p class="kpi-value">${escapeHtml(selectedFarm ? zones.length : 0)}</p><p class="kpi-label">Selected farm zones</p></article>
    </section>
    <section class="grid-two">${cards || '<section class="card empty">No farms available yet.</section>'}</section>
  `;
}

async function renderRecommendations() {
  const panel = panels.recommendations;
  panel.innerHTML = '<section class="card">Loading recommendation context…</section>';

  const zone = selectedZone();
  if (!zone) {
    panel.innerHTML = '<section class="card empty">Select a zone/block to view recommendation context.</section>';
    return;
  }

  const blockId = getBlockIdFromZone(zone);
  if (!blockId) {
    panel.innerHTML = '<section class="card empty">No block mapping is available for this selected zone.</section>';
    return;
  }

  const [waterRes, historyRes, decisionsRes] = await Promise.all([
    api.getWaterState(blockId),
    api.getWaterStateHistory(blockId, 8),
    api.getDecisionRuns(blockId, 10),
  ]);

  const latestDecision = decisionsRes.ok ? toArray(decisionsRes.data)[0] : null;
  const states = historyRes.ok ? toArray(historyRes.data?.states) : [];

  panel.innerHTML = `
    <section class="grid-two">
      <article class="card">
        <h3>Latest Recommendation</h3>
        <p class="kv"><span>Time:</span>${escapeHtml(formatDate(latestDecision?.recommended_at))}</p>
        <p class="kv"><span>Duration:</span>${escapeHtml(latestDecision?.planned_duration_min ?? "n/a")} min</p>
        <p class="kv"><span>Volume:</span>${escapeHtml(latestDecision?.planned_volume_m3 ?? "n/a")} m³</p>
        <p class="kv"><span>Status:</span>${escapeHtml(latestDecision?.status || "n/a")}</p>
        <p class="kv"><span>Provider:</span>${escapeHtml(latestDecision?.provider || "WiseConn")}</p>
      </article>
      <article class="card">
        <h3>Water State</h3>
        <p class="kv"><span>Estimated at:</span>${escapeHtml(formatDate(waterRes.data?.estimated_at))}</p>
        <p class="kv"><span>Root zone VWC:</span>${escapeHtml(waterRes.data?.root_zone_vwc ?? "n/a")}</p>
        <p class="kv"><span>Stress risk:</span>${escapeHtml(waterRes.data?.stress_risk ?? "n/a")}</p>
        <p class="kv"><span>Hours to stress:</span>${escapeHtml(waterRes.data?.hours_to_stress ?? "n/a")}</p>
        <p class="kv"><span>Confidence:</span>${escapeHtml(waterRes.data?.confidence ?? "n/a")}</p>
      </article>
    </section>
    <section id="water-state-history"></section>
  `;

  renderTable(
    document.getElementById("water-state-history"),
    ["Estimated", "Root VWC", "Stress", "Refill", "Confidence"],
    states.map((item) => [
      formatDate(item.estimated_at),
      item.root_zone_vwc,
      item.stress_risk,
      item.refill_status,
      item.confidence,
    ]),
    "No water-state history returned yet for this zone/block."
  );

  if (!decisionsRes.ok && !waterRes.ok && !historyRes.ok) {
    setMessage("Recommendation and water-state data are not available for this zone yet.", "warn");
  }
}

async function renderVerification() {
  const panel = panels.verification;
  panel.innerHTML = '<section class="card">Loading verification data…</section>';

  const zone = selectedZone();
  if (!zone) {
    panel.innerHTML = '<section class="card empty">Select a zone/block to view verification.</section>';
    return;
  }

  const blockId = getBlockIdFromZone(zone);
  const [verificationsRes, irrigationsRes] = await Promise.all([
    blockId ? api.getVerifications(blockId, 20) : Promise.resolve({ ok: false, status: 0, data: null }),
    api.getIrrigations(zone.id, 14),
  ]);

  const verificationRows = verificationsRes.ok
    ? toArray(verificationsRes.data).map((item) => [
        item.outcome || "n/a",
        item.verification_status || "n/a",
        item.duration_deviation_pct ?? "n/a",
        item.volume_deviation_pct ?? "n/a",
        formatDate(item.verified_at),
      ])
    : [];

  const irrigationRows = irrigationsRes.ok
    ? toArray(irrigationsRes.data).slice(0, 20).map((item) => [
        formatDate(item.start_time || item.start || item.date),
        item.duration_minutes || item.duration_min || "n/a",
        item.depth_mm || item.depth || "n/a",
        item.volume_m3 || item.volume || "n/a",
      ])
    : [];

  panel.innerHTML = '<section id="verification-table"></section><section id="irrigation-table"></section>';

  renderTable(
    document.getElementById("verification-table"),
    ["Outcome", "Status", "Duration Δ%", "Volume Δ%", "Verified At"],
    verificationRows,
    "No execution verification records available for this zone/block yet."
  );

  renderTable(
    document.getElementById("irrigation-table"),
    ["Irrigation Time", "Duration (min)", "Depth", "Volume (m³)"],
    irrigationRows,
    "No irrigation events were found in the last 14 days for this zone."
  );
}

function defaultDateWindow(days = 30) {
  const now = new Date();
  const from = new Date(now);
  from.setDate(now.getDate() - days);
  const toISO = now.toISOString().slice(0, 10);
  const fromISO = from.toISOString().slice(0, 10);
  return { from: fromISO, to: toISO };
}

async function renderReports() {
  const panel = panels.reports;
  panel.innerHTML = '<section class="card">Loading reports…</section>';

  const zone = selectedZone();
  const blockId = getBlockIdFromZone(zone);
  const { from, to } = defaultDateWindow(30);
  const reportRes = await api.getRoiReport({ from, to, blockId: blockId || "" });

  if (reportRes.ok) {
    const r = reportRes.data;
    panel.innerHTML = `
      <section class="card">
        <h3>ROI Report (${escapeHtml(from)} → ${escapeHtml(to)})</h3>
        <p class="kv"><span>Block:</span>${escapeHtml(r.block_id || "All")}</p>
        <p class="kv"><span>Water saved:</span>${escapeHtml(r.water_saved_m3)} m³</p>
        <p class="kv"><span>Energy saved:</span>${escapeHtml(r.energy_saved_kwh)} kWh</p>
        <p class="kv"><span>Cost saved:</span>$${escapeHtml(r.cost_saved_usd)}</p>
        <p class="kv"><span>Yield delta:</span>${escapeHtml(r.yield_delta_pct)}%</p>
        <p class="kv"><span>Baseline method:</span>${escapeHtml(r.baseline_method)}</p>
      </section>
    `;
    return;
  }

  if (reportRes.status === 404) {
    panel.innerHTML =
      '<section class="card empty">Reports are not yet available in this deployment.</section>';
    return;
  }

  panel.innerHTML = `<section class="card empty">Reports unavailable (${escapeHtml(reportRes.status || "request failed")}).</section>`;
}

async function renderTab(tab) {
  setMessage();
  Object.entries(panels).forEach(([name, panel]) => {
    panel.classList.toggle("hidden", name !== tab);
  });

  titleEl.textContent = tab.charAt(0).toUpperCase() + tab.slice(1);

  if (tab === "overview") await renderOverview();
  if (tab === "recommendations") await renderRecommendations();
  if (tab === "verification") await renderVerification();
  if (tab === "reports") await renderReports();
}

async function initAuthStatus() {
  const authRes = await api.getAuth();
  if (!authRes.ok) {
    setAuthBadge({ ok: false, text: "Connection issue" });
    return;
  }

  setAuthBadge({
    ok: Boolean(authRes.data?.authenticated),
    text: authRes.data?.authenticated ? "Connected" : "Disconnected",
  });
}

farmSelectEl.addEventListener("change", async (event) => {
  state.selectedFarmId = event.target.value;
  const zones = getSelectedZones();
  state.selectedZoneId = zones.length ? String(zones[0].id) : "";
  updateSelectors();

  const activeTab = tabsEl.querySelector(".tab.active")?.dataset.tab || "overview";
  await renderTab(activeTab);
});

zoneSelectEl.addEventListener("change", async (event) => {
  state.selectedZoneId = event.target.value;
  const activeTab = tabsEl.querySelector(".tab.active")?.dataset.tab || "overview";
  await renderTab(activeTab);
});

tabsEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-tab]");
  if (!button) return;

  tabsEl.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab === button);
  });

  await renderTab(button.dataset.tab);
});

async function initializePortal() {
  await initAuthStatus();
  await bootstrapFarmsAndZones();
  await renderTab("overview");
}

initializePortal();
