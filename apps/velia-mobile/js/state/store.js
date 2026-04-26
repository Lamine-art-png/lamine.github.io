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
    alertHistory: [],
    voiceTimeline: [],
    weatherCache: null,
    demoScenario: "baseline",
    language: "en",
    units: "metric",
  };
}

export const loadState = () => storage.get(KEY, createInitialState());
export const saveState = (state) => storage.set(KEY, state);

export function recordRecommendationHistory(state, fieldId, rec) {
  const last = state.recommendationHistory.find((entry) => entry.fieldId === fieldId);
  const now = Date.now();
  const lastAt = last ? new Date(last.at).getTime() : 0;
  const changedUrgency = !last || last.rec.urgency !== rec.urgency;
  if (!changedUrgency && now - lastAt < 30 * 60 * 1000) return state;

  return {
    ...state,
    recommendationHistory: [{ fieldId, rec, at: new Date().toISOString() }, ...state.recommendationHistory].slice(0, 40),
  };
}

export function applyDemoScenario(state, scenarioName) {
  const scenario = demoScenarios[scenarioName] || demoScenarios.baseline;
  const fields = state.fields.map((field) => ({ ...field, waterStressLevel: scenario.stress, lastObservation: scenario.observation }));
  return { ...state, demoScenario: scenarioName, fields, weatherCache: state.weatherCache ? { ...state.weatherCache, ...scenario.weatherOverride } : state.weatherCache };
}

export function useDemoMode(state) {
  return {
    ...state,
    mode: "demo",
    onboarded: true,
    demoScenario: "baseline",
    profile: { role: demoProfile.role, farm: demoProfile.farm, hardware: demoProfile.farm.hardware },
    fields: demoProfile.fields,
    irrigationLogs: demoProfile.irrigationLogs,
    fieldNotes: demoProfile.fieldNotes,
    observations: demoProfile.observations || [],
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
      },
    },
    fields: [field],
    language: onboarding.language,
    units: onboarding.units,
  };
}
