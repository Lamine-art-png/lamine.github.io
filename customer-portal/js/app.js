import { ApiClient } from "./apiClient.js";

const api = new ApiClient();

const state = {
  farms: [],
  zonesByFarm: new Map(),
  controllerEnvironments: [],
  controllerTotals: {},
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
  return String(value ?? "")
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
  if (Number.isNaN(date.getTime())) return String(value);
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

function humanizeSource(source) {
  const key = String(source || "").toLowerCase();
  if (key === "wiseconn") return "WiseConn";
  if (key === "talgil") return "Talgil";
  if (key === "unknown") return "Unknown";
  if (!key) return "Unknown";
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function normalizeSourceFromFarm(farm) {
  return String(farm?.provider || farm?.source || "wiseconn").toLowerCase();
}

function zoneBlockId(zone) {
  const source = String(zone?.provider || zone?.source || "wiseconn").toLowerCase();
  if (source === "wiseconn") {
    return `wc-${zone.id}`;
  }
  if (source === "talgil") {
    const controllerId = zone?.controller_id || zone?.farm_id || "unknown";
    return `tg-${controllerId}-${zone.id}`;
  }
  return String(zone?.id || "");
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
    panel.innerHTML = `<section class="empty-state">${escapeHtml(emptyText)}</section>`;
    return;
  }

  const head = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("");
  const body = rows
    .map(
      (row) =>
        `<tr>${row.map((cell) => `<td>${escapeHtml(cell ?? "n/a")}</td>`).join("")}</tr>`
    )
    .join("\n");

  panel.innerHTML = `<div class="table-wrap"><table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

async function bootstrapFarmsAndZones() {
  const environmentsRes = await api.getControllerEnvironments();
  if (environmentsRes.ok) {
    state.controllerEnvironments = toArray(environmentsRes.data?.environments);
    state.controllerTotals = environmentsRes.data?.totals || {};
  } else {
    state.controllerEnvironments = [];
    state.controllerTotals = {};
  }

  const [wiseconnFarmsRes, talgilFarmsRes] = await Promise.all([
    api.getFarms(),
    api.getTalgilFarms(),
  ]);

  const wiseconnFarms = wiseconnFarmsRes.ok
    ? toArray(wiseconnFarmsRes.data).map((farm) => ({ ...farm, provider: "wiseconn", source: "wiseconn" }))
    : [];
  const talgilFarms = talgilFarmsRes.ok
    ? toArray(talgilFarmsRes.data).map((farm) => ({ ...farm, provider: "talgil", source: "talgil" }))
    : [];

  if (!wiseconnFarmsRes.ok && !talgilFarmsRes.ok) {
    setMessage(
      `Unable to load controller farms (WiseConn ${wiseconnFarmsRes.status}, Talgil ${talgilFarmsRes.status}).`,
      "error"
    );
    state.farms = [];
    updateSelectors();
    return;
  }

  state.farms = [...wiseconnFarms, ...talgilFarms];

  await Promise.all(
    state.farms.map(async (farm) => {
      const source = String(farm.provider || farm.source || "wiseconn").toLowerCase();
      const zonesRes = source === "talgil" ? await api.getTalgilZones(farm.id) : await api.getZones(farm.id);
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
    const key = String(zone.provider || zone.source || "wiseconn").toLowerCase();
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  const selectedFarm = farms.find((f) => String(f.id) === String(state.selectedFarmId));
  const zones = getSelectedZones();
  const sourceSummary = Object.entries(sourceCounts)
    .map(([key, count]) => `${humanizeSource(key)} (${count})`)
    .join(", ");

  const environmentCards = state.controllerEnvironments
    .map((env) => {
      const statusLabel =
        env.status === "live"
          ? "Live"
          : env.status === "configured"
            ? "Configured"
            : "Integration-ready";
      const sourceParts = Object.entries(env.sources || {})
        .map(([source, count]) => `${humanizeSource(source)} ${count}`)
        .join(" • ");

      return `
      <section class="card">
        <div class="card-head">
          <h3 class="section-title">${escapeHtml(env.label || humanizeSource(env.source))}</h3>
          <span class="source-chip ${escapeHtml(env.status || "integration_ready")}">${escapeHtml(statusLabel)}</span>
        </div>
        <p class="kv"><span>Environment source:</span>${escapeHtml(humanizeSource(env.source))}</p>
        <p class="kv"><span>Farms:</span>${escapeHtml(env.farms ?? 0)}</p>
        <p class="kv"><span>Zones:</span>${escapeHtml(env.zones ?? 0)}</p>
        <p class="kv"><span>Observed sources:</span>${escapeHtml(sourceParts || "n/a")}</p>
        <p class="muted">${escapeHtml(env.notes || "")}</p>
      </section>`;
    })
    .join("\n");

  const cards = farms
    .slice(0, 8)
    .map((farm) => {
      const farmZones = state.zonesByFarm.get(String(farm.id)) || [];
      const farmSource = humanizeSource(normalizeSourceFromFarm(farm));
      return `
      <section class="card">
        <div class="card-head">
        <h3 class="section-title">${escapeHtml(farm.name || `Farm ${farm.id}`)}</h3>
          <span class="source-chip subtle">${escapeHtml(farmSource)}</span>
        </div>
        <p class="kv"><span>Farm ID:</span>${escapeHtml(farm.id)}</p>
        <p class="kv"><span>Zones:</span>${escapeHtml(farmZones.length)}</p>
        <p class="kv"><span>Controller source:</span>${escapeHtml(farmSource)}</p>
      </section>`;
    })
    .join("\n");

  panel.innerHTML = `
    <section class="kpi-row">
      <article class="card"><p class="kpi-value">${escapeHtml(state.controllerTotals.farms ?? farms.length)}</p><p class="kpi-label">Controller farms</p></article>
      <article class="card"><p class="kpi-value">${escapeHtml(state.controllerTotals.zones ?? allZones.length)}</p><p class="kpi-label">Controller zones</p></article>
      <article class="card"><p class="kpi-value">${escapeHtml(sourceSummary || "n/a")}</p><p class="kpi-label">Observed zone sources</p></article>
      <article class="card"><p class="kpi-value">${escapeHtml(selectedFarm ? zones.length : 0)}</p><p class="kpi-label">Selected farm zones</p></article>
    </section>
    <section class="card">
      <h3 class="section-title">Controller Environments</h3>
      <p class="muted">AGRO-AI unifies irrigation intelligence across controller environments. Live telemetry flows from authenticated sources while integration-ready sources remain visible without fabricated operational metrics.</p>
    </section>
    <section class="grid-two">${environmentCards || '<section class="empty-state">Controller environment summary is unavailable from the backend right now.</section>'}</section>
    <section class="card">
      <h3 class="section-title">Connected Farm Groups</h3>
      <p class="muted">Operational farms grouped by controller source.</p>
    </section>
    <section class="grid-two">${cards || '<section class="empty-state">No farms available.</section>'}</section>
  `;
}

async function renderRecommendations() {
  const panel = panels.recommendations;
  panel.innerHTML = '<section class="card">Loading recommendation context…</section>';

  const zone = selectedZone();
  if (!zone) {
    panel.innerHTML = '<section class="empty-state">Select a zone/block to view recommendation context.</section>';
    return;
  }

  const blockId = zoneBlockId(zone);
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
        <h3 class="section-title">Latest Recommendation Flow</h3>
        <p class="kv"><span>Recommendation time:</span>${escapeHtml(formatDate(latestDecision?.recommended_at))}</p>
        <p class="kv"><span>Recommended duration:</span>${escapeHtml(latestDecision?.planned_duration_min ?? "n/a")} min</p>
        <p class="kv"><span>Recommended volume:</span>${escapeHtml(latestDecision?.planned_volume_m3 ?? "n/a")} m³</p>
        <p class="kv"><span>Status:</span>${escapeHtml(latestDecision?.status || "n/a")}</p>
        <p class="kv"><span>Controller source:</span>${escapeHtml(humanizeSource(latestDecision?.provider || zone?.provider || zone?.source || "wiseconn"))}</p>
      </article>
      <article class="card">
        <h3 class="section-title">Water State Context</h3>
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
    panel.innerHTML = '<section class="empty-state">Select a zone/block to view verification.</section>';
    return;
  }

  const blockId = zone ? zoneBlockId(zone) : "";
  const zoneSource = String(zone?.provider || zone?.source || "wiseconn").toLowerCase();
  const [verificationsRes, irrigationsRes] = await Promise.all([
    api.getVerifications(blockId, 20),
    zoneSource === "wiseconn" ? api.getIrrigations(zone.id, 14) : Promise.resolve({ ok: true, data: [] }),
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
    ? toArray(irrigationsRes.data)
        .slice(0, 20)
        .map((item) => [
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
    "No irrigation rows are available in the selected 14-day window for this controller environment."
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
        <h3 class="section-title">ROI Report (${escapeHtml(from)} → ${escapeHtml(to)})</h3>
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
      '<section class="empty-state">Reports endpoint is not exposed in the live deployment yet. Marked as not yet wired.</section>';
    return;
  }

  panel.innerHTML = `<section class="empty-state">Reports unavailable (${escapeHtml(reportRes.status || "request failed")}): ${escapeHtml(
    reportRes.error || "unknown error"
  )}</section>`;
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
