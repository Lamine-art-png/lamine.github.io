import { ragEngine } from "./ragEngine.js";
import { fieldReasoningAgent } from "./fieldReasoningAgent.js";
import { weatherRiskAgent } from "./weatherRiskAgent.js";
import { safetyGuardrails } from "./safetyGuardrails.js";
import { memoryStore } from "./memoryStore.js";

const label = (score) => (score >= 0.75 ? "high" : score >= 0.5 ? "moderate" : "low");

export const irrigationDecisionAgent = {
  async decide({ field, weather, logs = [], observations = [], plannerTools = [] }) {
    const dataQuality = fieldReasoningAgent.evaluate(field, weather);
    const risk = weatherRiskAgent.assess(weather);
    const knowledge = await ragEngine.retrieve(`${field.crop || "crop"} irrigation weather confidence`);

    let needScore = field.waterStressLevel === "high" ? 0.82 : field.waterStressLevel === "moderate" ? 0.6 : 0.35;
    if (risk.risks.includes("heat_risk")) needScore += 0.12;
    if (risk.risks.includes("rain_likely")) needScore -= 0.2;
    if (observations[0]?.condition === "Looks dry") needScore += 0.1;
    if (observations[0]?.condition === "Looks too wet") needScore -= 0.25;
    needScore = Math.max(0.1, Math.min(0.95, needScore));

    const action = needScore > 0.75 ? "irrigate" : needScore > 0.45 ? "check field first" : risk.risks.includes("rain_likely") ? "wait" : "monitor";
    const decision = {
      decisionId: `dec-${Date.now()}`,
      fieldId: field.id,
      action,
      timing: action === "irrigate" ? "Next 2-4 hours" : "Today before evening",
      urgency: needScore > 0.75 ? "high" : needScore > 0.45 ? "medium" : "low",
      estimatedDurationRange: action === "irrigate" ? "45-90 min" : "check only",
      confidenceScore: Math.max(0.2, needScore - dataQuality.missingData.length * 0.08),
      confidenceLabel: "",
      reasons: [
        `Weather: ${weather.forecastSummary || "unknown"}`,
        `Observation: ${observations[0]?.condition || "none"}`,
        `Need score: ${needScore.toFixed(2)}`,
      ],
      uncertainties: dataQuality.missingData.length ? [`Missing ${dataQuality.missingData.join(", ")}`] : ["No major data uncertainty"],
      missingData: dataQuality.missingData,
      fieldChecks: ["Check topsoil before irrigation", "Confirm condition after action"],
      risks: risk.risks,
      nextBestAction: action === "irrigate" ? "Log irrigation after execution" : "Update field condition",
      decisionTrace: {
        dataChecked: ["field profile", "weather", "logs", "observations", "knowledge"],
        toolsUsed: plannerTools,
        confidenceDrivers: dataQuality.confidenceDrivers,
        uncertainty: dataQuality.missingData,
      },
      knowledgeSources: knowledge.map((k) => ({ source: k.source, score: k.score })),
      verificationPlan: { checks: ["compare recommendation and log", "capture post-action observation"] },
    };

    decision.confidenceLabel = label(decision.confidenceScore);
    const safe = safetyGuardrails.enforce(decision, weather);
    memoryStore.updateFieldMemory(field.id, { type: "decision", payload: safe });
    return safe;
  },
};
