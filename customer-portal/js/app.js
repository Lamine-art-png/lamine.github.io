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
const apiBaseEl = document.getElementById("api-base");
const apiBaseInputEl = document.getElementById("api-base-input");
const apiBaseSaveEl = document.getElementById("api-base-save");

const panels = {
  overview: document.getElementById("overview"),
  recommendations: document.getElementById("recommendations"),
  verification: document.getElementById("verification"),
  reports: document.getElementById("reports"),
};

apiBaseEl.textContent = api.baseUrl;
apiBaseInputEl.value = api.baseUrl;

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

function updateSelectors() {
  farmSelectEl.innerHTML = state.farms
    .map((farm) => `<option value="${farm.id}">${farm.name || farm.id}</option>`)
    .join("");

  if (!state.selectedFarmId && state.farms.length) {
    state.selectedFarmId = String(state.farms[0].id);
  }

  farmSelectEl.value = state.selectedFarmId;

  const zones = getSelectedZones();
  zoneSelectEl.innerHTML = zones.length
    ? zones.map((zone) => `<option value="${zone.id}">${zone.name || zone.id}</option>`).join("")
    : '<option value="">No zones available</option>';

  if (zones.length && !zones.some((z) => String(z.id) === String(state.selectedZoneId))) {
    state.selectedZoneId = String(zones[0].id);
  }

  zoneSelectEl.value = state.selectedZoneId || "";
}

function renderTable(panel, headers, rows, emptyText) {
  if (!rows.length) {
    panel.innerHTML = `<section class="card muted">${emptyText}</section>`;
    return;
  }

  const head = headers.map((h) => `<th>${h}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cell ?? "n/a"}</td>`).join("")}</tr>`)
    .join("\n");

  panel.innerHTML = `<table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function bootstrapFarmsAndZones() {
  const farmsRes = await api.getFarms();
  if (!farmsRes.ok) {
    setMessage(`Unable to load farms (${farmsRes.status}).`, "error");
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
  panel.innerHTML = '<section class="card">Loading overview…</section>';

  const farms = state.farms;
  const allZones = farms.flatMap((farm) => state.zonesByFarm.get(String(farm.id)) || []);
  const sourceCounts = allZones.reduce((acc, zone) => {
    const key = zone.provider || zone.source || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  const selectedFarm = farms.find((f) => String(f.id) === String(state.selectedFarmId));
  const zones = getSelectedZones();

  const cards = farms
    .slice(0, 8)
    .map((farm) => {
      const farmZones = state.zonesByFarm.get(String(farm.id)) || [];
      return `
      <section class="card">
        <h3>${farm.name || `Farm ${farm.id}`}</h3>
        <p class="kv"><span>Farm ID:</span>${farm.id}</p>
        <p class="kv"><span>Zones:</span>${farmZones.length}</p>
        <p class="kv"><span>Controller source:</span>${farm.provider || "unknown"}</p>
      </section>`;
    })
    .join("\n");

  panel.innerHTML = `
    <section class="kpi-row">
      <article class="card"><p class="kpi-value">${farms.length}</p><p class="kpi-label">Farms</p></article>
      <article class="card"><p class="kpi-value">${allZones.length}</p><p class="kpi-label">Zones</p></article>
      <article class="card"><p class="kpi-value">${Object.keys(sourceCounts).join(", ") || "n/a"}</p><p class="kpi-label">Controller source</p></article>
      <article class="card"><p class="kpi-value">${selectedFarm ? zones.length : 0}</p><p class="kpi-label">Selected farm zones</p></article>
    </section>
    <section class="grid-two">${cards || '<section class="card muted">No farms available.</section>'}</section>
  `;
}

async function renderRecommendations() {
  const panel = panels.recommendations;
  panel.innerHTML = '<section class="card">Loading recommendation context…</section>';

  const zone = selectedZone();
  if (!zone) {
    panel.innerHTML = '<section class="card muted">Select a zone/block to view recommendation context.</section>';
    return;
  }

  const [waterRes, historyRes, decisionsRes] = await Promise.all([
    api.getWaterState(zone.id),
    api.getWaterStateHistory(zone.id, 8),
    api.getDecisionRuns(zone.id, 10),
  ]);

  const latestDecision = decisionsRes.ok ? toArray(decisionsRes.data)[0] : null;
  const states = historyRes.ok ? toArray(historyRes.data?.states) : [];

  panel.innerHTML = `
    <section class="grid-two">
      <article class="card">
        <h3>Latest Recommendation Flow</h3>
        <p class="kv"><span>Recommendation time:</span>${formatDate(latestDecision?.recommended_at)}</p>
        <p class="kv"><span>Recommended duration:</span>${latestDecision?.planned_duration_min ?? "n/a"} min</p>
        <p class="kv"><span>Recommended volume:</span>${latestDecision?.planned_volume_m3 ?? "n/a"} m³</p>
        <p class="kv"><span>Status:</span>${latestDecision?.status || "n/a"}</p>
        <p class="kv"><span>Provider:</span>${latestDecision?.provider || "n/a"}</p>
      </article>
      <article class="card">
        <h3>Water State Context</h3>
        <p class="kv"><span>Estimated at:</span>${formatDate(waterRes.data?.estimated_at)}</p>
        <p class="kv"><span>Root zone VWC:</span>${waterRes.data?.root_zone_vwc ?? "n/a"}</p>
        <p class="kv"><span>Stress risk:</span>${waterRes.data?.stress_risk ?? "n/a"}</p>
        <p class="kv"><span>Hours to stress:</span>${waterRes.data?.hours_to_stress ?? "n/a"}</p>
        <p class="kv"><span>Confidence:</span>${waterRes.data?.confidence ?? "n/a"}</p>
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
    "No water-state history returned for this block yet."
  );

  if (!decisionsRes.ok && !waterRes.ok && !historyRes.ok) {
    setMessage(
      "Decisioning/execution data is not available for the selected zone yet. Verify block ID mapping in backend data.",
      "warn"
    );
  }
}

async function renderVerification() {
  const panel = panels.verification;
  panel.innerHTML = '<section class="card">Loading verification data…</section>';

  const zone = selectedZone();
  if (!zone) {
    panel.innerHTML = '<section class="card muted">Select a zone/block to view verification.</section>';
    return;
  }

  const [verificationsRes, irrigationsRes] = await Promise.all([
    api.getVerifications(zone.id, 20),
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
    ["Recommended vs Applied", "Status", "Duration Δ%", "Volume Δ%", "Verified At"],
    verificationRows,
    "No execution verification rows available yet for this block."
  );

  renderTable(
    document.getElementById("irrigation-table"),
    ["Irrigation Time", "Duration (min)", "Depth", "Volume (m³)"],
    irrigationRows,
    "No WiseConn irrigation rows available in the selected 14-day window."
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
  panel.innerHTML = '<section class="card">Loading report endpoints…</section>';

  const zone = selectedZone();
  const { from, to } = defaultDateWindow(30);
  const reportRes = await api.getRoiReport({ from, to, blockId: zone?.id || "" });

  if (reportRes.ok) {
    const r = reportRes.data;
    panel.innerHTML = `
      <section class="card">
        <h3>ROI Report (${from} → ${to})</h3>
        <p class="kv"><span>Block:</span>${r.block_id || "All"}</p>
        <p class="kv"><span>Water saved:</span>${r.water_saved_m3} m³</p>
        <p class="kv"><span>Energy saved:</span>${r.energy_saved_kwh} kWh</p>
        <p class="kv"><span>Cost saved:</span>$${r.cost_saved_usd}</p>
        <p class="kv"><span>Yield delta:</span>${r.yield_delta_pct}%</p>
        <p class="kv"><span>Baseline method:</span>${r.baseline_method}</p>
      </section>
    `;
    return;
  }

  if (reportRes.status === 404) {
    panel.innerHTML =
      '<section class="card muted">Reports endpoint is not exposed in the live deployment yet. Marked as not yet wired.</section>';
    return;
  }

  panel.innerHTML = `<section class="card muted">Reports unavailable (${reportRes.status || "request failed"}): ${
    reportRes.error || "unknown error"
  }</section>`;
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
    setAuthBadge({ ok: false, text: `Auth check failed (${authRes.status || "network"})` });
    return;
  }

  setAuthBadge({
    ok: Boolean(authRes.data?.authenticated),
    text: authRes.data?.authenticated ? "WiseConn API connected" : "WiseConn API not authenticated",
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

apiBaseSaveEl.addEventListener("click", () => {
  const nextBase = apiBaseInputEl.value.trim();
  if (!nextBase) return;
  window.localStorage.setItem("AGROAI_API_BASE", nextBase);
  setMessage("Saved API base override. Reloading portal…");
  window.setTimeout(() => window.location.reload(), 500);
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
