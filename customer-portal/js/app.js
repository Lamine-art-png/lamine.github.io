import "./data/models.js";
import { t, setLanguage, language } from "./i18n/index.js";
import { alerts, crops, dailyConsistency, fields, generateRecommendations, getCrop, getFieldById, irrigationLogs, mockFarm, mockUser, notes, reportSummary, weather } from "./data/mockData.js";
import { storageService } from "./services/storageService.js";
import { syncService } from "./services/syncService.js";
import { voiceAgent } from "./services/voiceAgent.js";
import { integrationRegistry } from "./services/integrations/adapters.js";
import { ApiClient } from "./apiClient.js";

const app = document.getElementById("app");
const apiClient = new ApiClient();

const state = {
  route: "today",
  selectedFieldId: fields[0]?.id || "",
  recommendations: generateRecommendations(),
  voiceSession: null,
  voiceTranscript: null,
  voiceResponse: "",
  voiceListening: false,
  runtimeEnvironments: [],
  runtimeEnvironmentsError: "",
  intelligenceRecommendation: null,
  intelligenceError: "",
};

const navItems = ["today", "intelligence", "fields", "alerts", "assistant", "reports", "settings"];

function fmtDate(value) {
  return new Date(value).toLocaleString();
}

function recommendationFor(fieldId) {
  return state.recommendations.find((item) => item.fieldId === fieldId);
}

function renderLayout(content) {
  const sync = syncService.getSyncStatus();
  app.innerHTML = `
    <div class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">AGRO-AI</p>
          <h1>${t("appName")}</h1>
          <p class="framing">${t("framing")}</p>
        </div>
        <div class="status-stack">
          <span class="badge ${sync.isOnline ? "ok" : "offline"}">${sync.isOnline ? "Online" : "Offline mode"}</span>
          <span class="badge">Sync: ${sync.status}${sync.pendingActions ? ` (${sync.pendingActions})` : ""}</span>
        </div>
      </header>
      <main class="page">${content}</main>
      <nav class="bottom-nav">
        ${navItems.map((item) => `<button data-route="${item}" class="nav-btn ${state.route === item ? "active" : ""}">${t(`nav.${item}`)}</button>`).join("")}
      </nav>
    </div>`;

  app.querySelectorAll("[data-route]").forEach((button) => {
    button.addEventListener("click", () => {
      state.route = button.dataset.route;
      render();
    });
  });

  app.querySelectorAll("[data-open-field]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedFieldId = button.dataset.openField;
      state.route = "fields";
      location.hash = `#/fields/${state.selectedFieldId}`;
      render();
    });
  });

  bindVoiceButtons();
}

function quickActionsHtml(fieldId = state.selectedFieldId) {
  return `<div class="quick-actions">
      <button class="action-btn" data-quick="note" data-field="${fieldId}">Add field note</button>
      <button class="action-btn" data-quick="irrigation" data-field="${fieldId}">Log irrigation</button>
      <button class="action-btn" data-quick="photo" data-field="${fieldId}">Take field photo</button>
      <button class="action-btn" data-route="assistant">Ask Velia</button>
      <button class="action-btn voice-entry" data-voice-entry="${fieldId}">🎙️ Voice</button>
    </div>`;
}

function voiceModule(fieldId = state.selectedFieldId) {
  const sync = syncService.getSyncStatus();
  return `<section class="card">
      <h3>Voice Agent</h3>
      <p>${t("voicePrompt")}</p>
      <div class="voice-controls">
        <button class="mic ${state.voiceListening ? "listening" : ""}" data-voice-start="${fieldId}">${state.voiceListening ? "Listening... tap to stop" : "Start voice input"}</button>
      </div>
      <p class="muted">Transcript: ${state.voiceTranscript?.text || "No transcript yet"}</p>
      <p class="muted">Velia response: ${state.voiceResponse || "No response yet"}</p>
      <div class="quick-actions">
        <button class="action-btn" data-voice-speak="1">Read response aloud</button>
        <button class="action-btn" data-voice-save-note="${fieldId}">Save voice note as field note</button>
      </div>
      ${!sync.isOnline ? `<p class="offline-msg">${t("offlineSaved")}. ${t("syncPending")}.</p>` : ""}
    </section>`;
}

function renderToday() {
  const topPriority = state.recommendations
    .filter((r) => r.type === "irrigate_now")
    .sort((a, b) => (a.confidence < b.confidence ? 1 : -1))[0];
  const attentionFields = fields.filter((f) => f.status !== "stable");
  return `
    <section class="card">
      <h2>Today's irrigation decision summary</h2>
      <p class="priority">Today's priority: ${getFieldById(topPriority?.fieldId)?.name || "No urgent field"}</p>
      <p>Recommended next action: ${topPriority?.action || "Monitor all fields"}</p>
      <p>Confidence: ${topPriority?.confidence || "moderate"}</p>
      <p>Weather: ${weather.condition}, ${weather.temperatureC}°C • ${weather.summary}</p>
      <p>Water priority status: ${attentionFields.length} field(s) need attention.</p>
      <p>Daily check-in consistency: ${dailyConsistency.checkInsThisWeek}/7 this week • ${dailyConsistency.streakDays}-day streak placeholder.</p>
      <p>Field attention queue: ${attentionFields.map((f) => f.name).join(", ")}</p>
      ${quickActionsHtml()}
    </section>
    ${voiceModule()}
  `;
}

function renderIntelligence() {
  if (state.intelligenceError) {
    return `<section class="card">
      <h2>Intelligence Engine</h2>
      <p class="muted">Unable to load intelligence recommendation: ${state.intelligenceError}</p>
      <p class="muted">Fallback: operate with conservative manual verification workflow.</p>
    </section>`;
  }

  const rec = state.intelligenceRecommendation;
  if (!rec) {
    return `<section class="card"><h2>Intelligence Engine</h2><p>Loading recommendation...</p></section>`;
  }

  return `<section class="card">
      <h2>Intelligence Engine • Today’s Water Decision</h2>
      <p><strong>Recommended action:</strong> ${rec.action}</p>
      <p><strong>Confidence:</strong> ${rec.confidence_label} (${rec.confidence_score}/100)</p>
      <p><strong>Reason:</strong> ${rec.reasoning_summary}</p>
      <p><strong>Data quality:</strong> ${rec.data_quality.data_quality_label} (${rec.data_quality.data_quality_score}/100)</p>
      <p><strong>Missing data:</strong> ${(rec.missing_data || []).join(", ") || "none"}</p>
      <p><strong>Verification plan:</strong> ${rec.verification_plan.expected_field_outcome}</p>
      <p><strong>Source trace:</strong> ${rec.source_trace.source || "unknown"} / ${rec.source_trace.source_entity_id || "n/a"}</p>
      <p><strong>Language status:</strong> ${rec.language_status}</p>
      <h3>Execution Task</h3>
      <p>${rec.execution_task.task_title} • due ${rec.execution_task.due_window}</p>
      <ol>${rec.execution_task.task_steps.map((step) => `<li>${step}</li>`).join("")}</ol>
      <h3>Explanation</h3>
      <p>${rec.human_readable_explanation.en}</p>
    </section>`;
}

function fieldCard(field) {
  const crop = getCrop(field.cropId);
  const rec = recommendationFor(field.id);
  return `<article class="card field-card" data-open-field="${field.id}">
    <h3>${field.name}</h3>
    <p>${crop?.name} • ${field.acreage} acres</p>
    <p>Irrigation status: ${field.status}</p>
    <p>Water stress: ${field.waterStressLevel}</p>
    <p>Last irrigation: ${fmtDate(field.lastIrrigationAt)}</p>
    <p>Next recommended action: ${rec?.action || "Monitor"}</p>
    <p>Data source: ${field.dataSourceStatus}</p>
  </article>`;
}

function renderFieldDetail(fieldId) {
  const field = getFieldById(fieldId);
  if (!field) return `<section class="card"><p>Field not found.</p></section>`;
  const crop = getCrop(field.cropId);
  const rec = recommendationFor(field.id);
  const fieldNotes = notes.filter((note) => note.fieldId === field.id);
  const activity = irrigationLogs.filter((log) => log.fieldId === field.id);

  return `<section class="card">
      <h2>${field.name}</h2>
      <p>Crop and acreage: ${crop?.name} • ${field.acreage} acres</p>
      <p>Soil type: ${field.soilType}</p>
      <p>Irrigation method: ${field.irrigationMethod}</p>
      <p>Latest recommendation: ${rec?.action}</p>
      <p>Reasoning summary: ${(rec?.reasoning || []).join(" • ")}</p>
      <h3>Recent activity timeline</h3>
      <ul>${activity.map((log) => `<li>${fmtDate(log.performedAt)} - ${log.amountMm} mm (${log.durationMin} min)</li>`).join("") || "<li>No activity logged.</li>"}</ul>
      <h3>Notes</h3>
      <ul>${fieldNotes.map((note) => `<li>${fmtDate(note.createdAt)} - ${note.text}</li>`).join("") || "<li>No notes yet.</li>"}</ul>
      <p>Photos: placeholder for field photos</p>
      <div class="quick-actions">
        <button class="action-btn" data-quick="irrigation" data-field="${field.id}">Manual log</button>
        <button class="action-btn" data-quick="note" data-field="${field.id}">Add note</button>
      </div>
      <p>Recommendation history: placeholder</p>
    </section>
    ${voiceModule(field.id)}`;
}

function renderFields() {
  const hashField = location.hash.match(/^#\/fields\/(.+)$/)?.[1];
  if (hashField) return renderFieldDetail(hashField);
  return `<section class="stack">${fields.map(fieldCard).join("")}</section>`;
}

function renderAlerts() {
  return `<section class="stack">${alerts.map((alert) => `<article class="card">
      <h3>${alert.type}</h3>
      <p>Severity: <span class="sev ${alert.severity}">${alert.severity}</span></p>
      <p>Field affected: ${alert.fieldId ? getFieldById(alert.fieldId)?.name : "Farm-wide"}</p>
      <p>Recommended action: ${alert.action}</p>
      <p>Time sensitivity: ${alert.timeSensitivity}</p>
    </article>`).join("")}</section>`;
}

function renderAssistant() {
  const prompts = [
    "Should I irrigate today?",
    "Which field needs attention?",
    "Explain this recommendation",
    "What changed since yesterday?",
    "Create a water plan for this week",
  ];
  return `<section class="card">
      <h2>Field Decision Assistant</h2>
      <p>Ask Velia anything about your fields, irrigation, weather risk, or water planning.</p>
      <div class="chips">${prompts.map((p) => `<button class="chip">${p}</button>`).join("")}</div>
      <div class="conversation">
        <p><strong>You:</strong> Which field needs attention?</p>
        <p><strong>Velia:</strong> Based on current weather and your last logged irrigation, Field 2 is the priority today. I recommend checking soil conditions before irrigating because the confidence is moderate.</p>
      </div>
    </section>
    ${voiceModule()}`;
}

function renderReports() {
  return `<section class="card">
    <h2>Reports</h2>
    <p>Weekly water summary: ${reportSummary.periodLabel}</p>
    <p>Recommended vs logged irrigation: ${reportSummary.recommendedMm} mm vs ${reportSummary.loggedMm} mm</p>
    <p>Estimated water saved: placeholder (calculation pending verified baseline)</p>
    <p>Field performance: ${reportSummary.fieldPerformanceSummary}</p>
    <button class="action-btn" disabled>Export report (placeholder)</button>
  </section>`;
}

function renderSettings() {
  const environmentsHtml = state.runtimeEnvironments.length
    ? `<ul>${state.runtimeEnvironments
      .map(
        (env) =>
          `<li><strong>${env.label}</strong>: ${env.status} • farms ${env.farms} • zones ${env.zones}<br><span class="muted">${env.notes}</span></li>`,
      )
      .join("")}</ul>`
    : `<p class="muted">${state.runtimeEnvironmentsError || "Runtime controller environments are unavailable from API."}</p>`;

  return `<section class="card">
    <h2>Settings</h2>
    <p>Farm profile: ${mockFarm.name}, ${mockFarm.location}</p>
    <label>Language
      <select id="language-select">
        <option value="en" ${language() === "en" ? "selected" : ""}>English</option>
      </select>
    </label>
    <p>Units: Metric default (placeholder toggle)</p>
    <p>Offline mode: Enabled with local queue fallback</p>
    <p>Data sources: Manual, Weather, Sensor, Controller</p>
    <p>Integrations: ${integrationRegistry.list().map((item) => item.name).join(", ")}</p>
    <h3>Runtime integration status</h3>
    ${environmentsHtml}
    <p>Team members: ${mockUser.name} (${mockUser.role})</p>
    <p>Notification preferences: reminder-ready structure placeholder</p>
  </section>`;
}

function bindGeneralActions() {
  app.querySelectorAll("[data-quick]").forEach((button) => {
    button.addEventListener("click", () => {
      const type = button.dataset.quick;
      const fieldId = button.dataset.field || state.selectedFieldId;
      if (type === "note") {
        const note = { id: `n-${Date.now()}`, fieldId, text: "Quick note placeholder captured.", createdAt: new Date().toISOString(), source: "manual", synced: navigator.onLine };
        notes.unshift(note);
        if (!navigator.onLine) syncService.enqueue({ kind: "field_note", payload: note });
      }
      if (type === "irrigation") {
        const log = { id: `log-${Date.now()}`, fieldId, amountMm: 8, durationMin: 35, method: getFieldById(fieldId)?.irrigationMethod || "manual", performedAt: new Date().toISOString(), source: "manual" };
        irrigationLogs.unshift(log);
        if (!navigator.onLine) syncService.enqueue({ kind: "irrigation_log", payload: log });
      }
      render();
    });
  });

  const languageSelect = document.getElementById("language-select");
  if (languageSelect) {
    languageSelect.addEventListener("change", (event) => {
      setLanguage(event.target.value);
      storageService.set("lang", event.target.value);
      render();
    });
  }
}

function bindVoiceButtons() {
  app.querySelectorAll("[data-voice-start]").forEach((button) => {
    button.addEventListener("click", () => {
      const fieldId = button.dataset.voiceStart;
      if (!state.voiceListening) {
        state.voiceSession = voiceAgent.startListening(language(), fieldId);
        state.voiceListening = true;
      } else {
        state.voiceSession = voiceAgent.stopListening(state.voiceSession);
        state.voiceTranscript = voiceAgent.transcribe(state.voiceSession);
        const command = voiceAgent.detectIntent(state.voiceTranscript);
        const action = voiceAgent.executeVoiceAction(command, { fieldId, transcript: state.voiceTranscript });

        if (!navigator.onLine) {
          voiceAgent.saveOfflineVoiceAction(action);
          state.voiceResponse = t("gracefulOffline");
        } else {
          const field = getFieldById(fieldId);
          const rec = recommendationFor(fieldId);
          state.voiceResponse = voiceAgent.composeResponse({ recommendation: { ...rec, fieldName: field?.name }, command: action, offline: false });
        }
        state.voiceListening = false;
      }
      render();
    });
  });

  app.querySelectorAll("[data-voice-save-note]").forEach((button) => {
    button.addEventListener("click", () => {
      const fieldId = button.dataset.voiceSaveNote;
      if (!state.voiceTranscript?.text) return;
      const note = { id: `n-${Date.now()}`, fieldId, text: state.voiceTranscript.text, createdAt: new Date().toISOString(), source: "voice", synced: navigator.onLine };
      notes.unshift(note);
      if (!navigator.onLine) syncService.enqueue({ kind: "field_note", payload: note });
      render();
    });
  });

  app.querySelectorAll("[data-voice-speak]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!state.voiceResponse) return;
      state.voiceResponse = voiceAgent.speakResponse({ text: state.voiceResponse }).text;
      render();
    });
  });
}

function routeContent() {
  if (state.route === "today") return renderToday();
  if (state.route === "intelligence") return renderIntelligence();
  if (state.route === "fields") return renderFields();
  if (state.route === "alerts") return renderAlerts();
  if (state.route === "assistant") return renderAssistant();
  if (state.route === "reports") return renderReports();
  if (state.route === "settings") return renderSettings();
  return renderToday();
}

function render() {
  renderLayout(routeContent());
  bindGeneralActions();
}

async function bootstrap() {
  const storedLanguage = storageService.get("lang", "en");
  setLanguage(storedLanguage);
  const environments = await apiClient.getControllerEnvironments();
  if (environments.ok) {
    state.runtimeEnvironments = environments.data?.environments || [];
    state.runtimeEnvironmentsError = "";
  } else {
    state.runtimeEnvironments = [];
    state.runtimeEnvironmentsError = environments.error || "Unable to fetch runtime environments.";
  }

  const field = fields[0];
  const intelligencePayload = {
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
      sensor_context: {},
      controller_context: {},
      recent_irrigation_context: {},
      field_observations: [],
      confidence_inputs: ["portal_bootstrap"],
    },
    language: language(),
    user_role: mockUser.role || "farm_manager",
    time_horizon: "today",
  };
  const intelligenceResp = await apiClient.getIntelligenceRecommendation(intelligencePayload);
  if (intelligenceResp.ok) {
    state.intelligenceRecommendation = intelligenceResp.data;
    state.intelligenceError = "";
  } else {
    state.intelligenceRecommendation = null;
    state.intelligenceError = intelligenceResp.error || "Unknown intelligence API error.";
  }
  window.addEventListener("online", async () => {
    await syncService.syncQueuedActions();
    const response = await apiClient.getControllerEnvironments();
    if (response.ok) {
      state.runtimeEnvironments = response.data?.environments || [];
      state.runtimeEnvironmentsError = "";
    }
    render();
  });
  window.addEventListener("offline", render);
  window.addEventListener("hashchange", render);
  render();
}

bootstrap();
