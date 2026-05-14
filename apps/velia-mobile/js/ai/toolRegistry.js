import { ragEngine } from "./ragEngine.js";
import { verificationAgent } from "./verificationAgent.js";
import { translationAgent } from "./translationAgent.js";

function schema(type, required = []) {
  return { type: "object", properties: type, required };
}

export function createToolRegistry(context) {
  const tools = {
    getFarmProfile: {
      name: "getFarmProfile",
      description: "Retrieve farm profile",
      inputSchema: schema({}),
      outputSchema: schema({ farm: { type: "object" } }),
      mode: "mock",
      execute: () => context.getFarmProfile(),
    },
    getFieldProfile: { name: "getFieldProfile", description: "Retrieve field profile", inputSchema: schema({ fieldId: { type: "string" } }, ["fieldId"]), outputSchema: schema({ field: { type: "object" } }), mode: "mock", execute: ({ fieldId }) => context.getFieldProfile(fieldId) },
    getWeather: { name: "getWeather", description: "Get current weather", inputSchema: schema({}), outputSchema: schema({ weather: { type: "object" } }), mode: "mock", execute: () => context.getWeather() },
    getForecast: { name: "getForecast", description: "Get forecast", inputSchema: schema({}), outputSchema: schema({ forecast: { type: "object" } }), mode: "mock", execute: () => context.getWeather() },
    getIrrigationLogs: { name: "getIrrigationLogs", description: "Get irrigation logs", inputSchema: schema({ fieldId: { type: "string" } }), outputSchema: schema({ logs: { type: "array" } }), mode: "mock", execute: ({ fieldId }) => context.getIrrigationLogs(fieldId) },
    getFieldObservations: { name: "getFieldObservations", description: "Get field observations", inputSchema: schema({ fieldId: { type: "string" } }), outputSchema: schema({ observations: { type: "array" } }), mode: "mock", execute: ({ fieldId }) => context.getFieldObservations(fieldId) },
    getRecommendationHistory: { name: "getRecommendationHistory", description: "Get recommendation history", inputSchema: schema({ fieldId: { type: "string" } }), outputSchema: schema({ history: { type: "array" } }), mode: "mock", execute: ({ fieldId }) => context.getRecommendationHistory(fieldId) },
    saveIrrigationLog: { name: "saveIrrigationLog", description: "Save irrigation log", inputSchema: schema({ payload: { type: "object" } }, ["payload"]), outputSchema: schema({ ok: { type: "boolean" } }), mode: "mock", execute: ({ payload }) => context.saveIrrigationLog(payload) },
    saveFieldObservation: { name: "saveFieldObservation", description: "Save field observation", inputSchema: schema({ payload: { type: "object" } }, ["payload"]), outputSchema: schema({ ok: { type: "boolean" } }), mode: "mock", execute: ({ payload }) => context.saveFieldObservation(payload) },
    saveVoiceNote: { name: "saveVoiceNote", description: "Save voice note", inputSchema: schema({ payload: { type: "object" } }), outputSchema: schema({ ok: { type: "boolean" } }), mode: "mock", execute: ({ payload }) => context.saveVoiceNote(payload) },
    retrieveKnowledge: { name: "retrieveKnowledge", description: "Retrieve agronomic knowledge", inputSchema: schema({ query: { type: "string" } }), outputSchema: schema({ chunks: { type: "array" } }), mode: "mock", execute: ({ query }) => ragEngine.retrieve(query) },
    calculateWaterBalance: { name: "calculateWaterBalance", description: "Estimate water balance", inputSchema: schema({ field: { type: "object" }, weather: { type: "object" } }), outputSchema: schema({ waterBalanceScore: { type: "number" } }), mode: "mock", execute: ({ field, weather }) => context.calculateWaterBalance(field, weather) },
    estimateIrrigationNeed: { name: "estimateIrrigationNeed", description: "Estimate irrigation need", inputSchema: schema({ field: { type: "object" }, weather: { type: "object" } }), outputSchema: schema({ needScore: { type: "number" } }), mode: "mock", execute: ({ field, weather }) => context.estimateIrrigationNeed(field, weather) },
    calculateConfidence: { name: "calculateConfidence", description: "Calculate confidence", inputSchema: schema({ missingData: { type: "array" } }), outputSchema: schema({ confidenceScore: { type: "number" } }), mode: "mock", execute: ({ missingData, needScore }) => context.calculateConfidence({ missingData, needScore }) },
    generateExplanation: { name: "generateExplanation", description: "Generate concise explanation", inputSchema: schema({ decision: { type: "object" } }), outputSchema: schema({ explanation: { type: "string" } }), mode: "mock", execute: ({ decision }) => context.generateExplanation(decision) },
    verifyRecommendationOutcome: { name: "verifyRecommendationOutcome", description: "Verify recommendation outcome", inputSchema: schema({ recommendation: { type: "object" }, fieldId: { type: "string" } }), outputSchema: schema({ verification: { type: "object" } }), mode: "mock", execute: ({ recommendation, fieldId }) => verificationAgent.verify({ recommendation, irrigationLogs: context.getIrrigationLogs(fieldId), observations: context.getFieldObservations(fieldId) }) },
    translateText: { name: "translateText", description: "Translate output", inputSchema: schema({ text: { type: "string" }, language: { type: "string" } }), outputSchema: schema({ translated: { type: "string" } }), mode: "mock", execute: ({ text, language }) => translationAgent.translate(text, language) },
  };

  return {
    get(name) {
      return tools[name];
    },
    list() {
      return Object.values(tools);
    },
  };
}
