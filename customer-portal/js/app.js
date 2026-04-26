import { t, setLanguage } from "./i18n/index.js";
import { fields, getCrop, getFieldById, mockFarm, mockUser, weather } from "./data/mockData.js";
import { storageService } from "./services/storageService.js";
import { syncService } from "./services/syncService.js";
import { ApiClient } from "./apiClient.js";

const app = document.getElementById("app");
const apiClient = new ApiClient();
const DEFAULT_WISECONN_ZONE_ID = "162803";

const state = {
  route: "command_center",
  selectedFieldId: fields[0]?.id || "",
  recommendation: null,
  recommendationError: "",
  environments: [],
  environmentsError: "",
};

const navItems = [
  { id: "command_center", label: "Command Center" },
  { id: "intelligence", label: "Intelligence" },
  { id: "verification", label: "Verification" },
  { id: "reports", label: "Reports" },
  { id: "integrations", label: "Integrations" },
];

function activeField() {
  return getFieldById(state.selectedFieldId) || fields[0] || null;
}

function safeRec() {
  return state.recommendation;
}

function fallbackRecommendation() {
  return {
    action: "monitor field conditions",
    confidence_label: "Recommendation confidence: pending",
    confidence_score: 0,
    reasoning_summary: "Manual context available while live telemetry is still arriving.",
    data_quality: { data_quality_label: "Data source pending", data_quality_score: 0 },
    verification_plan: { expected_field_outcome: "Verification pending." },
    key_drivers: ["Manual context available"],
    missing_data: ["Live telemetry feed"],
    source_trace: {
      source: "Manual context available",
      context_origin: "Operator-provided context",
      live_inputs_used: [],
      manual_overrides_used: [],
    },
    execution_task: {
      task_title: "Prepare operations team for next irrigation event",
      task_steps: ["Confirm schedule window", "Validate field readiness", "Capture observed outcome"],
    },
    human_readable_explanation: {
      en: "AGRO-AI is holding a conservative recommendation until richer telemetry arrives.",
    },
  };
}

function titleCase(value) {
  return String(value || "").replaceAll("_", " ");
}

function decisionCard() {
  const rec = safeRec() || fallbackRecommendation();
  return `<section class="panel panel-highlight">
      <h2>Today’s Water Decision</h2>
      <p class="decision-action">${titleCase(rec.action)}</p>
      <p><strong>Recommendation confidence:</strong> ${rec.confidence_label || "pending"} ${rec.confidence_score ? `(${rec.confidence_score}/100)` : ""}</p>
      <p><strong>Data quality:</strong> ${rec.data_quality?.data_quality_label || "Data source pending"} ${rec.data_quality?.data_quality_score ? `(${rec.data_quality.data_quality_score}/100)` : ""}</p>
      <p><strong>Key reason:</strong> ${rec.reasoning_summary || "Awaiting telemetry"}</p>
      <p><strong>Recommended action:</strong> ${titleCase(rec.action)}</p>
      <p><strong>Next verification step:</strong> ${rec.verification_plan?.expected_field_outcome || "Verification pending"}</p>
      <p class="watch-item"><strong>Watch item:</strong> ${(rec.missing_data || []).join(", ") || "No critical watch item at this time."}</p>
    </section>`;
}

function headerStatus() {
  const sync = syncService.getSyncStatus();
  const field = activeField();
  const rec = safeRec();
  const source = rec?.source_trace?.source || "Manual context available";
  return `<header class="top-header">
      <div class="brand-row">
        <img class="logo" src="./assets/agro-ai-logo.png" alt="AGRO-AI logo" />
        <div>
          <p class="eyebrow">AGRO-AI Portal</p>
          <h1>${t("appName")}</h1>
          <p class="subhead">Water Command Center</p>
        </div>
      </div>
      <div class="status-row">
        <span class="status-pill ${sync.isOnline ? "ok" : "warn"}">${sync.isOnline ? "Connected source live" : "Manual context available"}</span>
        <span class="status-pill">Selected farm: ${mockFarm.name}</span>
        <span class="status-pill">Selected block or zone: ${field?.name || "Selection pending"}</span>
        <span class="status-pill">Live controller source: ${source}</span>
      </div>
    </header>`;
}

function commandCenterScreen() {
  const field = activeField();
  const rec = safeRec() || fallbackRecommendation();
  return `<div class="grid-two">
      ${decisionCard()}
      <section class="panel">
        <h3>Operational Snapshot</h3>
        <p><strong>Selected farm:</strong> ${mockFarm.name}</p>
        <p><strong>Selected block or zone:</strong> ${field?.name || "Selection pending"}</p>
        <p><strong>Live controller source:</strong> ${rec.source_trace?.source || "Manual context available"}</p>
        <p><strong>Today’s weather:</strong> ${weather.condition}, ${weather.temperatureC}°C</p>
        <p><strong>Sync status:</strong> ${syncService.getSyncStatus().status}</p>
      </section>
      <section class="panel">
        <h3>Next Operational Verification</h3>
        <p><strong>Recommended:</strong> ${titleCase(rec.action)}</p>
        <p><strong>Scheduled:</strong> Not scheduled yet</p>
        <p><strong>Applied:</strong> Awaiting confirmation</p>
        <p><strong>Observed:</strong> Observation not recorded yet</p>
      </section>
      <section class="panel">
        <h3>Execution Task</h3>
        <p>${rec.execution_task?.task_title || "Execution task will appear after recommendation refresh."}</p>
        <ul>${(rec.execution_task?.task_steps || ["Verification pending"]).map((step) => `<li>${step}</li>`).join("")}</ul>
      </section>
      <section class="panel">
        <h3>Watchboard</h3>
        <p><strong>Priority watch item:</strong> ${(rec.missing_data || []).join(", ") || "No critical watch item at this time."}</p>
        <p class="muted">Recommendations stay conservative while AGRO-AI protects water efficiency and crop safety.</p>
      </section>
    </div>`;
}

function intelligenceScreen() {
  const rec = safeRec() || fallbackRecommendation();

  return `<div class="grid-two">
      <section class="panel panel-highlight">
        <h2>Today’s Recommendation</h2>
        <p><strong>Action:</strong> ${titleCase(rec.action)}</p>
        <p><strong>Timing:</strong> ${rec.recommended_timing || "Timing pending"}</p>
        <p><strong>Duration:</strong> ${rec.recommended_duration_minutes || "Duration pending"} min</p>
        <p><strong>Depth:</strong> ${rec.recommended_depth_mm || "Depth pending"} mm</p>
        <p><strong>Recommendation confidence:</strong> ${rec.confidence_label || "pending"} ${rec.confidence_score ? `(${rec.confidence_score}/100)` : ""}</p>
        <p><strong>Data quality:</strong> ${rec.data_quality?.data_quality_label || "Data source pending"}</p>
      </section>
      <section class="panel">
        <h3>Drivers and Coverage</h3>
        <p><strong>Key drivers:</strong></p>
        <ul>${(rec.key_drivers || ["Awaiting telemetry"]).map((item) => `<li>${item}</li>`).join("")}</ul>
        <p><strong>Missing data:</strong> ${(rec.missing_data || []).join(", ") || "No critical gaps reported."}</p>
        <p><strong>Live inputs used:</strong> ${(rec.source_trace?.live_inputs_used || []).join(", ") || "Awaiting telemetry"}</p>
        <p><strong>Manual overrides used:</strong> ${(rec.source_trace?.manual_overrides_used || []).join(", ") || "None"}</p>
        <p><strong>Source trace summary:</strong> ${rec.source_trace?.source || "Manual context available"} • ${rec.source_trace?.context_origin || "Operator context"}</p>
      </section>
      <section class="panel">
        <h3>Explanation</h3>
        <p>${rec.human_readable_explanation?.en || "Explanation pending."}</p>
      </section>
      <section class="panel">
        <h3>Execution + Verification Plan</h3>
        <p><strong>Execution task:</strong> ${rec.execution_task?.task_title || "Execution guidance pending"}</p>
        <ul>${(rec.execution_task?.task_steps || ["Verification pending"]).map((step) => `<li>${step}</li>`).join("")}</ul>
        <p><strong>Verification plan:</strong> ${rec.verification_plan?.expected_field_outcome || "Verification pending"}</p>
      </section>
    </div>`;
}

function verificationScreen() {
  const rec = safeRec();
  return `<section class="panel">
      <h2>Verification Chain</h2>
      <div class="chain">
        <div><h4>Recommended</h4><p>${rec ? titleCase(rec.action) : "Awaiting recommendation"}</p></div>
        <div><h4>Scheduled</h4><p>Not scheduled yet</p></div>
        <div><h4>Applied</h4><p>No applied record yet</p></div>
        <div><h4>Observed</h4><p>Observation not recorded yet</p></div>
      </div>
      <p class="muted">AGRO-AI keeps recommendation, scheduling, application, and observation clearly separated for operational trust.</p>
    </section>`;
}

function reportsScreen() {
  const reportCard = (title) => `<article class="panel report-card"><h4>${title}</h4><p>Report generation is coming online for this deployment.</p></article>`;
  return `<section class="stack">
      ${reportCard("Daily irrigation intelligence report")}
      ${reportCard("Verification report")}
      ${reportCard("Water-use summary")}
      ${reportCard("Data quality summary")}
    </section>`;
}

function integrationsScreen() {
  const envs = state.environments;
  if (!envs.length) {
    return `<section class="panel">
      <h2>Integrations</h2>
      <p>${state.environmentsError || "Data source pending"}</p>
    </section>`;
  }

  const sorted = [...envs].sort((a, b) => {
    if (a.label === "WiseConn") return -1;
    if (b.label === "WiseConn") return 1;
    if (a.label === "Talgil") return -1;
    if (b.label === "Talgil") return 1;
    return a.label.localeCompare(b.label);
  });

  return `<section class="stack">
      ${sorted
        .map(
          (env) => `<article class="panel">
            <h3>${env.label}</h3>
            <p><strong>Status:</strong> ${env.status}</p>
            <p><strong>Connection state:</strong> ${env.live ? "Connected source live" : "Data source pending"}</p>
            <p><strong>Farms or targets:</strong> ${env.farms ?? 0}</p>
            <p><strong>Zones or sensors:</strong> ${env.zones ?? 0}</p>
            <p><strong>Last check:</strong> ${env.last_check || "Awaiting telemetry"}</p>
            <p><strong>Current limitation:</strong> ${env.notes || "No current limitation reported."}</p>
          </article>`,
        )
        .join("")}
    </section>`;
}

function routeScreen() {
  if (state.route === "command_center") return commandCenterScreen();
  if (state.route === "intelligence") return intelligenceScreen();
  if (state.route === "verification") return verificationScreen();
  if (state.route === "reports") return reportsScreen();
  if (state.route === "integrations") return integrationsScreen();
  return commandCenterScreen();
}

function layout() {
  app.innerHTML = `
    <div class="command-shell">
      <aside class="sidebar">
        <div class="sidebar-title">AGRO-AI Water Command Center</div>
        ${navItems
          .map(
            (item) => `<button class="nav-item ${state.route === item.id ? "active" : ""}" data-route="${item.id}">${item.label}</button>`,
          )
          .join("")}
      </aside>
      <div class="main-area">
        ${headerStatus()}
        <section class="context-bar panel">
          <p><strong>Operator:</strong> ${mockUser.name} (${mockUser.role})</p>
          <p><strong>Selected context:</strong> ${activeField()?.name || "Selection pending"}</p>
          <label>Block / Zone
            <select id="field-select">${fields.map((f) => `<option value="${f.id}" ${f.id === state.selectedFieldId ? "selected" : ""}>${f.name}</option>`).join("")}</select>
          </label>
        </section>
        <main class="screen">${routeScreen()}</main>
      </div>
    </div>`;

  app.querySelectorAll("[data-route]").forEach((button) => {
    button.addEventListener("click", () => {
      state.route = button.dataset.route;
      render();
    });
  });

  const select = document.getElementById("field-select");
  if (select) {
    select.addEventListener("change", async (e) => {
      state.selectedFieldId = e.target.value;
      await loadIntelligence();
      render();
    });
  }
}

async function loadIntegrations() {
  const response = await apiClient.getControllerEnvironments();
  if (response.ok) {
    state.environments = response.data?.environments || [];
    state.environmentsError = "";
  } else {
    state.environments = [];
    state.environmentsError = response.error || "Data source pending";
  }
}

async function loadIntelligence() {
  const field = activeField();
  const fallbackPayload = {
    field_context: {
      field_id: field?.id || "field-unknown",
      farm_id: mockFarm.id || "farm-unknown",
      source: "manual",
      source_entity_id: field?.id || null,
      crop_type: getCrop(field?.cropId)?.name || null,
      irrigation_method: field?.irrigationMethod || null,
      soil_type: field?.soilType || null,
      area: field?.acreage || null,
      location: { region: mockFarm.location || null },
      weather_context: {
        eto_mm: weather.et0 || 4.2,
        precipitation_forecast_mm: weather.rainForecastMm || 0,
        temperature_c: weather.temperatureC || null,
      },
      field_observations: [],
      confidence_inputs: ["portal_command_center"],
    },
    language: "en",
    user_role: mockUser.role || "farm_manager",
    time_horizon: "today",
  };

  let response = await apiClient.request(`/v1/intelligence/recommend/live/wiseconn/${DEFAULT_WISECONN_ZONE_ID}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      crop_type: getCrop(field?.cropId)?.name || null,
      soil_type: field?.soilType || null,
      irrigation_method: field?.irrigationMethod || null,
      area: field?.acreage || null,
      location: { region: mockFarm.location || null },
      weather_context: fallbackPayload.field_context.weather_context,
      field_observations: [],
      language: "en",
      user_role: mockUser.role || "farm_manager",
      time_horizon: "today",
    }),
  });

  if (!response.ok) {
    response = await apiClient.getIntelligenceRecommendation(fallbackPayload);
  }

  if (response.ok) {
    state.recommendation = response.data;
    state.recommendationError = "";
  } else {
    state.recommendation = null;
    state.recommendationError = response.error || "Awaiting telemetry";
  }
}

function render() {
  layout();
}

async function bootstrap() {
  setLanguage(storageService.get("lang", "en"));
  await Promise.all([loadIntegrations(), loadIntelligence()]);
  window.addEventListener("online", async () => {
    await syncService.syncQueuedActions();
    await Promise.all([loadIntegrations(), loadIntelligence()]);
    render();
  });
  window.addEventListener("offline", render);
  render();
}

bootstrap();
