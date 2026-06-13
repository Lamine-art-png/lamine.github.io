import { translations } from "./i18n/translations.js";
import { syncService } from "./services/sync.js";
import { applyVoiceAction, parseVoiceCommand, saveOfflineVoiceAction } from "./services/voiceAgent.js";
import { weatherService } from "./services/weatherService.js";
import { apiClient } from "./services/apiClient.js";
import { actionMappingFor, alertFingerprint, alertGroup, alertKey, confidencePresentation, dedupeActivityRows, escapeHtml, confidenceText, isAlertDismissed, normalizeDecisionAction, readConfidence, recommendationContextLabel, relativeTime, shortDate, sortAlerts, weatherAgeLabel } from "./services/uiHelpers.js";
import { applyDemoScenario, applyOnboarding, loadState, recordRecommendationHistory, saveState, useDemoMode } from "./state/store.js";
import { createIrrigationLog, createObservation, createVoiceTimelineEntry } from "./state/actions.js";
import { createAiOrchestrator } from "./ai/aiOrchestrator.js";
import { memoryStore } from "./ai/memoryStore.js";
import { appendLedgerEvent, appendRecommendationEventIfNew, fieldObservationEvent, recommendationFingerprint, waterAppliedEvent, waterRecommendationEvent } from "./domain/fieldLedger.js";
import { terrisModuleRegistryForMode } from "./domain/moduleRegistry.js";
import { createNutrientRecord, nutrientLedgerEvent } from "./domain/nutrients.js";
import { compareEligibleWindows, demoEnergyComparison } from "./domain/energy.js";
import { completeFieldTask, createFieldTask, taskEvent } from "./domain/ops.js";
import { createEvidencePacket, evidencePacketEvent, evidenceReviewSignature, filterEvidenceEvents, reviewRowsForEvents, TERRIS_PROOF_DISCLAIMER } from "./domain/proof.js";

const app = document.getElementById("app");
const h = escapeHtml;
let state = loadState();
let route = "today";
let selectedField = null;
let fieldSearch = "";
let fieldFilter = "all";
let voiceListening = false;
let transcript = "";
let pendingVoiceCommand = null;
let voiceResponse = "Tap the orb and Terris will prepare a local transcript preview.";
let assistantResponse = "Ask about irrigation, weather risk, missing data, or what changed since yesterday.";
let assistantFieldId = state.fields[0]?.id || "";
let weather = state.weatherCache || null;
let decisionRefreshInflight = new Set();
let renderRecommendationSnapshot = new Map();
let uiMessage = "";
let proofReviewSnapshot = null;
let onboardingStep = 0;
let onboardingDraft = {
  role: "farmer",
  language: "en",
  farmName: "",
  farmLocation: "",
  coordinates: null,
  fieldName: "",
  fieldLocation: "",
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

const moduleState = (key, mode = state.mode) => terrisModuleRegistryForMode(mode).find((module) => module.key === key) || null;
function isTerrisModuleEnabled(key, mode = state.mode) {
  return Boolean(moduleState(key, mode)?.enabled);
}

function representativeDemoFor(key) {
  return Boolean(moduleState(key, state.mode)?.representativeDemo);
}

const bootParams = new URLSearchParams(window.location.search);
const acceptanceDemo = bootParams.get("demo") === "1";
if (acceptanceDemo) {
  state = useDemoMode(state);
  route = bootParams.get("screen") || "today";
  assistantFieldId = bootParams.get("field") || state.fields[0]?.id || "";
  if (bootParams.get("screen") === "field-detail") {
    route = "fields";
    selectedField = { type: "detail", fieldId: bootParams.get("field") || state.fields[0]?.id };
  }
  saveState(state);
}

const nav = [
  { id: "today", label: "Today" },
  { id: "fields", label: "Fields" },
  { id: "assistant", label: "Ask Terris", featured: true },
  { id: "alerts", label: "Alerts" },
  { id: "more", label: "More" },
];
const tr = (k) => translations[state.language || "en"]?.[k] || translations.en[k] || k;

function buildAiContext({ preview = true } = {}) {
  return {
    getFarmProfile: () => state.profile?.farm || {},
    getFieldProfile: (fieldId) => state.fields.find((f) => f.id === fieldId) || state.fields[0] || {},
    getWeather: () => weather || {},
    getIrrigationLogs: (fieldId) => state.irrigationLogs.filter((x) => x.fieldId === fieldId).slice(0, 10),
    getFieldObservations: (fieldId) => state.observations.filter((x) => x.fieldId === fieldId).slice(0, 10),
    getRecommendationHistory: (fieldId) => state.recommendationHistory.filter((x) => x.fieldId === fieldId).slice(0, 10),
    saveIrrigationLog: (payload) => ({ ok: true, payload }),
    saveFieldObservation: (payload) => ({ ok: true, payload }),
    saveVoiceNote: (payload) => ({ ok: true, payload }),
    calculateWaterBalance: (field, weatherData) => ({ waterBalanceScore: Math.max(0, 1 - (weatherData?.rainChance || 0) / 100 + (field?.waterStressLevel === "high" ? 0.2 : 0)) }),
    estimateIrrigationNeed: ({ field, weather: weatherData, observations }) => {
      const obs = observations?.[0]?.condition || field?.lastObservation || "";
      let score = field?.waterStressLevel === "high" ? 0.8 : field?.waterStressLevel === "moderate" ? 0.6 : 0.3;
      if ((weatherData?.heatRisk || "") === "elevated" || (weatherData?.heatRisk || "") === "high") score += 0.15;
      if ((weatherData?.rainChance || 0) > 55) score -= 0.2;
      if (/dry|stress|wilting/i.test(obs)) score += 0.1;
      if (/too wet|damp|moist/i.test(obs)) score -= 0.2;
      return { needScore: Math.max(0, Math.min(1, score)) };
    },
    calculateConfidence: ({ missingData, needScore }) => Math.max(0.2, Math.min(0.95, (needScore || 0.6) - ((missingData?.length || 0) * 0.08))),
    generateExplanation: ({ decision }) => `Terris checked weather, field profile, observations, and recent irrigation before recommending ${decision?.action || "monitoring"}.`,
    isPreviewRender: () => preview,
  };
}

function ai() { return createAiOrchestrator(buildAiContext({ preview: true })); }
function persist() { saveState(state); }
function syncStatus() { return syncService.status(); }

function reconcileLedgerSyncMetadata({ persistState = true } = {}) {
  const pending = syncService.status().pending > 0;
  const previous = state.ledgerMetadata || {};
  state.ledgerMetadata = { ...previous, queuedForSync: pending };
  if (persistState) persist();
  return pending;
}

function queueSyncAction(action) {
  const pending = syncService.queueAction(action);
  reconcileLedgerSyncMetadata({ persistState: false });
  return pending;
}

async function refreshWeather(forceRefresh = false) {
  const location = state.profile?.farm?.location || "farm";
  weather = await weatherService.getWeather({ location, coordinates: state.profile?.farm?.coordinates || state.fields[0]?.coordinates || null, forceRefresh });
  state.weatherCache = weather;
  if (state.onboarded) recordLocalRecommendationTransitions();
  persist();
}

function showMessage(text) {
  uiMessage = text;
  setTimeout(() => {
    if (uiMessage === text) {
      uiMessage = "";
      render();
    }
  }, 2800);
}

function addIrrigationLog(payload) {
  const offline = !navigator.onLine;
  const log = createIrrigationLog({ ...payload, offline });
  state.irrigationLogs.unshift(log);
  const field = state.fields.find((f) => f.id === payload.fieldId);
  if (field) {
    field.lastIrrigationAt = log.performedAt;
    field.updatedAt = new Date().toISOString();
  }
  state = appendLedgerEvent(state, waterAppliedEvent(log));
  if (field) recordLocalRecommendationTransitions([field]);
  if (offline) queueSyncAction({ kind: "irrigation_log", payload: log });
  persist();
  showMessage(navigator.onLine ? "Irrigation log saved." : "Saved offline. Terris will sync when connected.");
}

function addFieldNote(payload) {
  const note = { id: `note-${Date.now()}`, createdAt: new Date().toISOString(), ...payload };
  state.fieldNotes.unshift(note);
  if (!navigator.onLine) queueSyncAction({ kind: "field_note", payload: note });
  persist();
  showMessage(navigator.onLine ? "Field note added." : "Field note saved offline.");
}

function updateCondition(payload) {
  const offline = !navigator.onLine;
  const observation = createObservation({ ...payload, offline });
  state.observations.unshift(observation);
  const field = state.fields.find((f) => f.id === payload.fieldId);
  if (field) {
    field.lastObservation = payload.condition;
    field.updatedAt = new Date().toISOString();
  }
  state = appendLedgerEvent(state, fieldObservationEvent(observation));
  if (field) recordLocalRecommendationTransitions([field]);
  if (offline) queueSyncAction({ kind: "observation", payload: observation });
  persist();
  showMessage(navigator.onLine ? "Condition updated." : "Condition saved offline.");
}

function recordRecommendationLedgerEvent(field, recommendation, options = {}) {
  const sourceMode = options.sourceMode || recommendation.sourceMode || "local";
  const fingerprint = recommendationFingerprint({
    fieldId: field.id,
    recommendation,
    sourceMode,
    decisionVersion: options.decisionVersion,
    occurredAt: options.occurredAt || new Date().toISOString(),
    decisionTraceRef: recommendation.decisionTrace?.id || recommendation.decisionTrace?.traceId,
  });
  const result = appendRecommendationEventIfNew(state, waterRecommendationEvent({ field, recommendation: { ...recommendation, sourceMode }, weather, fingerprint }));
  state = result.state;
  return result.appended;
}

function computeLocalRecommendationForTransition(field) {
  if (state.mode === "demo" && field.demoRecommendation) {
    return { ...field.demoRecommendation, sourceMode: "demo", verificationStatus: field.verificationStatus || "needs field confirmation" };
  }
  const result = ai().runGoal({ goal: "daily irrigation decision", fieldId: field.id, language: state.language || "en" });
  return { ...result.decision, sourceMode: weather?.stale ? "offline" : "local", verificationStatus: field.verificationStatus || result.verification?.status || "needs field confirmation" };
}

function recordLocalRecommendationTransitions(fields = state.fields) {
  let changed = false;
  for (const field of fields) {
    if (!field) continue;
    const recommendation = computeLocalRecommendationForTransition(field);
    changed = recordRecommendationLedgerEvent(field, recommendation, { sourceMode: recommendation.sourceMode }) || changed;
  }
  return changed;
}

function computeRecommendation(field) {
  if (state.mode === "demo" && field.demoRecommendation) {
    return { ...field.demoRecommendation, sourceMode: "demo", verificationStatus: field.verificationStatus || "needs field confirmation" };
  }
  const result = ai().runGoal({ goal: "daily irrigation decision", fieldId: field.id, language: state.language || "en" });
  const localRec = result.decision;
  const cached = state.remoteDecisions?.[field.id];
  const freshCached = cached && Date.now() - new Date(cached.fetchedAt).getTime() < 10 * 60 * 1000;
  const rec = freshCached
    ? { ...cached.decision, sourceMode: "backend" }
    : { ...localRec, sourceMode: decisionRefreshInflight.has(field.id) ? "refreshing" : (weather?.stale ? "offline" : "local") };
  return { ...rec, verificationStatus: field.verificationStatus || result.verification?.status || "needs field confirmation" };
}

function prepareRecommendationSnapshot() {
  renderRecommendationSnapshot = new Map(state.fields.map((field) => [field.id, computeRecommendation(field)]));
}

function recommendationFor(field) {
  return renderRecommendationSnapshot.get(field.id) || computeRecommendation(field);
}

function scheduleDecisionRefreshes() {
  if (acceptanceDemo || state.mode === "demo" || !navigator.onLine) return;
  for (const field of state.fields) {
    const cached = state.remoteDecisions?.[field.id];
    const freshCached = cached && Date.now() - new Date(cached.fetchedAt).getTime() < 10 * 60 * 1000;
    if (!freshCached && !decisionRefreshInflight.has(field.id)) refreshRemoteDecision(field);
  }
}

async function refreshRemoteDecision(field) {
  decisionRefreshInflight.add(field.id);
  renderSoon();
  try {
    const result = await apiClient.getDailyDecision({
      field,
      weather,
      location: state.profile?.farm || null,
      logs: state.irrigationLogs.filter((x) => x.fieldId === field.id).slice(0, 10),
      observations: state.observations.filter((x) => x.fieldId === field.id).slice(0, 10),
      language: state.language || "en",
    });
    if (result?.decision) {
      state.remoteDecisions = { ...(state.remoteDecisions || {}), [field.id]: { decision: result.decision, fetchedAt: new Date().toISOString() } };
      state = recordRecommendationHistory(state, field.id, result.decision);
      recordRecommendationLedgerEvent(field, result.decision, { sourceMode: "backend", decisionVersion: result.decision?.decisionVersion || result.decision?.version });
      memoryStore.updateFieldMemory(field.id, { type: "decision", payload: result.decision });
      persist();
    }
  } catch {
    showMessage("Using local intelligence until the backend is reachable.");
  } finally {
    decisionRefreshInflight.delete(field.id);
    render();
  }
}

let renderTimer = null;
function renderSoon() {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(render, 60);
}

async function fetchAssistantText(fieldId, query = "Should I irrigate today?") {
  const fallback = ai().runGoal({ goal: "explain recommendation", fieldId: fieldId || state.fields[0]?.id || "" }).text || "Terris can explain the latest recommendation using local field context.";
  if (!navigator.onLine) return `${fallback} Offline mode is active, so this answer used local context.`;
  try {
    const latest = state.recommendationHistory.find((x) => !fieldId || x.fieldId === fieldId)?.rec || null;
    const result = await apiClient.queryAssistant({ query, fieldId, decision: latest, recommendationHistory: state.recommendationHistory, language: state.language || "en" });
    return result.answer || fallback;
  } catch {
    return `${fallback} Backend was unavailable, so Terris used local fallback.`;
  }
}

function confidenceClass(value) {
  const c = confidenceText(value).toLowerCase();
  if (c.includes("high")) return "high";
  if (c.includes("low")) return "low";
  return "moderate";
}

function actionTitle(rec, field) {
  const action = normalizeDecisionAction(rec.action);
  if (action === "irrigate") return `Irrigate ${field.name}`;
  if (action === "wait") return `Wait before irrigating ${field.name}`;
  if (action === "update missing data") return `Complete data for ${field.name}`;
  if (action === "check field first") return `Check ${field.name} before irrigating`;
  return `Monitor ${field.name}`;
}

function actionAttribute(kind, fieldId) {
  const id = h(fieldId);
  if (kind === "log") return `data-open-log="${id}"`;
  if (kind === "condition") return `data-open-condition="${id}"`;
  if (kind === "assistant") return `data-nav="assistant" data-assistant-field="${id}"`;
  if (kind === "reasoning") return `data-scroll-provenance="1"`;
  if (kind === "weather") return `data-nav="alerts"`;
  if (kind === "field-detail") return `data-open-field="${id}"`;
  if (kind === "reminder") return `data-set-reminder="${id}"`;
  return `data-open-condition="${id}"`;
}

function actionButtons(rec, field, compact = false) {
  const mapping = actionMappingFor(rec.action);
  return `<div class="${compact ? "card-actions" : "hero-actions"}"><button class="btn brand" ${actionAttribute(mapping.primaryAction, field.id)}>${h(mapping.primary)}</button><button class="btn" ${actionAttribute(mapping.secondaryAction, field.id)}>${h(mapping.secondary)}</button></div>`;
}

function riskFor(field, rec) {
  if (weather?.stale || rec.sourceMode === "offline") return "Stale offline fallback";
  if (field.verificationStatus === "overdue" || confidenceText(readConfidence(rec)).toLowerCase() === "low") return "Verify today";
  if (weather?.heatRisk === "high" || weather?.heatRisk === "elevated") return "Heat pressure";
  if ((weather?.rainChance || 0) > 55) return "Rain watch";
  return "Stable";
}

function emptyState(title, body, action = "") {
  return `<section class="empty-state"><div class="empty-mark"></div><h3>${h(title)}</h3><p>${h(body)}</p>${action}</section>`;
}

function confidenceBadge(confidence) {
  const display = confidencePresentation(confidence);
  const score = display.numeric == null ? "" : ` ${display.numeric}%`;
  return `<span class="confidence ${confidenceClass(display.label)}">${h(display.label)} confidence${h(score)}</span>`;
}

function confidenceBlock(rec) {
  const display = confidencePresentation(readConfidence(rec), rec);
  return `<div class="confidence-copy"><strong>${h(display.label)} confidence${display.numeric == null ? "" : ` ${display.numeric}%`}</strong><p>${h(display.explanation)}</p><small>${h(display.improve)}</small></div>`;
}

function riskBadge(label, severity = "normal") {
  return `<span class="risk-badge ${h(severity)}">${h(label)}</span>`;
}

function skeletonDecision() {
  return `<section class="card hero-card skeleton-card" data-testid="decision-loading">
    <div class="skeleton line wide"></div><div class="skeleton line title"></div><div class="skeleton line"></div><div class="skeleton row"><span></span><span></span></div>
  </section>`;
}

function mapPlaceholder(field) {
  if (field.coordinates) {
    const lat = Number(field.coordinates.lat).toFixed(3);
    const lon = Number(field.coordinates.lon).toFixed(3);
    return `<section class="map-card">
      <div class="map-grid"></div>
      <div><p class="card-label">Map-ready field</p><h3>${h(field.name)}</h3><p>${h(lat)}, ${h(lon)}</p><p class="muted">Boundary-ready foundation. Satellite imagery is not live yet.</p></div>
    </section>`;
  }
  return `<section class="map-card empty-map">
    <div class="map-pin"></div>
    <div><p class="card-label">Map-ready field</p><h3>Add field location to unlock map-based intelligence.</h3><p class="muted">Terris will use coordinates for weather context and future field-boundary workflows.</p></div>
  </section>`;
}

function provenanceSection(rec) {
  const p = rec.provenance || {};
  const sources = p.ragSourcesUsed || rec.knowledgeSources || [];
  const data = p.dataSourcesChecked || rec.decisionTrace?.dataChecked || ["field profile", "weather", "recent logs", "observations"];
  const missing = p.missingData || rec.missingData || [];
  return `<details class="accordion provenance-card" data-testid="provenance-disclosure">
    <summary>Why Terris recommended this</summary>
    <div class="provenance-grid">
      <div><span>Data checked</span><p>${h(data.slice(0, 5).map((x) => String(x).replaceAll("_", " ")).join(", "))}</p></div>
      <div><span>Weather</span><p>${h(p.weatherSource || weather?.weatherSource || weather?.source || "Weather context")} - ${h(weatherAgeLabel(weather))}${p.weatherStale || weather?.stale ? " - stale" : ""}</p></div>
      <div><span>Uncertainty</span><p>${h((missing.length ? missing : rec.uncertainties || ["No major gap reported"]).slice(0, 3).join(", "))}</p></div>
      <div><span>Improve confidence</span><p>${h((rec.fieldChecks || ["Record a field observation"]).slice(0, 2).join(", "))}</p></div>
      <div><span>Guidance</span><p>${h(sources.slice(0, 3).map((s) => s.title || s.topic || "Irrigation guidance").join(", ") || "Local irrigation guidance")}</p></div>
    </div>
  </details>`;
}

function fieldCard(field, compact = false) {
  const rec = recommendationFor(field);
  const risk = riskFor(field, rec);
  return `<article class="field-card ${compact ? "compact" : ""}" data-status="${h(rec.urgency || "medium")}">
    <div class="field-status-dot ${h(rec.urgency || "medium")}"></div>
    <div class="field-card-main">
      <div class="field-title-row"><h3>${h(field.name)}</h3>${riskBadge(risk, risk.includes("Verify") || risk.includes("fresh") ? "watch" : "normal")}</div>
      <p>${h(field.crop || "Crop not set")} - ${h(field.acreage || "0")} acres</p>
      <p class="muted">${h(field.irrigationMethod || "Irrigation method missing")} - ${h(field.lastObservation || "No recent condition")}</p>
      <div class="card-metrics">
        ${confidenceBadge(readConfidence(rec))}
        <span>${h(normalizeDecisionAction(rec.action))}</span>
        <span>${h(relativeTime(field.updatedAt || field.lastIrrigationAt))}</span>
      </div>
    </div>
    <button class="icon-button" data-open-field="${h(field.id)}" aria-label="Open ${h(field.name)}">View</button>
  </article>`;
}

function recentActivity(limit = 5) {
  const rows = dedupeActivityRows([
    ...state.irrigationLogs.map((x) => ({ at: x.performedAt, title: "Irrigation logged", body: `${fieldName(x.fieldId)} - ${x.durationMin} min`, fieldId: x.fieldId })),
    ...state.observations.map((x) => ({ at: x.createdAt, title: "Condition updated", body: `${fieldName(x.fieldId)} - ${x.condition}`, fieldId: x.fieldId })),
    ...state.fieldNotes.map((x) => ({ at: x.createdAt, title: "Note captured", body: `${fieldName(x.fieldId)} - ${x.text}`, fieldId: x.fieldId })),
    ...state.recommendationHistory.map((x) => ({ at: x.at, title: x.eventType === "recommendation changed" ? "Recommendation changed" : "Recommendation refreshed", body: `${fieldName(x.fieldId)} - ${x.rec?.action || x.rec?.urgency || "review"}`, fieldId: x.fieldId })),
  ], { limit });
  if (!rows.length) return emptyState("No activity yet", "Logs, field checks, and verified recommendations will appear here.");
  return `<div class="activity-list">${rows.map((row) => `<div class="activity-row"><span></span><div><strong>${h(row.title)}</strong><p>${h(row.body)}</p></div><time>${h(relativeTime(row.at))}</time></div>`).join("")}</div>`;
}

function fieldName(fieldId) {
  return state.fields.find((f) => f.id === fieldId)?.name || "Field";
}

function buildChanges(field, rec) {
  const changes = [];
  if (weather?.stale) changes.push(["Weather needs refresh", "Using cached weather until the connection improves."]);
  if ((weather?.rainChance || 0) >= 50) changes.push(["Rain probability increased", `${weather.rainChance}% rain chance is now part of the decision.`]);
  if (weather?.heatRisk === "high" || weather?.heatRisk === "elevated") changes.push(["Heat pressure elevated", "Terris is weighing afternoon demand more carefully."]);
  const lastObs = state.observations.find((o) => o.fieldId === field.id);
  if (lastObs) changes.push(["New field observation", `${field.name}: ${lastObs.condition}.`]);
  if (rec.sourceMode === "backend") changes.push(["Backend decision synced", "Terris refreshed the recommendation with server-side intelligence."]);
  if (!changes.length) changes.push(["No major overnight shift", "Weather, logs, and observations remain consistent."]);
  return `<section class="card section-card"><div class="section-heading"><p class="card-label">What changed overnight</p></div>${changes.slice(0, 4).map(([title, body]) => `<div class="change-row"><strong>${h(title)}</strong><p>${h(body)}</p></div>`).join("")}</section>`;
}

function todayContent() {
  const field = state.fields[0];
  if (!field) return emptyState("Set up your first field", "Terris needs at least one field profile before it can brief you.", `<button class="btn brand" data-next-step="1">Start setup</button>`);
  const rec = recommendationFor(field);
  const attentionFields = state.fields.filter((f) => {
    const r = recommendationFor(f);
    return r.urgency !== "low" || confidenceText(readConfidence(r)).toLowerCase() === "low" || f.verificationStatus === "overdue";
  });
  const irrigationCount = attentionFields.filter((f) => normalizeDecisionAction(recommendationFor(f).action) === "irrigate").length;
  return `<section class="screen today-screen">
    <section class="morning-brief">
      <div><p class="eyebrow">Good morning</p><h1>${h(state.profile?.farm?.name || "Your farm")}</h1><p>${h(shortDate())} - ${h(weather?.forecastSummary || "Weather context is loading.")}</p></div>
      <div class="weather-pill"><strong>${h(weather?.temperature ?? "--")}°</strong><span>${h(weatherAgeLabel(weather))}</span></div>
    </section>
    ${decisionRefreshInflight.has(field.id) ? skeletonDecision() : ""}
    <section class="card hero-card urgency-${h(rec.urgency || "medium")}">
      <div class="hero-kicker"><span>${h(field.name)}</span>${confidenceBadge(readConfidence(rec))}</div>
      <h2>${h(actionTitle(rec, field))}</h2>
      <p class="field-context-line">${h(field.crop || "Crop not set")} - ${h(field.acreage || "0")} acres - ${h(field.irrigationMethod || "Irrigation method missing")}</p>
      <p>${h(rec.reasons?.[0] || rec.nextBestAction || "Terris checked field and weather signals for today's water decision.")}</p>
      <div class="hero-meta"><span>${h(rec.timing || "Today")}</span><span>${h(riskFor(field, rec))}</span><span>${h(recommendationContextLabel(rec, weather, state.mode))}</span></div>
      ${confidenceBlock(rec)}
      ${actionButtons(rec, field)}
    </section>
    ${buildChanges(field, rec)}
    <section class="section-card unframed"><div class="section-heading"><p class="card-label">Fields needing attention</p><button class="link-button" data-nav="fields">View all</button></div><div class="field-carousel">${attentionFields.length ? attentionFields.map((f) => fieldCard(f, true)).join("") : emptyState("No field needs urgent attention", "Terris will surface changes when weather, logs, or observations shift.")}</div></section>
    <section class="outlook-grid">
      <div class="outlook-ring"><span>${h(irrigationCount)}</span><p>irrigation priorities</p></div>
      <div class="card outlook-card"><p class="card-label">Daily water outlook</p><div class="water-strip"><span style="width:${Math.min(100, Math.max(8, (weather?.rainChance || 0)))}%"></span></div><p>Rain ${h(weather?.rainChance ?? "n/a")}% - Heat ${h(weather?.heatRisk || "unknown")} - ${h(attentionFields.length)} fields to review</p></div>
    </section>
    <section class="ask-entry" data-nav="assistant"><p>What do you need help with today?</p><button class="btn brand" data-nav="assistant">Ask Terris</button></section>
    <section class="card section-card"><p class="card-label">Recent activity</p>${recentActivity(4)}</section>
    ${provenanceSection(rec)}
  </section>`;
}

function quickLogForm(fieldId) {
  return `<section class="screen"><button class="link-button back" data-back-fields="1">Back to fields</button><section class="card form-card"><h2>Log irrigation</h2>
    <label>Field<select id="logField">${state.fields.map((f) => `<option value="${h(f.id)}" ${f.id === fieldId ? "selected" : ""}>${h(f.name)}</option>`).join("")}</select></label>
    <label>Date and time<input id="logDate" type="datetime-local" /></label>
    <label>Duration (minutes)<input id="logDuration" type="number" min="1" placeholder="60"/></label>
    <label>Water amount mm (optional)<input id="logAmount" type="number" min="0" /></label>
    <label>Note (optional)<input id="logNote" /></label>
    <button class="btn brand" data-save-log="1">Save irrigation log</button>
  </section></section>`;
}

function conditionForm(fieldId) {
  const options = ["Looks normal", "Looks dry", "Looks too wet", "Leaves look stressed", "I am not sure"];
  return `<section class="screen"><button class="link-button back" data-back-fields="1">Back to fields</button><section class="card form-card"><h2>Update field condition</h2>
    <label>Field<select id="conditionField">${state.fields.map((f) => `<option value="${h(f.id)}" ${f.id === fieldId ? "selected" : ""}>${h(f.name)}</option>`).join("")}</select></label>
    <label>Condition<select id="conditionValue">${options.map((o) => `<option>${h(o)}</option>`).join("")}</select></label>
    <button class="btn brand" data-save-condition="1">Save condition</button>
  </section></section>`;
}

function fieldsContent() {
  if (selectedField?.type === "log") return quickLogForm(selectedField.fieldId);
  if (selectedField?.type === "condition") return conditionForm(selectedField.fieldId);
  if (selectedField?.type === "detail") return fieldDetail(selectedField.fieldId);
  const filtered = state.fields.filter((field) => {
    const rec = recommendationFor(field);
    const matches = `${field.name} ${field.crop} ${field.location}`.toLowerCase().includes(fieldSearch.toLowerCase());
    const status = fieldFilter === "all" || String(rec.urgency || "").toLowerCase() === fieldFilter || riskFor(field, rec).toLowerCase().includes(fieldFilter);
    return matches && status;
  });
  return `<section class="screen fields-screen">
    <div class="screen-heading"><div><p class="eyebrow">Fields</p><h1>Every block, one calm view</h1></div><button class="btn compact" data-open-condition="${h(state.fields[0]?.id || "")}">Add check</button></div>
    <section class="toolbar-card"><input id="fieldSearch" value="${h(fieldSearch)}" placeholder="Search fields" /><div class="segmented">${["all", "high", "medium", "low", "verify"].map((x) => `<button class="${fieldFilter === x ? "active" : ""}" data-filter="${h(x)}">${h(x)}</button>`).join("")}</div></section>
    <section class="field-list">${filtered.length ? filtered.map((f) => fieldCard(f)).join("") : emptyState("No fields match", "Try a different status filter or search term.")}</section>
  </section>`;
}

function fieldDetail(fieldId) {
  const f = state.fields.find((x) => x.id === fieldId) || state.fields[0];
  if (!f) return emptyState("Field not found", "Return to fields and choose another block.");
  const rec = recommendationFor(f);
  const logs = state.irrigationLogs.filter((x) => x.fieldId === fieldId).slice(0, 6);
  const notes = state.fieldNotes.filter((x) => x.fieldId === fieldId).slice(0, 6);
  const observations = state.observations.filter((x) => x.fieldId === fieldId).slice(0, 6);
  return `<section class="screen field-detail-screen">
    <button class="link-button back" data-back-fields="1">Back to fields</button>
    <section class="field-hero"><div><p class="eyebrow">${h(f.crop || "Field")}</p><h1>${h(f.name)}</h1><p>${h(f.location || "Location not set")} - ${h(f.acreage || "0")} acres</p></div>${riskBadge(riskFor(f, rec), "watch")}</section>
    ${mapPlaceholder(f)}
    <section class="detail-grid">
      <article class="card"><p class="card-label">Today's recommendation</p><h2>${h(actionTitle(rec, f))}</h2><p>${h(rec.nextBestAction || rec.reasons?.[0] || "Check the field and log what you see.")}</p>${confidenceBlock(rec)}</article>
      <article class="card"><p class="card-label">Weather context</p><p>${h(weather?.forecastSummary || "Weather context unavailable.")}</p><div class="card-metrics"><span>Rain ${h(weather?.rainChance ?? "n/a")}%</span><span>Heat ${h(weather?.heatRisk || "unknown")}</span></div></article>
      <article class="card"><p class="card-label">Data sources</p><div class="data-source-list"><span>Sensor: ${h(f.sensorData ? "available" : "not connected")}</span><span>Controller: ${h(f.controllerStatus || f.dataSource || "not connected")}</span><span>Verification: ${h(f.verificationStatus || "not confirmed")}</span></div></article>
    </section>
    <section class="card section-card"><p class="card-label">Timeline</p>${timelineRows([...logs.map((x) => ["Irrigation", `${x.durationMin} min`, x.performedAt]), ...observations.map((x) => ["Observation", x.condition, x.createdAt]), ...notes.map((x) => ["Note", x.text, x.createdAt])])}</section>
    <section class="field-actions">${actionButtons(rec, f, true)}<button class="btn" data-nav="assistant" data-assistant-field="${h(f.id)}">Ask Terris about this field</button></section>
    ${provenanceSection(rec)}
  </section>`;
}

function timelineRows(rows) {
  const sorted = rows.sort((a, b) => new Date(b[2]) - new Date(a[2])).slice(0, 8);
  if (!sorted.length) return emptyState("No field timeline yet", "Logs, notes, and observations will appear here.");
  return `<div class="timeline">${sorted.map(([type, body, at]) => `<div class="timeline-row"><span></span><div><strong>${h(type)}</strong><p>${h(body)}</p></div><time>${h(relativeTime(at))}</time></div>`).join("")}</div>`;
}

function assistantContent() {
  const field = state.fields.find((f) => f.id === assistantFieldId) || state.fields[0];
  const suggestions = ["Should I irrigate today?", "Which field needs attention first?", "Why did the recommendation change?", "What information are you missing?", "What should I check in the field?", "Did yesterday's irrigation help?", "What is the rain risk this week?"];
  return `<section class="screen assistant-screen">
    <div class="screen-heading"><div><p class="eyebrow">Ask Terris</p><h1>Field intelligence, in conversation</h1></div></div>
    <section class="chat-panel">
      <label class="field-select">Context field<select id="assistantField">${state.fields.map((f) => `<option value="${h(f.id)}" ${f.id === field?.id ? "selected" : ""}>${h(f.name)}</option>`).join("")}</select></label>
      <div class="message assistant"><span>Terris</span><p>${h(assistantResponse)}</p><details><summary>Source and confidence</summary><p>${h(field ? `${field.name}, weather context, recent logs, and local fallback when needed.` : "Farm context will appear after setup.")}</p></details></div>
      <div class="suggestions">${suggestions.map((q) => `<button class="chip" data-assistant-query="${h(q)}">${h(q)}</button>`).join("")}</div>
      <div class="ask-box"><input id="assistantInput" placeholder="Ask about water, weather, or a field check" /><button class="btn brand" data-send-assistant="1">Send</button></div>
    </section>
    ${voiceCard(field?.id || "", field ? recommendationFor(field) : null)}
    <section class="card section-card"><p class="card-label">Recent conversations</p>${state.voiceTimeline.length ? timelineRows(state.voiceTimeline.map((x) => ["Voice", x.transcript || x.intent, x.createdAt])) : emptyState("No conversations yet", "Questions and voice notes will appear here.")}</section>
  </section>`;
}

function voiceCard(fieldId, rec) {
  const sync = syncStatus();
  return `<section class="voice-card">
    <div class="voice-copy"><p class="card-label">Voice field agent</p><h2>${voiceListening ? "Listening for a field note" : "Speak naturally"}</h2><p>${h(voiceListening ? "Tap again when you are done. Terris will show a confirmation before saving." : "Voice uses local parsing unless browser or provider support is available.")}</p></div>
    <button class="voice-orb ${voiceListening ? "listening" : ""}" data-voice="${h(fieldId)}" aria-label="Voice input"><span></span></button>
    <div class="voice-preview"><p><strong>Transcript</strong><br>${h(transcript || "No transcript yet")}</p><p><strong>Response</strong><br>${h(voiceResponse)}</p>${rec ? `<p>${confidenceBadge(readConfidence(rec))}</p>` : ""}${pendingVoiceCommand ? `<button class="btn brand" data-confirm-voice="1">Confirm and save</button>` : ""}${!sync.isOnline ? `<p class="warn">Offline-safe: actions will queue locally.</p>` : ""}</div>
  </section>`;
}

function buildAlerts() {
  const generated = [];
  const seenAlerts = { ...(state.alertFirstSeen || {}) };
  let firstSeenChanged = false;
  const addGeneratedAlert = (alert) => {
    const keyed = { ...alert, key: alert.key || alertKey(alert), id: alert.id || alert.key || alertKey(alert) };
    const fingerprint = alertFingerprint(keyed);
    const previous = seenAlerts[keyed.key];
    if (!previous || previous.fingerprint !== fingerprint) {
      seenAlerts[keyed.key] = { firstSeenAt: keyed.createdAt || new Date().toISOString(), fingerprint };
      firstSeenChanged = true;
    }
    keyed.createdAt = seenAlerts[keyed.key].firstSeenAt;
    if (!isAlertDismissed(keyed, state.dismissedAlerts || {})) generated.push(keyed);
  };
  for (const field of state.fields) {
    const rec = recommendationFor(field);
    if (weather?.heatRisk === "high" || weather?.heatRisk === "elevated") addGeneratedAlert({ type: "heat", severity: "medium", fieldId: field.id, conditionToken: `heat:${weather.heatRisk}`, createdAt: new Date().toISOString(), explanation: "Heat pressure may increase water demand.", action: "Check leaf stress before the afternoon.", resolved: false });
    if (weather?.frostRisk === "high" || weather?.frostRisk === "elevated") addGeneratedAlert({ type: "frost", severity: "high", fieldId: field.id, conditionToken: `frost:${weather.frostRisk}`, createdAt: new Date().toISOString(), explanation: "Frost risk can change irrigation timing.", action: "Confirm local frost protocol.", resolved: false });
    if (weather?.stale) addGeneratedAlert({ type: "stale weather", severity: "medium", fieldId: field.id, conditionToken: `weather:${weather.weatherTimestamp || weather.cachedAt || "stale"}`, createdAt: new Date().toISOString(), explanation: "Weather is cached or stale.", action: "Refresh weather when connected.", resolved: false });
    if (!field.lastObservation || field.verificationStatus === "overdue") addGeneratedAlert({ type: "verification", severity: "high", fieldId: field.id, conditionToken: `verification:${field.verificationStatus || "missing"}:${field.lastObservation || "none"}`, createdAt: field.updatedAt || new Date().toISOString(), explanation: "Terris needs a recent field observation.", action: "Record a field check.", resolved: false });
    if (!field.sensorData) addGeneratedAlert({ type: "sensor", severity: "low", fieldId: field.id, conditionToken: `sensor:${field.dataSource || "none"}`, createdAt: new Date().toISOString(), explanation: "No sensor reading is available.", action: "Use a manual observation to improve confidence.", resolved: false });
    if (confidenceText(readConfidence(rec)).toLowerCase() === "low") addGeneratedAlert({ type: "confidence", severity: "medium", fieldId: field.id, conditionToken: `confidence:${readConfidence(rec) || "low"}`, createdAt: new Date().toISOString(), explanation: "Decision confidence is low.", action: "Add crop, soil, weather, or observation data.", resolved: false });
  }
  if (firstSeenChanged) {
    state.alertFirstSeen = seenAlerts;
    persist();
  }
  return sortAlerts([...(state.alertHistory || []), ...generated].filter((a) => !a.resolved)).slice(0, 12);
}

function alertsContent() {
  const alerts = buildAlerts();
  const groups = ["Act now", "Review today", "Monitoring"].map((name) => [name, alerts.filter((alert) => alertGroup(alert) === name)]).filter(([, rows]) => rows.length);
  return `<section class="screen alerts-screen">
    <div class="screen-heading"><div><p class="eyebrow">Alerts</p><h1>Only what needs action</h1></div></div>
    <section class="alert-list">${groups.length ? groups.map(([name, rows]) => `<div class="alert-group"><h2>${h(name)}</h2>${rows.map((alert) => alertRow(alert)).join("")}</div>`).join("") : emptyState("No urgent alerts", "Terris is monitoring your fields.")}</section>
  </section>`;
}

function alertRow(alert) {
  return `<article class="alert-row ${h(alert.severity || "low")}">
    <div class="alert-severity"></div>
    <div><div class="field-title-row"><h3>${h(alert.type || "Alert")}</h3><span>${h(fieldName(alert.fieldId))}</span></div><p>${h(alert.explanation)}</p><strong>${h(alert.action)}</strong><time>${h(relativeTime(alert.createdAt))}</time></div>
    <button class="btn compact" data-resolve-alert="${h(alert.id || alertKey(alert))}" data-alert-fingerprint="${h(alertFingerprint(alert))}">Resolve</button>
  </article>`;
}

function moreContent() {
  const items = ["Reports", "Farm profile", "Fields setup", "Data sources", "Integrations", "Notifications", "Language", "Units", "Offline and sync", "Help", "About Terris"];
  return `<section class="screen more-screen">
    <div class="screen-heading"><div><p class="eyebrow">More</p><h1>Farm controls</h1></div></div>
    <section class="settings-list">${items.map((item) => `<button class="settings-row"><span>${h(item)}</span><small>${h(settingSubtitle(item))}</small></button>`).join("")}</section>
    <section class="card section-card"><p class="card-label">Offline and sync</p><p>${h(syncStatus().state)}${syncStatus().pending ? ` - ${h(syncStatus().pending)} queued` : ""}</p><button class="btn" data-refresh-weather="1">Refresh weather</button></section>
    ${terrisBetaContent()}
    ${state.mode === "demo" ? `<section class="card internal-card"><p class="card-label">Internal demo controls</p><label>Demo scenario<select id="demoScenario"><option value="baseline" ${state.demoScenario === "baseline" ? "selected" : ""}>Napa baseline</option><option value="hotDry" ${state.demoScenario === "hotDry" ? "selected" : ""}>Hot and dry</option><option value="coolWet" ${state.demoScenario === "coolWet" ? "selected" : ""}>Rain watch</option></select></label><button class="btn" data-apply-scenario="1">Apply scenario</button><button class="btn" data-mode="real">Leave demo mode</button></section>` : ""}
  </section>`;
}

function terrisBetaContent() {
  const modules = terrisModuleRegistryForMode(state.mode);
  const betaRows = modules.filter((module) => module.key !== "water").map((module) => `<div class="change-row"><strong>${h(module.label)}</strong><p>${h(module.enabled ? module.representativeDemo ? "Enabled as representative demo data." : "Enabled by explicit feature flag." : `${module.status} gated off in real mode.`)}</p></div>`).join("");
  return `<section class="card section-card"><p class="card-label">Terris modules</p>${betaRows}</section>${ledgerStatusCard()}${nutrientsBetaSurface()}${energyBetaSurface()}${opsBetaSurface()}${proofBetaSurface()}`;
}

function betaLockedCard(key, label) {
  const module = moduleState(key);
  return `<section class="card section-card" data-module-locked="${h(key)}"><p class="card-label">${h(label)}</p><h2>Beta not enabled</h2><p>This beta is not enabled for this workspace.</p><small>${h(module?.limitations?.[0] || "Feature-gated Terris module.")}</small></section>`;
}

function demoBadge(key) {
  return representativeDemoFor(key) ? `<p class="demo-banner">Representative demo data</p>` : "";
}

function ledgerStatusCard() {
  const sync = syncStatus();
  const pending = sync.pending > 0;
  return `<section class="card section-card"><p class="card-label">Terris Ledger status</p><div class="data-source-list"><span>Storage: Local mobile buffer</span><span>Retention: Latest ${h(state.ledgerMetadata?.retentionLimit || 500)} events</span><span>Backend persistence: Not enabled</span><span>Pending sync: ${pending ? "Yes" : "No"}</span></div><p class="muted">This is not yet a durable audit archive.</p></section>`;
}

function nutrientsBetaSurface() {
  if (!isTerrisModuleEnabled("nutrients")) return betaLockedCard("nutrients", "Terris Nutrients beta");
  return `<section class="card form-card"><h2>Terris Nutrients beta</h2>${demoBadge("nutrients")}
      <label>Field<select id="nutrientField">${state.fields.map((f) => `<option value="${h(f.id)}">${h(f.name)}</option>`).join("")}</select></label>
      <label>Block optional<input id="nutrientBlock" /></label>
      <label>Crop cycle optional<input id="nutrientCropCycle" /></label>
      <label>Nutrient type<input id="nutrientType" placeholder="N, P, K, compost" /></label>
      <label>Source type<input id="nutrientSource" placeholder="fertilizer, compost, fertigation mix" /></label>
      <label>Application method<select id="nutrientMethod"><option value="">Select</option><option value="fertigation">Fertigation</option><option value="broadcast">Broadcast</option><option value="foliar">Foliar</option></select></label>
      <label>Planned quantity optional<input id="nutrientPlanned" type="number" /></label>
      <label>Applied quantity optional<input id="nutrientApplied" type="number" /></label>
      <label>Unit<input id="nutrientUnit" placeholder="kg, lb, gal" /></label>
      <label>Water volume optional<input id="nutrientWater" type="number" /></label>
      <label>Concentration optional<input id="nutrientConcentration" type="number" /></label>
      <label>Timestamp<input id="nutrientTimestamp" type="datetime-local" /></label>
      <label>Linked irrigation event optional<input id="nutrientIrrigationEvent" /></label>
      <label>Notes<input id="nutrientNotes" /></label>
      <button class="btn brand" data-save-nutrient="1">Save nutrient record</button>
    </section>`;
}

function energyBetaSurface() {
  if (!isTerrisModuleEnabled("energy")) return betaLockedCard("energy", "Terris Energy beta");
  const energy = state.mode === "demo" ? demoEnergyComparison({ timing: "Today before afternoon heat" }) : compareEligibleWindows({ recommendation: {}, windows: [], tariff: null, mode: "real", pumpEvidence: null });
  return `<section class="card section-card"><p class="card-label">Terris Energy beta</p>${demoBadge("energy")}<p>${h(energy.status === "ok" ? `Representative demo comparison: ${energy.bestWindow?.label}` : `Withheld until ${energy.missingInputs?.join(" and ") || "pump and tariff evidence"} exists.`)}</p><small>Cost optimization never overrides agronomic constraints.</small></section>`;
}

function openTasks() {
  return (state.fieldTasks || []).filter((task) => task.status !== "completed");
}

function opsBetaSurface() {
  if (!isTerrisModuleEnabled("ops")) return betaLockedCard("ops", "Terris Ops beta");
  const tasks = openTasks();
  return `<section class="card form-card"><h2>Terris Ops beta</h2>${demoBadge("ops")}
    <label>Task title<input id="taskTitle" placeholder="Collect missing evidence" /></label>
    <label>Field<select id="taskField">${state.fields.map((f) => `<option value="${h(f.id)}">${h(f.name)}</option>`).join("")}</select></label>
    <label>Task type<select id="taskType"><option value="collect_missing_data">Collect missing evidence</option><option value="inspect_field">Inspect field</option><option value="inspect_pump">Inspect pump</option><option value="record_fertigation">Record fertigation</option><option value="attach_evidence">Attach evidence</option><option value="review_anomaly">Review anomaly</option><option value="verify_application">Verify application workflow</option></select></label>
    <label>Priority<select id="taskPriority"><option value="medium">Medium</option><option value="high">High</option><option value="low">Low</option></select></label>
    <button class="btn" data-create-task="1">Create field task</button>
    <div class="change-row"><strong>Open-task queue</strong><p>${h(tasks.length ? tasks.map((task) => `${task.title} (${fieldName(task.fieldId)})`).join(", ") : "No open tasks.")}</p></div>
    <label>Task to complete<select id="taskToComplete">${tasks.map((task) => `<option value="${h(task.id)}">${h(task.title)} - ${h(fieldName(task.fieldId))}</option>`).join("")}</select></label>
    <label>Operator note<input id="taskCompletionNote" placeholder="What was completed?" /></label>
    <label>Attachment refs optional<input id="taskAttachments" placeholder="photo-1, receipt-2" /></label>
    <label>Completed at<input id="taskCompletedAt" type="datetime-local" /></label>
    <button class="btn" data-complete-task="1">Complete selected task</button>
  </section>`;
}

function defaultProofWindow() {
  const end = new Date().toISOString().slice(0, 10);
  const start = new Date(Date.now() - 7 * 24 * 3600000).toISOString().slice(0, 10);
  return { start, end };
}

function proofCandidateEvents(scope = {}) {
  const window = scope.dateWindow || defaultProofWindow();
  return filterEvidenceEvents(state.fieldLedgerEvents || [], {
    moduleScope: scope.moduleScope || "water",
    farmScope: scope.farmScope || "local-farm",
    fieldScope: scope.fieldScope || null,
    blockScope: scope.blockScope || null,
    dateWindow: window,
  });
}

function proofReviewTable(events) {
  const rows = reviewRowsForEvents(events);
  if (!rows.length) return `<p class="muted">No candidate events match the current default scope.</p>`;
  const overflow = rows.length > 8 ? `<p class="muted">...and ${h(rows.length - 8)} more events in scope.</p>` : "";
  return `<div class="activity-list">${rows.slice(0, 8).map((row) => `<div class="activity-row"><span></span><div><strong>${h(row.eventType)}</strong><p>${h(fieldName(row.fieldId))} - ${h(row.truthLabel)} - ${h(row.dataQuality)}</p></div><time>${h(relativeTime(row.occurredAt))}</time></div>`).join("")}</div>${overflow}`;
}

function proofBetaSurface() {
  if (!isTerrisModuleEnabled("proof")) return betaLockedCard("proof", "Terris Proof beta");
  const defaults = proofReviewSnapshot?.scope?.dateWindow || defaultProofWindow();
  const moduleScope = proofReviewSnapshot?.scope?.moduleScope || "water";
  const farmScope = proofReviewSnapshot?.scope?.farmScope || "local-farm";
  const fieldScope = proofReviewSnapshot?.scope?.fieldScope || "";
  const blockScope = proofReviewSnapshot?.scope?.blockScope || "";
  const candidates = proofReviewSnapshot?.events || [];
  return `<section class="card form-card"><h2>Terris Proof beta</h2>${demoBadge("proof")}<p>${h(TERRIS_PROOF_DISCLAIMER)}</p>
    <label>Module scope<input id="proofModule" value="${h(moduleScope)}" /></label>
    <label>Farm scope<input id="proofFarm" value="${h(farmScope)}" /></label>
    <label>Field scope<select id="proofField"><option value="">All fields</option>${state.fields.map((f) => `<option value="${h(f.id)}" ${fieldScope === f.id ? "selected" : ""}>${h(f.name)}</option>`).join("")}</select></label>
    <label>Block scope optional<input id="proofBlock" value="${h(blockScope)}" /></label>
    <label>Start date<input id="proofStart" type="date" value="${h(defaults.start)}" /></label>
    <label>End date<input id="proofEnd" type="date" value="${h(defaults.end)}" /></label>
    <button class="btn" data-preview-proof="1">Preview candidate events</button>
    <div class="change-row"><strong>Candidate event review</strong><p>${proofReviewSnapshot ? `Previewed ${h(candidates.length)} events at ${h(relativeTime(proofReviewSnapshot.reviewedAt))}.` : "Preview candidate events before generating."}</p></div>
    ${proofReviewSnapshot ? proofReviewTable(candidates) : `<p class="muted">No reviewed candidate set yet.</p>`}
    <label class="check-row"><input id="proofReviewed" type="checkbox" /> I reviewed included events</label>
    <button class="btn" data-generate-packet="1">Generate packet</button>
  </section>`;
}

function settingSubtitle(item) {
  const map = {
    Reports: "Season summaries and verification history",
    "Farm profile": state.profile?.farm?.name || "Farm identity",
    "Fields setup": `${state.fields.length} fields configured`,
    "Data sources": "Sensors, controllers, and manual checks",
    Integrations: "Connectors prepared for future setup",
    Notifications: "Alert preferences",
    Language: state.language || "English",
    Units: state.units || "metric",
    "Offline and sync": syncStatus().isOnline ? "Online" : "Offline",
    Help: "Field-ready support",
    "About Terris": "Agricultural intelligence companion",
  };
  return map[item] || "";
}

function progressDots() {
  const steps = ["Welcome", "Role", "Location", "Field", "Setup"];
  return `<div class="progress-wrap">${steps.map((s, i) => `<div class="progress-pill ${onboardingStep === i ? "active" : onboardingStep > i ? "done" : ""}">${h(s)}</div>`).join("")}</div>`;
}

function cardOptions(options, key) {
  return `<div class="choice-grid">${options.map((option) => `<button type="button" class="choice-card ${onboardingDraft[key] === option.value ? "selected" : ""}" data-onboard-choice="${h(key)}" data-value="${h(option.value)}"><strong>${h(option.label)}</strong>${option.sub ? `<span>${h(option.sub)}</span>` : ""}</button>`).join("")}</div>`;
}

function onboardingFlow() {
  if (onboardingStep === 0) {
    return `<section class="onboard-hero">
      <p class="eyebrow">Terris</p><h1>Know what to do with water today.</h1><p>A calm agricultural intelligence companion for every field decision.</p>
      <button class="btn brand xl" data-next-step="1">Set up my farm</button><button class="btn xl" id="startDemo">Preview with Napa vineyard data</button>
    </section>`;
  }
  const stepCards = {
    1: `<section class="card onboard-card"><h2>Who will use Terris?</h2>${cardOptions([{ value: "farmer", label: "Farmer" }, { value: "farm manager", label: "Farm manager" }, { value: "agronomist", label: "Agronomist" }, { value: "irrigation professional", label: "Irrigation pro" }], "role")}<label>Language<select id="language"><option value="en" ${onboardingDraft.language === "en" ? "selected" : ""}>English</option><option value="fr">French</option><option value="es">Spanish</option><option value="wo">Wolof</option><option value="ar">Arabic</option><option value="hi">Hindi</option><option value="pt">Portuguese</option></select></label></section>`,
    2: `<section class="card onboard-card"><h2>Where is your farm?</h2><label>Farm name<input id="farmName" value="${h(onboardingDraft.farmName)}" placeholder="e.g., North Valley Farm" /></label><label>Location<input id="farmLocation" value="${h(onboardingDraft.farmLocation)}" placeholder="City or region" /></label><button class="btn" id="captureGps">Use GPS location</button></section>`,
    3: `<section class="card onboard-card"><h2>Add your first field</h2><label>Field name<input id="fieldName" value="${h(onboardingDraft.fieldName)}" placeholder="North Block" /></label><label>Field location<input id="fieldLocation" value="${h(onboardingDraft.fieldLocation)}" placeholder="North block, near road" /></label><label>Crop<input id="crop" value="${h(onboardingDraft.crop)}" placeholder="Grapes, maize, tomato" /></label><label>Acreage<input id="acreage" value="${h(onboardingDraft.acreage)}" type="number" min="1" placeholder="10" /></label><label>Units<select id="units"><option value="metric" ${onboardingDraft.units === "metric" ? "selected" : ""}>Metric</option><option value="imperial" ${onboardingDraft.units === "imperial" ? "selected" : ""}>Imperial</option></select></label></section>`,
    4: `<section class="card onboard-card"><h2>Irrigation setup</h2>${cardOptions([{ value: "Drip", label: "Drip" }, { value: "Sprinkler", label: "Sprinkler" }, { value: "Pivot", label: "Pivot" }, { value: "Flood", label: "Flood" }], "irrigationMethod")}<label>Data availability</label>${cardOptions([{ value: "neither", label: "No sensors/controller", sub: "Manual tracking" }, { value: "sensors", label: "Sensors only" }, { value: "controller", label: "Controller only" }, { value: "both", label: "Sensors + controller" }], "dataSource")}<label>Soil type<input id="soilType" value="${h(onboardingDraft.soilType)}" placeholder="Loam, clay, sandy" /></label><label>Last irrigation date<input id="lastIrrigationAt" value="${h(onboardingDraft.lastIrrigationAt)}" type="date" /></label><label>Usual duration min<input id="usualDurationMin" value="${h(onboardingDraft.usualDurationMin)}" type="number" min="1" /></label><label>Water source<input id="waterSource" value="${h(onboardingDraft.waterSource)}" placeholder="Canal, well, reservoir" /></label></section>`,
  };
  return `${progressDots()}${stepCards[onboardingStep]}<div class="onboard-actions"><button class="btn" data-prev-step="1">Back</button><button class="btn brand" data-onboard-continue="1">Save and continue</button></div>`;
}

function topBar() {
  const sync = syncStatus();
  const farm = state.profile?.farm?.name || "Terris";
  return `<header class="app-topbar"><div class="wordmark"><span></span><strong>Terris</strong></div>${state.onboarded ? `<button class="farm-selector">${h(farm)}</button><div class="top-actions"><span class="sync-dot ${sync.isOnline ? "online" : "offline"}"></span><button class="icon-button" data-nav="alerts" aria-label="Notifications">!</button><button class="profile-button" data-nav="more">Me</button></div>` : ""}</header>`;
}

function content() {
  if (!state.onboarded) return onboardingFlow();
  if (route === "today") return todayContent();
  if (route === "fields") return fieldsContent();
  if (route === "assistant") return assistantContent();
  if (route === "alerts") return alertsContent();
  return moreContent();
}

function bottomNav() {
  return `<nav class="bottom-nav">${nav.map((n) => `<button class="${route === n.id ? "active" : ""} ${n.featured ? "featured" : ""}" data-nav="${h(n.id)}"><span>${h(n.label)}</span></button>`).join("")}</nav>`;
}

function render() {
  const sync = syncStatus();
  if (state.onboarded) prepareRecommendationSnapshot();
  app.innerHTML = `<div class="app-bg"><main class="shell ${!state.onboarded ? "shell-onboard" : ""}">${topBar()}${!sync.isOnline ? `<div class="offline-banner">Offline mode active. Logs and observations will sync later.</div>` : ""}${content()}${uiMessage ? `<div class="toast">${h(uiMessage)}</div>` : ""}${state.onboarded ? bottomNav() : ""}</main></div>`;
  bind();
  scheduleDecisionRefreshes();
}

function readDraftInputs() {
  const assign = (id, key = id) => {
    const el = document.getElementById(id);
    if (el) onboardingDraft[key] = el.value;
  };
  ["language", "farmName", "farmLocation", "fieldName", "fieldLocation", "crop", "acreage", "units", "soilType", "lastIrrigationAt", "usualDurationMin", "waterSource"].forEach((id) => assign(id));
}

function bind() {
  app.querySelectorAll("[data-nav]").forEach((b) => (b.onclick = async () => {
    route = b.dataset.nav;
    selectedField = null;
    if (b.dataset.assistantField) assistantFieldId = b.dataset.assistantField;
    if (route === "assistant") assistantResponse = await fetchAssistantText(assistantFieldId || state.fields[0]?.id || "");
    render();
  }));
  app.querySelectorAll("[data-open-field]").forEach((b) => (b.onclick = () => { route = "fields"; selectedField = { type: "detail", fieldId: b.dataset.openField }; render(); }));
  app.querySelectorAll("[data-open-log]").forEach((b) => (b.onclick = () => { route = "fields"; selectedField = { type: "log", fieldId: b.dataset.openLog }; render(); }));
  app.querySelectorAll("[data-open-condition]").forEach((b) => (b.onclick = () => { route = "fields"; selectedField = { type: "condition", fieldId: b.dataset.openCondition }; render(); }));
  app.querySelectorAll("[data-back-fields]").forEach((b) => (b.onclick = () => { selectedField = null; route = "fields"; render(); }));
  app.querySelectorAll("[data-filter]").forEach((b) => (b.onclick = () => { fieldFilter = b.dataset.filter; render(); }));
  const search = document.getElementById("fieldSearch");
  if (search) search.oninput = () => { fieldSearch = search.value; renderSoon(); };
  const assistantField = document.getElementById("assistantField");
  if (assistantField) assistantField.onchange = async () => { assistantFieldId = assistantField.value; assistantResponse = await fetchAssistantText(assistantFieldId); render(); };
  app.querySelectorAll("[data-assistant-query]").forEach((b) => (b.onclick = async () => { assistantResponse = await fetchAssistantText(assistantFieldId || state.fields[0]?.id || "", b.dataset.assistantQuery); render(); }));
  const sendAssistant = document.querySelector("[data-send-assistant]");
  if (sendAssistant) sendAssistant.onclick = async () => { const q = document.getElementById("assistantInput")?.value || "Should I irrigate today?"; assistantResponse = await fetchAssistantText(assistantFieldId || state.fields[0]?.id || "", q); render(); };
  app.querySelectorAll("[data-refresh-weather]").forEach((b) => (b.onclick = async () => { await refreshWeather(true); showMessage("Weather refreshed."); render(); }));
  app.querySelectorAll("[data-set-reminder]").forEach((b) => (b.onclick = () => showMessage(`Reminder set for ${fieldName(b.dataset.setReminder)}.`)));
  app.querySelectorAll("[data-scroll-provenance]").forEach((b) => (b.onclick = () => document.querySelector("[data-testid='provenance-disclosure']")?.scrollIntoView({ behavior: "smooth", block: "start" })));
  app.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = async () => { state = b.dataset.mode === "demo" ? useDemoMode(state) : { ...state, mode: "real" }; persist(); await refreshWeather(true); render(); }));

  const applyScenarioBtn = document.querySelector("[data-apply-scenario]");
  if (applyScenarioBtn) applyScenarioBtn.onclick = async () => {
    const scenario = document.getElementById("demoScenario")?.value || "baseline";
    state = applyDemoScenario(state, scenario);
    recordLocalRecommendationTransitions();
    persist();
    await refreshWeather(true);
    render();
  };
  const saveLogBtn = document.querySelector("[data-save-log]");
  if (saveLogBtn) saveLogBtn.onclick = () => {
    addIrrigationLog({ fieldId: document.getElementById("logField").value, performedAt: new Date(document.getElementById("logDate").value || Date.now()).toISOString(), durationMin: document.getElementById("logDuration").value || 45, amountMm: document.getElementById("logAmount").value || null, note: document.getElementById("logNote").value || "", source: "manual" });
    route = "today"; selectedField = null; render();
  };
  const saveConditionBtn = document.querySelector("[data-save-condition]");
  if (saveConditionBtn) saveConditionBtn.onclick = () => {
    updateCondition({ fieldId: document.getElementById("conditionField").value, condition: document.getElementById("conditionValue").value, source: "manual" });
    route = "today"; selectedField = null; render();
  };
  const saveNutrientBtn = document.querySelector("[data-save-nutrient]");
  if (saveNutrientBtn) saveNutrientBtn.onclick = () => {
    if (!isTerrisModuleEnabled("nutrients")) {
      showMessage("Terris Nutrients beta is not enabled for this workspace.");
      return;
    }
    const offline = !navigator.onLine;
    const record = createNutrientRecord({
      fieldId: document.getElementById("nutrientField")?.value,
      blockId: document.getElementById("nutrientBlock")?.value || null,
      cropCycleId: document.getElementById("nutrientCropCycle")?.value || null,
      nutrientType: document.getElementById("nutrientType")?.value || "",
      sourceType: document.getElementById("nutrientSource")?.value || "",
      applicationMethod: document.getElementById("nutrientMethod")?.value || "",
      plannedQuantity: document.getElementById("nutrientPlanned")?.value || null,
      appliedQuantity: document.getElementById("nutrientApplied")?.value || null,
      unit: document.getElementById("nutrientUnit")?.value || "",
      waterVolume: document.getElementById("nutrientWater")?.value || null,
      concentration: document.getElementById("nutrientConcentration")?.value || null,
      timestamp: document.getElementById("nutrientTimestamp")?.value ? new Date(document.getElementById("nutrientTimestamp").value).toISOString() : new Date().toISOString(),
      linkedIrrigationEventId: document.getElementById("nutrientIrrigationEvent")?.value || null,
      notes: document.getElementById("nutrientNotes")?.value || "",
      representativeDemo: representativeDemoFor("nutrients"),
      demo: state.mode === "demo",
      syncStatus: offline ? "queued" : "synced",
    });
    state.nutrientRecords.unshift(record);
    state = appendLedgerEvent(state, nutrientLedgerEvent(record));
    if (offline) queueSyncAction({ kind: "nutrient_log", payload: record });
    persist();
    showMessage(record.missingData.length ? `Saved draft. Missing: ${record.missingData.join(", ")}.` : "Nutrient record saved.");
    render();
  };
  const createTaskBtn = document.querySelector("[data-create-task]");
  if (createTaskBtn) createTaskBtn.onclick = () => {
    if (!isTerrisModuleEnabled("ops")) {
      showMessage("Terris Ops beta is not enabled for this workspace.");
      return;
    }
    try {
      const task = createFieldTask({
        title: document.getElementById("taskTitle")?.value || "Collect missing evidence",
        module: "ops",
        taskType: document.getElementById("taskType")?.value || "collect_missing_data",
        priority: document.getElementById("taskPriority")?.value || "medium",
        fieldId: document.getElementById("taskField")?.value || state.fields[0]?.id || "local-field",
        offlineSyncState: navigator.onLine ? "synced" : "queued",
        representativeDemo: representativeDemoFor("ops"),
      });
      state.fieldTasks.unshift(task);
      state = appendLedgerEvent(state, taskEvent(task, false));
      persist();
      showMessage("Field task created.");
      render();
    } catch (error) {
      showMessage(error.message);
    }
  };
  const completeTaskBtn = document.querySelector("[data-complete-task]");
  if (completeTaskBtn) completeTaskBtn.onclick = () => {
    if (!isTerrisModuleEnabled("ops")) {
      showMessage("Terris Ops beta is not enabled for this workspace.");
      return;
    }
    try {
      const taskId = document.getElementById("taskToComplete")?.value || "";
      const task = (state.fieldTasks || []).find((row) => row.id === taskId);
      if (!task) throw new Error("Select an open task before completing it.");
      const completed = completeFieldTask(task, {
        notes: document.getElementById("taskCompletionNote")?.value || "",
        attachments: (document.getElementById("taskAttachments")?.value || "").split(",").map((x) => x.trim()).filter(Boolean),
        completedAt: document.getElementById("taskCompletedAt")?.value ? new Date(document.getElementById("taskCompletedAt").value).toISOString() : new Date().toISOString(),
        offline: !navigator.onLine,
      });
      state.fieldTasks = (state.fieldTasks || []).map((row) => row.id === task.id ? completed : row);
      state = appendLedgerEvent(state, taskEvent(completed, true));
      persist();
      showMessage("Task completion recorded separately from agronomic verification.");
      render();
    } catch (error) {
      showMessage(error.message);
    }
  };
  const previewProofBtn = document.querySelector("[data-preview-proof]");
  if (previewProofBtn) previewProofBtn.onclick = () => {
    if (!isTerrisModuleEnabled("proof")) {
      showMessage("Terris Proof beta is not enabled for this workspace.");
      return;
    }
    const scope = {
      moduleScope: document.getElementById("proofModule")?.value || "",
      farmScope: document.getElementById("proofFarm")?.value || "",
      fieldScope: document.getElementById("proofField")?.value || null,
      blockScope: document.getElementById("proofBlock")?.value || null,
      dateWindow: { start: document.getElementById("proofStart")?.value || "", end: document.getElementById("proofEnd")?.value || "" },
    };
    const events = filterEvidenceEvents(state.fieldLedgerEvents || [], scope);
    proofReviewSnapshot = {
      scope,
      includedEventIds: events.map((event) => event.id),
      reviewSignature: evidenceReviewSignature(scope, events),
      reviewedAt: new Date().toISOString(),
      events,
    };
    showMessage(events.length ? "Candidate events previewed." : "No candidate events matched this proof scope.");
    render();
  };
  const generatePacketBtn = document.querySelector("[data-generate-packet]");
  if (generatePacketBtn) generatePacketBtn.onclick = () => {
    if (!isTerrisModuleEnabled("proof")) {
      showMessage("Terris Proof beta is not enabled for this workspace.");
      return;
    }
    const fieldScope = document.getElementById("proofField")?.value || null;
    const blockScope = document.getElementById("proofBlock")?.value || null;
    const scope = {
      moduleScope: document.getElementById("proofModule")?.value || "",
      farmScope: document.getElementById("proofFarm")?.value || "",
      fieldScope,
      blockScope,
      dateWindow: { start: document.getElementById("proofStart")?.value || "", end: document.getElementById("proofEnd")?.value || "" },
    };
    const events = filterEvidenceEvents(state.fieldLedgerEvents || [], scope);
    const currentSignature = evidenceReviewSignature(scope, events);
    const snapshotMatches = proofReviewSnapshot?.reviewSignature === currentSignature
      && JSON.stringify([...(proofReviewSnapshot?.includedEventIds || [])].sort()) === JSON.stringify(events.map((event) => event.id).sort());
    const packet = createEvidencePacket({
      moduleScope: scope.moduleScope,
      farmScope: scope.farmScope,
      fieldScope,
      blockScope,
      dateWindow: scope.dateWindow,
      events,
      preFiltered: true,
      reviewConfirmed: Boolean(document.getElementById("proofReviewed")?.checked) && snapshotMatches,
      reviewSnapshot: proofReviewSnapshot,
      missingInputs: snapshotMatches ? events.length ? [] : ["reviewable ledger evidence"] : ["preview candidate events for the current scope"],
      representativeDemo: representativeDemoFor("proof"),
    });
    state.evidencePackets.unshift(packet);
    state = appendLedgerEvent(state, evidencePacketEvent(packet));
    persist();
    showMessage(packet.status === "draft_missing_evidence" ? "Draft packet saved with missing evidence clearly labeled." : "Operational evidence packet saved.");
    render();
  };
  app.querySelectorAll("[data-resolve-alert]").forEach((b) => (b.onclick = () => {
    const key = b.dataset.resolveAlert;
    state.alertHistory = (state.alertHistory || []).map((a) => (a.id === key || a.key === key) ? { ...a, resolved: true } : a);
    state.dismissedAlerts = { ...(state.dismissedAlerts || {}), [key]: { dismissedAt: new Date().toISOString(), fingerprint: b.dataset.alertFingerprint || "" } };
    persist();
    showMessage("Alert resolved.");
    render();
  }));
  app.querySelectorAll("[data-next-step]").forEach((b) => (b.onclick = () => { onboardingStep = Number(b.dataset.nextStep); render(); }));
  app.querySelectorAll("[data-prev-step]").forEach((b) => (b.onclick = () => { readDraftInputs(); onboardingStep = Math.max(0, onboardingStep - 1); render(); }));
  app.querySelectorAll("[data-onboard-choice]").forEach((b) => (b.onclick = () => { onboardingDraft[b.dataset.onboardChoice] = b.dataset.value; render(); }));
  const continueBtn = document.querySelector("[data-onboard-continue]");
  if (continueBtn) continueBtn.onclick = async () => {
    readDraftInputs();
    if (onboardingStep < 4) { onboardingStep += 1; render(); return; }
    state = applyOnboarding(state, { ...onboardingDraft, coordinates: onboardingDraft.coordinates });
    route = "today"; persist(); await refreshWeather(true); render();
  };
  const gpsBtn = document.getElementById("captureGps");
  if (gpsBtn) gpsBtn.onclick = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      onboardingDraft.coordinates = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      onboardingDraft.farmLocation = `${pos.coords.latitude.toFixed(3)}, ${pos.coords.longitude.toFixed(3)}`;
      render();
    }, () => showMessage("GPS unavailable. You can add location manually."));
  };
  const demo = document.getElementById("startDemo");
  if (demo) demo.onclick = async () => { state = useDemoMode(state); route = "today"; persist(); await refreshWeather(true); render(); };
  app.querySelectorAll("[data-voice]").forEach((b) => (b.onclick = async () => {
    const fieldId = b.dataset.voice || state.fields[0]?.id || "";
    if (!voiceListening) {
      voiceListening = true; transcript = ""; pendingVoiceCommand = null; voiceResponse = "Listening locally. Tap the orb again to review."; render(); return;
    }
    voiceListening = false;
    transcript = `Field ${fieldName(fieldId)} looks dry`;
    const command = parseVoiceCommand(transcript, { fieldId });
    pendingVoiceCommand = command;
    voiceResponse = `I heard: ${command.intent.replaceAll("_", " ").toLowerCase()}. Confirm before saving.`;
    render();
  }));
  const confirmVoice = document.querySelector("[data-confirm-voice]");
  if (confirmVoice) confirmVoice.onclick = () => {
    const command = pendingVoiceCommand;
    if (!command) return;
    if (!navigator.onLine) {
      saveOfflineVoiceAction(command.action);
      reconcileLedgerSyncMetadata({ persistState: false });
    }
    applyVoiceAction(command, { onIrrigation: addIrrigationLog, onCondition: updateCondition, onNote: addFieldNote, onNoop: () => {} });
    state.voiceTimeline.unshift(createVoiceTimelineEntry({ transcript, intent: command.intent, outcome: "confirmed", fieldId: command.action?.payload?.fieldId || state.fields[0]?.id }));
    state.voiceTimeline = state.voiceTimeline.slice(0, 20);
    pendingVoiceCommand = null;
    voiceResponse = navigator.onLine ? "Voice action saved." : "Voice action queued offline.";
    persist();
    render();
  };
}

if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
window.addEventListener("online", async () => { await syncService.flushQueue(); reconcileLedgerSyncMetadata(); await refreshWeather(false); render(); });
window.addEventListener("offline", render);

(async () => {
  await refreshWeather(false);
  assistantFieldId = state.fields[0]?.id || "";
  render();
})();
