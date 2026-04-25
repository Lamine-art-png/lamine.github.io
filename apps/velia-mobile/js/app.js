import { translations } from "./i18n/translations.js";
import { syncService } from "./services/sync.js";
import { generateRecommendation } from "./services/recommendationEngine.js";
import { applyVoiceAction, parseVoiceCommand, saveOfflineVoiceAction } from "./services/voiceAgent.js";
import { weatherService } from "./services/weatherService.js";
import { applyOnboarding, loadState, saveState, useDemoMode } from "./state/store.js";
import { createIrrigationLog, createObservation } from "./state/actions.js";

const app = document.getElementById("app");
let state = loadState();
let route = "today";
let selectedField = null;
let voiceListening = false;
let transcript = "";
let voiceResponse = "";
let weather = state.weatherCache || null;

const nav = ["today", "fields", "alerts", "assistant", "reports", "settings"];
const tr = (k) => translations[state.language || "en"]?.[k] || translations.en[k] || k;

function persist() { saveState(state); }

async function refreshWeather(forceRefresh = false) {
  const location = state.profile?.farm?.location || "farm";
  weather = await weatherService.getWeather({ location, forceRefresh });
  state.weatherCache = weather;
  persist();
}

function addIrrigationLog(payload) {
  const log = createIrrigationLog(payload);
  state.irrigationLogs.unshift(log);
  const field = state.fields.find((f) => f.id === payload.fieldId);
  if (field) {
    field.lastIrrigationAt = log.performedAt;
    field.updatedAt = new Date().toISOString();
  }
  if (!navigator.onLine) syncService.queueAction({ kind: "irrigation_log", payload: log });
  persist();
}

function addFieldNote(payload) {
  const note = { id: `note-${Date.now()}`, createdAt: new Date().toISOString(), ...payload };
  state.fieldNotes.unshift(note);
  if (!navigator.onLine) syncService.queueAction({ kind: "field_note", payload: note });
  persist();
}

function updateCondition(payload) {
  const observation = createObservation(payload);
  state.observations.unshift(observation);
  const field = state.fields.find((f) => f.id === payload.fieldId);
  if (field) {
    field.lastObservation = payload.condition;
    field.updatedAt = new Date().toISOString();
  }
  if (!navigator.onLine) syncService.queueAction({ kind: "observation", payload: observation });
  persist();
}

function recommendationFor(field) {
  const recentObservation = state.observations.find((o) => o.fieldId === field.id);
  const rec = generateRecommendation(field, weather, { lastObservation: recentObservation?.condition });
  state.recommendationHistory.unshift({ fieldId: field.id, rec, at: new Date().toISOString() });
  state.recommendationHistory = state.recommendationHistory.slice(0, 30);
  persist();
  return rec;
}

function todayContent() {
  const field = state.fields[0];
  if (!field) return `<section class='card'>No fields yet. Complete onboarding.</section>`;
  const rec = recommendationFor(field);
  const attentionFields = state.fields.filter((f) => generateRecommendation(f, weather).urgency !== "low");
  const yesterday = state.irrigationLogs.find((l) => Date.now() - new Date(l.performedAt).getTime() > 20 * 3600000);

  return `<section class='card'>
      <p class='priority'>${rec.mainRecommendation}</p>
      <p><strong>Today’s action:</strong> ${rec.nextBestAction}</p>
      <p><strong>Timing:</strong> ${rec.timing} • <strong>Urgency:</strong> ${rec.urgency}</p>
      <p><strong>Confidence:</strong> ${rec.confidence}</p>
      <p><strong>Why:</strong> ${rec.reasonSummary.join(" • ")}</p>
      <p><strong>Missing data:</strong> ${rec.missingData.length ? rec.missingData.join(", ") : "No critical gaps"}</p>
      <p><strong>Weather risks:</strong> heat ${weather?.heatRisk || "unknown"}, frost ${weather?.frostRisk || "unknown"}, rain chance ${weather?.rainChance ?? "n/a"}%</p>
      <p><strong>Fields needing attention:</strong> ${attentionFields.map((f) => f.name).join(", ") || "None"}</p>
      <p><strong>What changed since yesterday:</strong> ${yesterday ? `Irrigation logged ${Math.round((Date.now() - new Date(yesterday.performedAt).getTime()) / 3600000)}h ago.` : "No previous irrigation log."}</p>
      ${!navigator.onLine ? `<p class='warn'>Using last available weather data (${weather?.lastUpdated ? new Date(weather.lastUpdated).toLocaleString() : "unknown"}).</p>` : ""}
      <div class='grid two'>
        <button class='btn' data-open-log='${field.id}'>Log irrigation</button>
        <button class='btn' data-act='note' data-field='${field.id}'>Add field note</button>
        <button class='btn' data-nav='assistant'>Ask Velia</button>
        <button class='btn' data-open-condition='${field.id}'>Update field condition</button>
      </div>
    </section>
    ${voiceCard(field.id, rec)}`;
}

function quickLogForm(fieldId) {
  return `<section class='card'><h3>Log irrigation</h3>
    <label>Field<select id='logField'>${state.fields.map((f) => `<option value='${f.id}' ${f.id === fieldId ? "selected" : ""}>${f.name}</option>`).join("")}</select></label>
    <label>Date and time<input id='logDate' type='datetime-local' /></label>
    <label>Duration (minutes)<input id='logDuration' type='number' min='1' placeholder='60'/></label>
    <label>Water amount mm (optional)<input id='logAmount' type='number' min='0' /></label>
    <label>Note (optional)<input id='logNote' /></label>
    <button class='btn brand' data-save-log='1'>Save irrigation log</button>
  </section>`;
}

function conditionForm(fieldId) {
  const options = ["Looks normal", "Looks dry", "Looks too wet", "Leaves look stressed", "I am not sure"];
  return `<section class='card'><h3>Update field condition</h3>
    <label>Field<select id='conditionField'>${state.fields.map((f) => `<option value='${f.id}' ${f.id === fieldId ? "selected" : ""}>${f.name}</option>`).join("")}</select></label>
    <label>Condition<select id='conditionValue'>${options.map((o) => `<option>${o}</option>`).join("")}</select></label>
    <button class='btn brand' data-save-condition='1'>Save condition</button>
  </section>`;
}

function fieldsContent() {
  if (selectedField?.type === "log") return quickLogForm(selectedField.fieldId);
  if (selectedField?.type === "condition") return conditionForm(selectedField.fieldId);
  if (selectedField?.type === "detail") return fieldDetail(selectedField.fieldId);

  return `<section class='grid'>${state.fields.map((f) => `<article class='card'><h3>${f.name}</h3><p>${f.crop} • ${f.acreage} acres</p><p>${f.irrigationMethod} • ${f.soilType || "Soil unknown"}</p><p>Last irrigation: ${f.lastIrrigationAt ? new Date(f.lastIrrigationAt).toLocaleString() : "not logged"}</p><button class='btn' data-open-field='${f.id}'>Open field</button></article>`).join("")}</section>`;
}

function fieldDetail(fieldId) {
  const f = state.fields.find((x) => x.id === fieldId);
  const logs = state.irrigationLogs.filter((x) => x.fieldId === fieldId).slice(0, 8);
  const notes = state.fieldNotes.filter((x) => x.fieldId === fieldId).slice(0, 8);
  const observations = state.observations.filter((x) => x.fieldId === fieldId).slice(0, 5);

  return `<section class='card'><h2>${f.name}</h2>
    <p>Crop and acreage: ${f.crop} • ${f.acreage}</p><p>Soil type: ${f.soilType || "unknown"}</p><p>Irrigation method: ${f.irrigationMethod}</p><p>Last updated: ${f.updatedAt || "n/a"}</p>
    <h3>Irrigation logs</h3><ul>${logs.map((l) => `<li>${new Date(l.performedAt).toLocaleString()} - ${l.durationMin} min</li>`).join("") || "<li>No logs</li>"}</ul>
    <h3>Field observations</h3><ul>${observations.map((o) => `<li>${o.condition} (${new Date(o.createdAt).toLocaleString()})</li>`).join("") || "<li>No observations</li>"}</ul>
    <h3>Notes</h3><ul>${notes.map((n) => `<li>${new Date(n.createdAt).toLocaleString()} - ${n.text}</li>`).join("") || "<li>No notes</li>"}</ul>
    <p>Recommendation history: placeholder</p><p>Alert history: placeholder</p></section>${voiceCard(f.id, recommendationFor(f))}`;
}

function alertsContent() { return `<section class='card'>No active alerts yet in v0.2.</section>`; }
function assistantContent() {
  const chips = ["Should I irrigate today?", "Log irrigation for Field 1 for two hours", "Field 1 looks dry", "Why is confidence moderate?", "What changed since yesterday?"];
  return `<section class='card'><h2>Field Decision Assistant</h2><p>Ask Velia anything about your irrigation decisions.</p><div class='chips'>${chips.map((c) => `<span class='chip'>${c}</span>`).join("")}</div><p><strong>Velia:</strong> I explain recommendation confidence and missing data so you can decide with confidence.</p></section>${voiceCard(state.fields[0]?.id, state.fields[0] ? recommendationFor(state.fields[0]) : null)}`;
}
function reportsContent() { return `<section class='card'><h2>Reports</h2><p>Planned for next increment.</p></section>`; }
function settingsContent() { return `<section class='card'><h2>Settings</h2><p>Mode: ${state.mode}</p><button class='btn' data-mode='demo'>Demo mode</button><button class='btn' data-mode='real'>Real mode</button><p>Farm location: ${state.profile?.farm?.location || "not set"}</p><button class='btn' data-refresh-weather='1'>Refresh weather</button></section>`; }

function voiceCard(fieldId, rec) {
  const sync = syncService.status();
  return `<section class='card'><h3>Voice Agent</h3><button class='btn mic ${voiceListening ? "listening" : ""}' data-voice='${fieldId}'>${voiceListening ? "Listening... tap to stop" : "Start voice input"}</button><p class='small'>Transcript: ${transcript || "No transcript yet"}</p><p class='small'>Velia response: ${voiceResponse || "No response yet"}</p>${rec ? `<p class='small'>Current confidence: ${rec.confidence}</p>` : ""}${!sync.isOnline ? `<p class='warn'>${tr("offlineSaved")}. ${tr("willSync")}.</p>` : ""}</section>`;
}

function onboardingForm() {
  return `<section class='card'><h2>Welcome to Velia</h2><p>${tr("framing")}</p><div class='grid'>
    <label>Role<select id='role'><option>farmer</option><option>farm manager</option><option>agronomist</option><option>irrigation professional</option><option>enterprise user</option></select></label>
    <label>Farm name<input id='farmName' required /></label>
    <label>Location (city/region)<input id='farmLocation' placeholder='Manual location' /></label>
    <button class='btn' id='captureGps'>Use GPS location</button>
    <label>Field name<input id='fieldName' required /></label>
    <label>Crop type<input id='crop' required /></label>
    <label>Acreage<input id='acreage' type='number' min='1' required /></label>
    <label>Irrigation method<input id='irrigationMethod' required /></label>
    <label>Soil type (optional)<input id='soilType' /></label>
    <label>Last irrigation date (optional)<input id='lastIrrigationAt' type='date' /></label>
    <label>Usual irrigation duration minutes (optional)<input id='usualDurationMin' type='number' min='1' /></label>
    <label>Water source (optional)<input id='waterSource' placeholder='Canal, borehole, reservoir' /></label>
    <label>Data sources<select id='dataSource'><option value='neither'>Neither</option><option value='sensors'>Sensors</option><option value='controller'>Controller</option><option value='both'>Both</option></select></label>
    <label>Units<select id='units'><option value='metric'>Metric</option><option value='imperial'>Imperial</option></select></label>
    <label>Preferred language<select id='language'><option value='en'>English</option><option value='fr'>French</option><option value='es'>Spanish</option><option value='wo'>Wolof</option><option value='ar'>Arabic</option><option value='hi'>Hindi</option><option value='pt'>Portuguese</option></select></label>
    <label>Hardware<select id='hardware'><option value='manual'>Manual irrigation</option><option value='connected'>Connected hardware</option></select></label>
    <button class='btn brand' id='finish'>Finish onboarding</button>
    <button class='btn' id='startDemo'>Use demo mode</button>
  </div></section>`;
}

function content() {
  if (!state.onboarded) return onboardingForm();
  if (route === "today") return todayContent();
  if (route === "fields") return fieldsContent();
  if (route === "alerts") return alertsContent();
  if (route === "assistant") return assistantContent();
  if (route === "reports") return reportsContent();
  return settingsContent();
}

function render() {
  const sync = syncService.status();
  app.innerHTML = `<div class='shell'><header class='top'><div><p class='small'>AGRO-AI</p><h1>${tr("appName")}</h1><p class='small'>${tr("framing")}</p></div><div><span class='small'>${sync.state}${sync.pending ? ` (${sync.pending})` : ""}</span></div></header>${content()}${state.onboarded ? `<nav class='bottom'>${nav.map((n) => `<button class='btn nav ${route === n ? "active" : ""}' data-nav='${n}'>${n}</button>`).join("")}</nav>` : ""}</div>`;
  bind();
}

function bind() {
  app.querySelectorAll("[data-nav]").forEach((b) => (b.onclick = () => { route = b.dataset.nav; selectedField = null; render(); }));
  app.querySelectorAll("[data-open-field]").forEach((b) => (b.onclick = () => { selectedField = { type: "detail", fieldId: b.dataset.openField }; render(); }));
  app.querySelectorAll("[data-open-log]").forEach((b) => (b.onclick = () => { route = "fields"; selectedField = { type: "log", fieldId: b.dataset.openLog }; render(); }));
  app.querySelectorAll("[data-open-condition]").forEach((b) => (b.onclick = () => { route = "fields"; selectedField = { type: "condition", fieldId: b.dataset.openCondition }; render(); }));
  app.querySelectorAll("[data-act='note']").forEach((b) => (b.onclick = () => { addFieldNote({ fieldId: b.dataset.field || state.fields[0]?.id, text: "Field note captured.", source: "manual" }); render(); }));
  app.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = async () => { state = b.dataset.mode === "demo" ? useDemoMode(state) : { ...state, mode: "real" }; persist(); await refreshWeather(true); render(); }));
  app.querySelectorAll("[data-refresh-weather]").forEach((b) => (b.onclick = async () => { await refreshWeather(true); render(); }));

  const saveLogBtn = document.querySelector("[data-save-log='1']");
  if (saveLogBtn) saveLogBtn.onclick = () => {
    addIrrigationLog({ fieldId: document.getElementById("logField").value, performedAt: new Date(document.getElementById("logDate").value || Date.now()).toISOString(), durationMin: document.getElementById("logDuration").value || 45, amountMm: document.getElementById("logAmount").value || null, note: document.getElementById("logNote").value || "", source: "manual" });
    route = "today"; selectedField = null; render();
  };

  const saveConditionBtn = document.querySelector("[data-save-condition='1']");
  if (saveConditionBtn) saveConditionBtn.onclick = () => {
    updateCondition({ fieldId: document.getElementById("conditionField").value, condition: document.getElementById("conditionValue").value, source: "manual" });
    route = "today"; selectedField = null; render();
  };

  const gpsBtn = document.getElementById("captureGps");
  if (gpsBtn) gpsBtn.onclick = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        document.getElementById("farmLocation").value = `${pos.coords.latitude.toFixed(3)}, ${pos.coords.longitude.toFixed(3)}`;
      },
      () => { /* manual fallback stays available */ }
    );
  };

  const finish = document.getElementById("finish");
  if (finish) finish.onclick = async () => {
    const get = (id) => document.getElementById(id).value;
    state = applyOnboarding(state, {
      role: get("role"), farmName: get("farmName"), farmLocation: get("farmLocation"), coordinates: null,
      fieldName: get("fieldName"), crop: get("crop"), acreage: get("acreage"), irrigationMethod: get("irrigationMethod"), soilType: get("soilType"),
      lastIrrigationAt: get("lastIrrigationAt") || null, usualDurationMin: get("usualDurationMin") || null, waterSource: get("waterSource") || null, dataSource: get("dataSource"),
      units: get("units"), language: get("language"), hardware: get("hardware"),
    });
    route = "today";
    persist();
    await refreshWeather(true);
    render();
  };

  const demo = document.getElementById("startDemo");
  if (demo) demo.onclick = async () => { state = useDemoMode(state); route = "today"; persist(); await refreshWeather(true); render(); };

  app.querySelectorAll("[data-voice]").forEach((b) => (b.onclick = () => {
    const fieldId = b.dataset.voice;
    if (!voiceListening) {
      voiceListening = true;
      transcript = "";
    } else {
      voiceListening = false;
      transcript = "Log irrigation for Field 1 for 2 hours";
      const command = parseVoiceCommand(transcript, { fieldId });
      if (!navigator.onLine) {
        saveOfflineVoiceAction(command.action);
        voiceResponse = tr("graceOffline");
      } else {
        applyVoiceAction(command, {
          onIrrigation: (payload) => addIrrigationLog(payload),
          onCondition: (payload) => updateCondition(payload),
          onNote: (payload) => addFieldNote(payload),
          onNoop: (_payload, intent) => {
            if (intent === "ASK_RECOMMENDATION") voiceResponse = recommendationFor(state.fields[0]).mainRecommendation;
            if (intent === "EXPLAIN_RECOMMENDATION") voiceResponse = `Confidence is ${recommendationFor(state.fields[0]).confidence} due to missing data.`;
            if (intent === "WHAT_CHANGED") voiceResponse = "Last change: check latest irrigation and observation entries on Today.";
          },
        });
        if (!voiceResponse) voiceResponse = `Intent: ${command.intent}. Action captured.`;
      }
    }
    render();
  }));
}

if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
window.addEventListener("online", async () => { await syncService.flushQueue(); await refreshWeather(false); render(); });
window.addEventListener("offline", render);

(async () => {
  await refreshWeather(false);
  render();
})();
