import { ragEngine } from "./ragEngine.js";
import { verificationAgent } from "./verificationAgent.js";
import { translationAgent } from "./translationAgent.js";

export function createToolRegistry(ctx) {
  const tools = {
    getFarmProfile: { name: "getFarmProfile", mode: "mock", execute: () => ctx.farm },
    getFieldProfile: { name: "getFieldProfile", mode: "mock", execute: () => ctx.field },
    getWeather: { name: "getWeather", mode: "mock", execute: () => ctx.weather },
    getForecast: { name: "getForecast", mode: "mock", execute: () => ctx.weather },
    getIrrigationLogs: { name: "getIrrigationLogs", mode: "mock", execute: () => ctx.logs || [] },
    getFieldObservations: { name: "getFieldObservations", mode: "mock", execute: () => ctx.observations || [] },
    getRecommendationHistory: { name: "getRecommendationHistory", mode: "mock", execute: () => ctx.recommendationHistory || [] },
    saveIrrigationLog: { name: "saveIrrigationLog", mode: "mock", execute: ({ payload }) => ({ ok: true, payload }) },
    saveFieldObservation: { name: "saveFieldObservation", mode: "mock", execute: ({ payload }) => ({ ok: true, payload }) },
    saveVoiceNote: { name: "saveVoiceNote", mode: "mock", execute: ({ payload }) => ({ ok: true, payload }) },
    retrieveKnowledge: { name: "retrieveKnowledge", mode: "mock", execute: ({ query }) => ragEngine.retrieve(query) },
    calculateWaterBalance: { name: "calculateWaterBalance", mode: "mock", execute: ({ field, weather }) => ({ score: (field?.waterStressLevel === "high" ? 0.8 : 0.4) + ((weather?.heatRisk === "elevated") ? 0.1 : 0) }) },
    estimateIrrigationNeed: { name: "estimateIrrigationNeed", mode: "mock", execute: ({ field }) => ({ score: field?.waterStressLevel === "high" ? 0.8 : 0.45 }) },
    calculateConfidence: { name: "calculateConfidence", mode: "mock", execute: ({ missingData }) => ({ score: Math.max(0.25, 0.8 - (missingData?.length || 0) * 0.1) }) },
    generateExplanation: { name: "generateExplanation", mode: "mock", execute: ({ decision }) => `This recommendation is ${decision.confidenceLabel} confidence due to available weather and field signals.` },
    verifyRecommendationOutcome: { name: "verifyRecommendationOutcome", mode: "mock", execute: ({ recommendation }) => verificationAgent.verify({ recommendation, logs: ctx.logs || [], observations: ctx.observations || [] }) },
    translateText: { name: "translateText", mode: "mock", execute: ({ text, language }) => translationAgent.translate(text, language) },
  };

  return {
    get: (name) => tools[name],
    list: () => Object.values(tools),
  };
}
