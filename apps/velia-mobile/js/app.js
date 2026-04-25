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
let onboardingStep = 0;
let onboardingDraft = {
  role: "farmer",
  language: "en",
  farmName: "",
  farmLocation: "",
  coordinates: null,
  fieldName: "",
  crop: "",
  acreage: "",
  units: "metric",
  irrigationMethod: "Drip",
  dataSource: "neither",
  hardware: "manual",
  soilType: "",
  lastIrrigationAt: "",
  usualDurationMin: "",
  waterSource: "",
};

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
  const recentHistory = state.recommendationHistory.slice(0, 3);

  return `<section class='today-stack'>
      <article class='card decision-card'>
        <p class='card-label'>Today’s decision</p>
        <h2>${field.name}</h2>
        <p class='decision-main'>${rec.mainRecommendation}</p>
        <div class='meta-row'>
          <span>Timing: ${rec.timing}</span>
          <span>Urgency: ${rec.urgency}</span>
        </div>
        <p class='small'>Next best step: ${rec.nextBestAction}</p>
      </article>

      <section class='today-grid'>
        <article class='card compact-card'>
          <p class='card-label'>Confidence</p>
          <p class='value-pill'>${rec.confidence}</p>
          <p class='small'>Velia is clearer when field updates are recent.</p>
        </article>

        <article class='card compact-card'>
          <p class='card-label'>Weather risk</p>
          <p>${weather?.forecastSummary || "Using last available weather."}</p>
          <div class='tag-row'>
            <span class='tag'>Heat: ${weather?.heatRisk || "unknown"}</span>
            <span class='tag'>Frost: ${weather?.frostRisk || "unknown"}</span>
            <span class='tag'>Rain: ${weather?.rainChance ?? "n/a"}%</span>
          </div>
          ${!navigator.onLine ? `<p class='small warn'>Using last available weather data.</p>` : ""}
        </article>

        <article class='card compact-card'>
          <p class='card-label'>Missing data</p>
          ${rec.missingData.length
            ? `<ul class='mini-list'>${rec.missingData.map((item) => `<li>${item}</li>`).join("")}</ul>`
            : `<p class='small'>No critical data gaps today.</p>`}
          <p class='small'>Not sure? You can update anytime from Fields.</p>
        </article>

        <article class='card compact-card'>
          <p class='card-label'>Fields needing attention</p>
          ${attentionFields.length
            ? `<ul class='mini-list'>${attentionFields.map((f) => `<li>${f.name}</li>`).join("")}</ul>`
            : `<p class='small'>All fields look stable now.</p>`}
        </article>
      </section>

      <article class='card compact-card'>
        <p class='card-label'>Recommendation history</p>
        ${recentHistory.length
          ? `<ul class='mini-list'>${recentHistory.map((entry) => `<li>${new Date(entry.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}: ${entry.rec.urgency} urgency</li>`).join("")}</ul>`
          : `<p class='small'>Your recommendation history will appear here.</p>`}
      </article>

      <article class='card compact-card'>
        <p class='card-label'>Quick actions</p>
        <div class='quick-actions-grid'>
          <button class='btn brand' data-open-log='${field.id}'>Log irrigation</button>
          <button class='btn' data-act='note' data-field='${field.id}'>Add field note</button>
          <button class='btn' data-open-condition='${field.id}'>Update field condition</button>
          <button class='btn' data-nav='assistant'>Ask Velia</button>
        </div>
      </article>
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

function progressDots() {
  const steps = ["Welcome", "Role", "Location", "Field", "Setup"];
  return `<div class='progress-wrap'>${steps.map((s, i) => `<div class='progress-pill ${onboardingStep === i ? "active" : onboardingStep > i ? "done" : ""}'>${s}</div>`).join("")}</div>`;
}

function cardOptions(options, key) {
  return `<div class='choice-grid'>${options.map((option) => `<button type='button' class='choice-card ${onboardingDraft[key] === option.value ? "selected" : ""}' data-onboard-choice='${key}' data-value='${option.value}'><strong>${option.label}</strong>${option.sub ? `<span>${option.sub}</span>` : ""}</button>`).join("")}</div>`;
}

function onboardingFlow() {
  if (onboardingStep === 0) {
    return `<section class='onboard-hero'>
      <p class='eyebrow'>AGRO-AI</p>
      <h1 class='onboard-title'>Velia</h1>
      <p class='onboard-promise'>Know what to do with water today.</p>
      <p class='small'>Simple daily irrigation guidance for farms of every size.</p>
      <button class='btn brand xl' data-next-step='1'>Set up my farm</button>
      <button class='btn xl' id='startDemo'>Try demo mode</button>
    </section>`;
  }

  const stepCards = {
    1: `<section class='card onboard-card'><h2>Who will use Velia?</h2><p class='small'>Pick your role and language.</p>
      ${cardOptions([
        { value: "farmer", label: "Farmer" },
        { value: "farm manager", label: "Farm manager" },
        { value: "agronomist", label: "Agronomist" },
        { value: "irrigation professional", label: "Irrigation pro" },
        { value: "enterprise user", label: "Enterprise" },
      ], "role")}
      <label>Language<select id='language'><option value='en' ${onboardingDraft.language === "en" ? "selected" : ""}>English</option><option value='fr'>French</option><option value='es'>Spanish</option><option value='wo'>Wolof</option><option value='ar'>Arabic</option><option value='hi'>Hindi</option><option value='pt'>Portuguese</option></select></label>
    </section>`,
    2: `<section class='card onboard-card'><h2>Where is your farm?</h2><p class='small'>Used for local weather context.</p>
      <label>Farm name<input id='farmName' value='${onboardingDraft.farmName}' placeholder='e.g., North Valley Farm' /></label>
      <label>Location<input id='farmLocation' value='${onboardingDraft.farmLocation}' placeholder='City or region' /></label>
      <button class='btn' id='captureGps'>Use GPS location</button>
      <p class='small'>Low connectivity is okay. You can update location later.</p>
    </section>`,
    3: `<section class='card onboard-card'><h2>Add your first field</h2><p class='small'>Just the basics to start recommendations.</p>
      <label>Field name<input id='fieldName' value='${onboardingDraft.fieldName}' placeholder='Field 1' /></label>
      <label>Crop<input id='crop' value='${onboardingDraft.crop}' placeholder='Maize, Tomato, Grapes…' /></label>
      <label>Acreage<input id='acreage' value='${onboardingDraft.acreage}' type='number' min='1' placeholder='10' /></label>
      <label>Units<select id='units'><option value='metric' ${onboardingDraft.units === "metric" ? "selected" : ""}>Metric</option><option value='imperial' ${onboardingDraft.units === "imperial" ? "selected" : ""}>Imperial</option></select></label>
    </section>`,
    4: `<section class='card onboard-card'><h2>Irrigation setup</h2><p class='small'>Not sure? You can skip this and update it later.</p>
      ${cardOptions([
        { value: "Drip", label: "Drip" },
        { value: "Sprinkler", label: "Sprinkler" },
        { value: "Pivot", label: "Pivot" },
        { value: "Flood", label: "Flood" },
      ], "irrigationMethod")}
      <label>Data availability</label>
      ${cardOptions([
        { value: "neither", label: "No sensors/controller", sub: "Manual tracking" },
        { value: "sensors", label: "Sensors only" },
        { value: "controller", label: "Controller only" },
        { value: "both", label: "Sensors + controller" },
      ], "dataSource")}
      <label>Hardware mode</label>
      ${cardOptions([
        { value: "manual", label: "Manual irrigation" },
        { value: "connected", label: "Connected hardware" },
      ], "hardware")}
      <label>Soil type (optional)<input id='soilType' value='${onboardingDraft.soilType}' placeholder='Loam, clay, sandy…' /></label>
      <label>Last irrigation date (optional)<input id='lastIrrigationAt' value='${onboardingDraft.lastIrrigationAt}' type='date' /></label>
      <label>Usual duration min (optional)<input id='usualDurationMin' value='${onboardingDraft.usualDurationMin}' type='number' min='1' /></label>
      <label>Water source (optional)<input id='waterSource' value='${onboardingDraft.waterSource}' placeholder='Canal, borehole, reservoir' /></label>
    </section>`,
  };

  return `${progressDots()}${stepCards[onboardingStep]}
    <div class='onboard-actions'>
      <button class='btn' data-prev-step='1'>Back</button>
      <button class='btn brand' data-onboard-continue='1'>${onboardingStep === 4 ? "Save and continue" : "Save and continue"}</button>
    </div>`;
}

function content() {
  if (!state.onboarded) return onboardingFlow();
  if (route === "today") return todayContent();
  if (route === "fields") return fieldsContent();
  if (route === "alerts") return alertsContent();
  if (route === "assistant") return assistantContent();
  if (route === "reports") return reportsContent();
  return settingsContent();
}

function render() {
  const sync = syncService.status();
  app.innerHTML = `<div class='shell ${!state.onboarded ? "shell-onboard" : ""}'><header class='top'><div><p class='small'>AGRO-AI</p><h1>${tr("appName")}</h1><p class='small'>${tr("framing")}</p></div><div><span class='small'>${sync.state}${sync.pending ? ` (${sync.pending})` : ""}</span></div></header>${content()}${state.onboarded ? `<nav class='bottom'>${nav.map((n) => `<button class='btn nav ${route === n ? "active" : ""}' data-nav='${n}'>${n}</button>`).join("")}</nav>` : ""}</div>`;
  bind();
}

function readDraftInputs() {
  const assign = (id, key = id) => {
    const el = document.getElementById(id);
    if (el) onboardingDraft[key] = el.value;
  };
  assign("language");
  assign("farmName");
  assign("farmLocation");
  assign("fieldName");
  assign("crop");
  assign("acreage");
  assign("units");
  assign("soilType");
  assign("lastIrrigationAt");
  assign("usualDurationMin");
  assign("waterSource");
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

  app.querySelectorAll("[data-next-step]").forEach((b) => (b.onclick = () => { onboardingStep = Number(b.dataset.nextStep); render(); }));
  app.querySelectorAll("[data-prev-step]").forEach((b) => (b.onclick = () => { readDraftInputs(); onboardingStep = Math.max(0, onboardingStep - 1); render(); }));
  app.querySelectorAll("[data-onboard-choice]").forEach((b) => (b.onclick = () => { onboardingDraft[b.dataset.onboardChoice] = b.dataset.value; render(); }));

  const continueBtn = document.querySelector("[data-onboard-continue='1']");
  if (continueBtn) continueBtn.onclick = async () => {
    readDraftInputs();
    if (onboardingStep < 4) {
      onboardingStep += 1;
      render();
      return;
    }

    state = applyOnboarding(state, {
      ...onboardingDraft,
      coordinates: onboardingDraft.coordinates,
    });
    route = "today";
    persist();
    await refreshWeather(true);
    render();
  };

  const gpsBtn = document.getElementById("captureGps");
  if (gpsBtn) gpsBtn.onclick = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        onboardingDraft.coordinates = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        onboardingDraft.farmLocation = `${pos.coords.latitude.toFixed(3)}, ${pos.coords.longitude.toFixed(3)}`;
        render();
      },
      () => { /* manual fallback stays available */ }
    );
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
