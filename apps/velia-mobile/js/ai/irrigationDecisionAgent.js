import { fieldReasoningAgent } from "./fieldReasoningAgent.js";
import { weatherRiskAgent } from "./weatherRiskAgent.js";
import { memoryStore } from "./memoryStore.js";
import { safetyGuardrails } from "./safetyGuardrails.js";

function confidenceLabel(score) {
  if (score >= 0.75) return "high";
  if (score >= 0.5) return "moderate";
  return "low";
}

export const irrigationDecisionAgent = {
  decide({ fieldId, tools, planner }) {
    const field = tools.get("getFieldProfile").execute({ fieldId });
    const weather = tools.get("getWeather").execute();
    const observations = tools.get("getFieldObservations").execute({ fieldId });
    const logs = tools.get("getIrrigationLogs").execute({ fieldId });
    const kb = tools.get("retrieveKnowledge").execute({ query: `${field.crop} irrigation weather risk confidence` });

    const dataQuality = fieldReasoningAgent.evaluateDataQuality(field, { weather, observations });
    const weatherRisk = weatherRiskAgent.assess(weather);
    const need = tools.get("estimateIrrigationNeed").execute({ field, weather, observations, logs });

    const confidenceScore = tools.get("calculateConfidence").execute({ missingData: dataQuality.missingData, needScore: need.needScore });

    const action = need.needScore > 0.7 ? "irrigate" : need.needScore > 0.45 ? "check field first" : (weather.rainChance > 55 ? "wait" : "monitor");
    const timing = action === "irrigate" ? "Next 2-4 hours" : "Today before evening";
    const urgency = need.needScore > 0.7 ? "high" : need.needScore > 0.45 ? "medium" : "low";

    let decision = {
      decisionId: `dec-${Date.now()}`,
      fieldId,
      action,
      timing,
      urgency,
      estimatedDurationRange: action === "irrigate" ? "45-90 min" : "0-30 min check",
      confidenceScore,
      confidenceLabel: confidenceLabel(confidenceScore),
      reasons: [
        `Weather summary: ${weather.forecastSummary}`,
        `Latest observation: ${observations[0]?.condition || "none"}`,
        `Estimated irrigation need score: ${need.needScore.toFixed(2)}`,
      ],
      uncertainties: dataQuality.missingData.length ? [`Missing: ${dataQuality.missingData.join(", ")}`] : ["No major uncertainty drivers"],
      missingData: dataQuality.missingData,
      fieldChecks: action === "check field first" ? ["Check topsoil moisture", "Inspect leaf stress"] : ["Confirm field condition after action"],
      risks: weatherRisk.risks,
      nextBestAction: action === "irrigate" ? "Log irrigation after completion" : "Update field condition",
      decisionTrace: {
        dataChecked: ["field profile", "weather", "logs", "observations", "knowledge snippets"],
        toolsUsed: planner.tools,
        confidenceDrivers: dataQuality.confidenceDrivers,
        uncertainty: dataQuality.missingData,
      },
      knowledgeSources: kb.map((chunk) => ({ id: chunk.chunkId, title: chunk.source.title, topic: chunk.source.topic })),
      verificationPlan: {
        when: "After action or by end of day",
        checks: ["compare log vs recommendation", "capture field condition update"],
      },
    };

    decision = safetyGuardrails.apply(decision, { weather });
    memoryStore.updateFieldMemory(fieldId, { type: "decision", payload: decision });
    return decision;
  },
};
