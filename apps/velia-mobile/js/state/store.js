import { storage } from "../services/storage.js";
import { demoProfile } from "../data/demoData.js";
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
    weatherCache: null,
    language: "en",
    units: "metric",
  };
}

export const loadState = () => storage.get(KEY, createInitialState());
export const saveState = (state) => storage.set(KEY, state);

export function useDemoMode(state) {
  return {
    ...state,
    mode: "demo",
    onboarded: true,
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
