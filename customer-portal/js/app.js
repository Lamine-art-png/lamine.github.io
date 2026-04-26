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

function decisionCard() {
  const rec = safeRec();
  const fallback = {
    action: "inspect",
    confidence_label: "Recommendation confidence: pending",
    confidence_score: 0,
    reasoning_summary: "Awaiting telemetry and manual context refresh.",
    data_quality: { data_quality_label: "Data source pending", data_quality_score: 0 },
    verification_plan: { expected_field_outcome: "Verification pending." },
  };
  const current = rec || fallback;
  return `<section class="panel panel-highlight">
      <h2>Today’s Water Decision</h2>
      <p class="decision-action">${String(current.action || "inspect").replaceAll("_", " ")}</p>
      <p><strong>Recommendation confidence:</strong> ${current.confidence_label || "pending"} ${current.confidence_score ? `(${current.confidence_score}/100)` : ""}</p>
      <p><strong>Data quality:</strong> ${current.data_quality?.data_quality_label || "Data source pending"} ${current.data_quality?.data_quality_score ? `(${current.data_quality.data_quality_score}/100)` : ""}</p>
      <p><strong>Key reason:</strong> ${current.reasoning_summary || "Manual context available; awaiting additional telemetry."}</p>
      <p><strong>Recommended action:</strong> ${String(current.action || "inspect").replaceAll("_", " ")}</p>
      <p><strong>Next verification step:</strong> ${current.verification_plan?.expected_field_outcome || "Verification pending"}</p>
      <p class="watch-item"><strong>Watch item:</strong> ${(current.missing_data || []).join(", ") || "No critical gaps reported"}</p>
    </section>`;
}

function headerStatus() {
  const sync = syncService.getSyncStatus();
  const field = activeField();
  const rec = safeRec();
  const source = rec?.source_trace?.source || "manual";
  return `<header class="top-header">
      <div class="brand-row">
        <img class="logo" src="./assets/agro-ai-logo.png" alt="AGRO-AI logo" />
        <div>
          <p class="eyebrow">AGRO-AI Water Command Center</p>
          <h1>Observe · Recommend · Execute · Verify</h1>
        </div>
      </div>
      <div class="status-row">
        <span class="status-pill ${sync.isOnline ? "ok" : "warn"}">${sync.isOnline ? "Connected source live" : "Manual context available"}</span>
        <span class="status-pill">Farm: ${mockFarm.name}</span>
        <span class="status-pill">Zone/Block: ${field?.name || "Selection pending"}</span>
        <span class="status-pill">Live source: ${source}</span>
      </div>
    </header>`;
}

function commandCenterScreen() {
  const field = activeField();
  const rec = safeRec();
  return `<div class="grid-two">
      ${decisionCard()}
      <section class="panel">
        <h3>Operational Context</h3>
        <p><strong>Current farm:</strong> ${mockFarm.name}</p>
        <p><strong>Selected block or zone:</strong> ${field?.name || "Selection pending"}</p>
        <p><strong>Live controller source:</strong> ${rec?.source_trace?.source || "Manual context available"}</p>
        <p><strong>Latest sync status:</strong> ${syncService.getSyncStatus().status}</p>
        <p><strong>Weather context:</strong> ${weather.condition}, ${weather.temperatureC}°C</p>
      </section>
      <section class="panel">
        <h3>Verification Status</h3>
        <p>Recommended: ${String(rec?.action || "inspect").replaceAll("_", " ")}</p>
        <p>Scheduled: ${rec ? "Not scheduled yet" : "Awaiting recommendation"}</p>
        <p>Applied: Awaiting confirmation</p>
        <p>Observed: Observation not recorded yet</p>
      </section>
      <section class="panel">
        <h3>Execution Task</h3>
        <p>${rec?.execution_task?.task_title || "Task generation pending"}</p>
        <ul>${(rec?.execution_task?.task_steps || ["Recommendation pending."]).map((s) => `<li>${s}</li>`).join("")}</ul>
      </section>
      <section class="panel">
        <h3>Reports Panel</h3>
        <p>Daily irrigation intelligence report</p>
        <p>Verification report</p>
        <p>Water-use summary</p>
        <p>Data quality summary</p>
        <p class="muted">Report generation is coming online for this deployment.</p>
      </section>
    </div>`;
}

function intelligenceScreen() {
  const rec = safeRec();
  if (!rec) {
    return `<section class="panel"><h2>Intelligence</h2><p>Awaiting telemetry and recommendation context.</p></section>`;
  }
  return `<div class="grid-two">
      <section class="panel panel-highlight">
        <h2>Intelligence Recommendation</h2>
        <p><strong>Action:</strong> ${String(rec.action).replaceAll("_", " ")}</p>
        <p><strong>Timing:</strong> ${rec.recommended_timing || "Pending"}</p>
        <p><strong>Duration:</strong> ${rec.recommended_duration_minutes || "Pending"} min</p>
        <p><strong>Depth:</strong> ${rec.recommended_depth_mm || "Pending"} mm</p>
        <p><strong>Confidence score:</strong> ${rec.confidence_score}/100</p>
        <p><strong>Confidence label:</strong> ${rec.confidence_label}</p>
      </section>
      <section class="panel">
        <h3>Recommendation Drivers</h3>
        <ul>${(rec.key_drivers || ["Awaiting telemetry"]).map((d) => `<li>${d}</li>`).join("")}</ul>
        <p><strong>Missing data:</strong> ${(rec.missing_data || []).join(", ") || "No critical gaps"}</p>
        <p><strong>Live inputs used:</strong> ${(rec.source_trace?.live_inputs_used || []).join(", ") || "Awaiting telemetry"}</p>
        <p><strong>Manual overrides used:</strong> ${(rec.source_trace?.manual_overrides_used || []).join(", ") || "None"}</p>
        <p><strong>Source trace summary:</strong> ${rec.source_trace?.source || "manual"} • ${rec.source_trace?.context_origin || "manual"}</p>
      </section>
      <section class="panel">
        <h3>Data Quality</h3>
        <p>${rec.data_quality?.data_quality_label || "Data source pending"}</p>
        <p>${rec.data_quality?.data_quality_score || 0}/100</p>
        <p>${(rec.data_quality?.recommendation_limitations || ["Manual context available"]).join(" • ")}</p>
      </section>
      <section class="panel">
        <h3>Explanation</h3>
        <p>${rec.human_readable_explanation?.en || "Explanation pending."}</p>
      </section>
    </div>`;
}

function verificationScreen() {
  const rec = safeRec();
  return `<section class="panel">
      <h2>Verification Chain</h2>
      <div class="chain">
        <div><h4>Recommended</h4><p>${rec ? String(rec.action).replaceAll("_", " ") : "Awaiting recommendation"}</p></div>
        <div><h4>Scheduled</h4><p>Not scheduled yet</p></div>
        <div><h4>Applied</h4><p>No applied record yet</p></div>
        <div><h4>Observed</h4><p>Observation not recorded yet</p></div>
      </div>
      <p class="muted">AGRO-AI separates recommendation, execution, and verification to keep operations trustworthy.</p>
    </section>`;
}

function reportsScreen() {
  return `<section class="panel">
      <h2>Reports</h2>
      <div class="chain">
        <div><h4>Daily irrigation intelligence report</h4><p>Report generation is coming online for this deployment.</p></div>
        <div><h4>Verification report</h4><p>Report generation is coming online for this deployment.</p></div>
        <div><h4>Water-use summary</h4><p>Report generation is coming online for this deployment.</p></div>
        <div><h4>Data quality summary</h4><p>Report generation is coming online for this deployment.</p></div>
      </div>
    </section>`;
}

function integrationsScreen() {
  const envs = state.environments;
  const cards = envs.length
    ? envs.map((env) => `<article class="panel">
        <h3>${env.label}</h3>
        <p><strong>Status:</strong> ${env.status}</p>
        <p><strong>Connection:</strong> ${env.live ? "Connected source live" : "Data source pending"}</p>
        <p><strong>Farms/targets:</strong> ${env.farms ?? 0}</p>
        <p><strong>Zones/sensors:</strong> ${env.zones ?? 0}</p>
        <p><strong>Current limitation:</strong> ${env.notes || "No active limitation"}</p>
      </article>`).join("")
    : `<article class="panel"><h3>Integrations</h3><p>${state.environmentsError || "Awaiting telemetry."}</p></article>`;
  return `<section class="stack">${cards}</section>`;
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
        <div class="sidebar-title">AGRO-AI</div>
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
