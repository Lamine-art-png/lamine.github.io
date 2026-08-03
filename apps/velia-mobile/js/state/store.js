import { storage } from "../services/storage.js";
import { demoProfile, demoScenarios } from "../data/demoData.js";
import { createField } from "./actions.js";

const KEY = "state";

export function createInitialState() {
  return {
    mode: "real",
    onboarded: false,
    profile: null,
    fields: [],
    irrigationLogs: [],
    fieldNotes: [],
    observations: [],
    recommendationHistory: [],
    remoteDecisions: {},
    alertHistory: [],
    dismissedAlerts: {},
    alertFirstSeen: {},
    voiceTimeline: [],
    weatherCache: null,
    nutrientRecords: [],
    pumpRuntimeEvents: [],
    fieldTasks: [],
    evidenceArtifacts: [],
    evidencePackets: [],
    fieldLedgerEvents: [],
    ledgerMetadata: {
      retentionLimit: 500,
      persistenceMode: "local_mobile_buffer",
      durableBackendPersistence: false,
      queuedForSync: false,
    },
    demoScenario: "baseline",
    language: "en",
    units: "metric",
  };
}

export function hydrateState(stored = {}) {
  const defaults = createInitialState();
  const safeStored = stored && typeof stored === "object" ? stored : {};
  return {
    ...defaults,
    ...safeStored,
    fields: Array.isArray(safeStored.fields) ? safeStored.fields : defaults.fields,
    irrigationLogs: Array.isArray(safeStored.irrigationLogs) ? safeStored.irrigationLogs : defaults.irrigationLogs,
    fieldNotes: Array.isArray(safeStored.fieldNotes) ? safeStored.fieldNotes : defaults.fieldNotes,
    observations: Array.isArray(safeStored.observations) ? safeStored.observations : defaults.observations,
    recommendationHistory: Array.isArray(safeStored.recommendationHistory) ? safeStored.recommendationHistory : defaults.recommendationHistory,
    alertHistory: Array.isArray(safeStored.alertHistory) ? safeStored.alertHistory : defaults.alertHistory,
    voiceTimeline: Array.isArray(safeStored.voiceTimeline) ? safeStored.voiceTimeline : defaults.voiceTimeline,
    nutrientRecords: Array.isArray(safeStored.nutrientRecords) ? safeStored.nutrientRecords : defaults.nutrientRecords,
    pumpRuntimeEvents: Array.isArray(safeStored.pumpRuntimeEvents) ? safeStored.pumpRuntimeEvents : defaults.pumpRuntimeEvents,
    fieldTasks: Array.isArray(safeStored.fieldTasks) ? safeStored.fieldTasks : defaults.fieldTasks,
    evidenceArtifacts: Array.isArray(safeStored.evidenceArtifacts) ? safeStored.evidenceArtifacts : defaults.evidenceArtifacts,
    evidencePackets: Array.isArray(safeStored.evidencePackets) ? safeStored.evidencePackets : defaults.evidencePackets,
    fieldLedgerEvents: Array.isArray(safeStored.fieldLedgerEvents) ? safeStored.fieldLedgerEvents : defaults.fieldLedgerEvents,
    remoteDecisions: safeStored.remoteDecisions && typeof safeStored.remoteDecisions === "object" ? safeStored.remoteDecisions : defaults.remoteDecisions,
    dismissedAlerts: safeStored.dismissedAlerts && typeof safeStored.dismissedAlerts === "object" ? safeStored.dismissedAlerts : defaults.dismissedAlerts,
    alertFirstSeen: safeStored.alertFirstSeen && typeof safeStored.alertFirstSeen === "object" ? safeStored.alertFirstSeen : defaults.alertFirstSeen,
    ledgerMetadata: {
      ...defaults.ledgerMetadata,
      ...(safeStored.ledgerMetadata && typeof safeStored.ledgerMetadata === "object" ? safeStored.ledgerMetadata : {}),
      persistenceMode: "local_mobile_buffer",
      durableBackendPersistence: false,
    },
  };
}

export const loadState = () => hydrateState(storage.get(KEY, createInitialState()));
export const saveState = (state) => storage.set(KEY, state);

export function recordRecommendationHistory(state, fieldId, rec) {
  const last = state.recommendationHistory.find((entry) => entry.fieldId === fieldId);
  const now = Date.now();
  const lastAt = last ? new Date(last.at).getTime() : 0;
  const changed = !last || last.rec.urgency !== rec.urgency || last.rec.action !== rec.action;
  if (!changed && now - lastAt < 45 * 60 * 1000) return state;

  return {
    ...state,
    recommendationHistory: [{ fieldId, rec, at: new Date().toISOString(), eventType: changed ? "recommendation changed" : "recommendation refreshed" }, ...state.recommendationHistory].slice(0, 40),
  };
}

export function applyDemoScenario(state, scenarioName) {
  const scenario = demoScenarios[scenarioName] || demoScenarios.baseline;
  const fields = state.fields.map((field) => ({ ...field, waterStressLevel: scenario.stress, lastObservation: scenario.observation }));
  return { ...state, demoScenario: scenarioName, fields, weatherCache: state.weatherCache ? { ...state.weatherCache, ...scenario.weatherOverride } : state.weatherCache };
}

export function useDemoMode(state) {
  const base = hydrateState(state);
  return {
    ...base,
    mode: "demo",
    onboarded: true,
    demoScenario: "baseline",
    profile: { role: demoProfile.role, farm: demoProfile.farm, hardware: demoProfile.farm.hardware },
    fields: demoProfile.fields,
    irrigationLogs: demoProfile.irrigationLogs,
    fieldNotes: demoProfile.fieldNotes,
    observations: demoProfile.observations || [],
    recommendationHistory: demoProfile.recommendationHistory || [],
    alertHistory: demoProfile.alertHistory || [],
    voiceTimeline: demoProfile.voiceTimeline || [],
    nutrientRecords: base.nutrientRecords || [],
    pumpRuntimeEvents: base.pumpRuntimeEvents || [],
    fieldTasks: base.fieldTasks || [],
    evidenceArtifacts: base.evidenceArtifacts || [],
    evidencePackets: base.evidencePackets || [],
    fieldLedgerEvents: base.fieldLedgerEvents || [],
    ledgerMetadata: { ...base.ledgerMetadata, queuedForSync: false },
    language: demoProfile.language,
    units: demoProfile.farm.units,
  };
}

export function applyOnboarding(state, onboarding) {
  const field = createField(onboarding);
  return {
    ...state,
    onboarded: true,
    mode: "real",
    profile: {
      role: onboarding.role,
      farm: {
        name: onboarding.farmName,
        location: onboarding.farmLocation,
        coordinates: onboarding.coordinates || null,
        hardware: onboarding.hardware,
        units: onboarding.units,
        waterSource: onboarding.waterSource || "",
        dataSourceMode: onboarding.dataSource || "neither",
      },
    },
    fields: [field],
    language: onboarding.language,
    units: onboarding.units,
  };
}
