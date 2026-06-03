import { ragEngine } from "./ragEngine.js";
import { weatherRiskAgent } from "./weatherRiskAgent.js";
import { safetyGuardrails } from "./safetyGuardrails.js";
import { memoryStore } from "./memoryStore.js";
import { modelRouter } from "./modelRouter.js";
import { createWeatherProvider } from "../services/weatherProviderFactory.js";
import { buildNormalizedFieldContext, calculateDeterministicSignals, deterministicDecisionFromSignals } from "./deterministicIrrigation.js";
import { decisionResponseSchema, normalizeDecisionResponse, parseDecisionJson, validateDecisionResponse } from "./decisionSchema.js";
import { scoreEvidence } from "./confidenceEngine.js";

const label = (score) => (score >= 0.75 ? "high" : score >= 0.5 ? "moderate" : "low");

function redactableContextForPrompt({ context, signals, memory, rag }) {
  return {
    field: {
      crop: context.crop,
      acreage: context.acreage,
      soilType: context.soilType,
      irrigationMethod: context.irrigationMethod,
      dataSource: context.dataSource,
      waterStressLevel: context.waterStressLevel,
      hasSensorData: Boolean(context.sensorData),
      hasControllerStatus: Boolean(context.controllerStatus),
      lastIrrigationAt: context.lastIrrigationAt,
      recentObservation: context.recentObservation,
    },
    weather: {
      temperature: context.weather?.temperature,
      humidity: context.weather?.humidity,
      wind: context.weather?.wind,
      rainChance: context.weather?.rainChance,
      rainfallForecastMm: context.weather?.rainfallForecastMm,
      forecastSummary: context.weather?.forecastSummary,
      heatRisk: context.weather?.heatRisk,
      frostRisk: context.weather?.frostRisk,
      stale: context.weather?.stale,
      source: context.weather?.weatherSource || context.weather?.source,
      timestamp: context.weather?.weatherTimestamp || context.weather?.lastUpdated,
      etLabel: context.weather?.etLabel,
    },
    deterministicSignals: {
      needScore: Number(signals.needScore.toFixed(2)),
      pressureLabel: signals.pressureLabel,
      recommendedAction: signals.action,
      urgency: signals.urgency,
      missingData: signals.missingData,
      rulesTriggered: signals.rulesTriggered,
      assumptions: signals.assumptions,
    },
    memory: {
      recentRecommendations: memory.recommendationHistory?.slice(0, 3) || [],
      recentLogs: memory.recentLogs || memory.irrigationLogs?.slice(0, 3) || [],
      recentObservations: memory.recentObservations || memory.observations?.slice(0, 3) || [],
      recurringPatterns: memory.recurringPatterns || [],
    },
    retrievedKnowledge: (rag.chunks || []).map((chunk) => ({
      id: chunk.source?.id,
      title: chunk.source?.title,
      topic: chunk.source?.topic,
      text: chunk.text,
      relevanceScore: chunk.relevanceScore,
    })),
  };
}

function buildReasoningPrompt(payload) {
  return `You are Velia, a field-specific irrigation decision engine.
Return only JSON matching the schema. Use the deterministic signals as safety-authoritative constraints.
Do not invent sensor data, exact soil moisture, satellite evidence, weather, sources, yield guarantees, or water-savings guarantees.
If data is missing, name it and choose the smallest useful field check.

Structured context:
${JSON.stringify(payload, null, 2)}`;
}

async function resolveWeather({ field, providedWeather, location }) {
  const coords = field.coordinates || location?.coordinates || null;
  const providerInput = {
    location: location?.location || field.location || providedWeather?.location || "farm",
    lat: field.lat ?? field.latitude ?? coords?.lat ?? providedWeather?.lat ?? null,
    lon: field.lon ?? field.longitude ?? coords?.lon ?? providedWeather?.lon ?? null,
  };
  const provider = createWeatherProvider();
  if ((provider.name === "mock" || provider.mode !== "live") && providedWeather) {
    return { ...providedWeather, providerMode: providedWeather.providerMode || "input", weatherSource: providedWeather.weatherSource || providedWeather.source || "input" };
  }
  if (providedWeather && !providedWeather.stale && providerInput.lat == null) {
    return { ...providedWeather, providerMode: "input", weatherSource: providedWeather.weatherSource || providedWeather.source || "input" };
  }
  const weather = await provider.getContext(providerInput);
  return providedWeather && weather?.fallbackStatus?.includes("missing_coordinates")
    ? { ...providedWeather, providerMode: "input", weatherSource: providedWeather.weatherSource || providedWeather.source || "input" }
    : weather;
}

async function callReasoningModel({ prompt, fallbackDecision, provider }) {
  if (provider.mode !== "live") {
    return {
      decision: fallbackDecision,
      provider,
      fallbackUsed: true,
      fallbackReason: provider.fallbackReason || "No live reasoning provider configured",
      repairAttempted: false,
    };
  }

  try {
    const first = await provider.generate(prompt, {
      task: "irrigation_decision",
      schema: decisionResponseSchema,
      schemaName: "velia_irrigation_decision",
      fallbackDecision,
    });
    let parsed = null;
    let validation;
    try {
      parsed = parseDecisionJson(first.text);
      validation = validateDecisionResponse(parsed);
    } catch (error) {
      validation = { ok: false, errors: [error.message] };
    }
    if (validation.ok) {
      return { decision: normalizeDecisionResponse(parsed, fallbackDecision), provider, fallbackUsed: false, repairAttempted: false };
    }

    const repair = await provider.generate(`${prompt}

The previous output was invalid: ${validation.errors.join("; ")}.
Repair it now. Return only valid JSON matching the schema. Previous output:
${first.text}`, {
      task: "irrigation_decision_repair",
      schema: decisionResponseSchema,
      schemaName: "velia_irrigation_decision",
      fallbackDecision,
      temperature: 0,
    });
    try {
      parsed = parseDecisionJson(repair.text);
      validation = validateDecisionResponse(parsed);
    } catch (error) {
      validation = { ok: false, errors: [error.message] };
    }
    if (validation.ok) {
      return { decision: normalizeDecisionResponse(parsed, fallbackDecision), provider, fallbackUsed: false, repairAttempted: true };
    }

    return {
      decision: fallbackDecision,
      provider,
      fallbackUsed: true,
      fallbackReason: `Malformed model response after repair: ${validation.errors.join("; ")}`,
      repairAttempted: true,
    };
  } catch (error) {
    return {
      decision: fallbackDecision,
      provider,
      fallbackUsed: true,
      fallbackReason: error.message,
      repairAttempted: false,
    };
  }
}

function mergeDecision({ modelDecision, fallbackDecision, signals, context, rag, modelResult, plannerTools }) {
  const merged = normalizeDecisionResponse(modelDecision, fallbackDecision);
  const guardrailsTriggered = [];

  if (merged.action === "irrigate" && fallbackDecision.action !== "irrigate") {
    merged.action = fallbackDecision.action;
    merged.timing = fallbackDecision.timing;
    merged.urgency = fallbackDecision.urgency;
    guardrailsTriggered.push("deterministic_layer_overrode_model_irrigate");
  }
  const escalationAttempted = ["irrigate"].includes(merged.action) && !["irrigate"].includes(fallbackDecision.action);
  if (escalationAttempted) {
    guardrailsTriggered.push("model_escalation_blocked");
  }

  const evidenceScore = scoreEvidence(context);
  const confidenceScore = Math.max(0.1, Math.min(0.95,
    evidenceScore.confidenceScore
    + (modelResult.fallbackUsed ? -0.04 : 0.03)
    + (rag.fallbackUsed ? -0.04 : 0),
  ));
  const weatherRisk = weatherRiskAgent.assess(context.weather);
  const decisionTimestamp = new Date().toISOString();
  const provenance = {
    providerMode: modelResult.provider.mode,
    provider: modelResult.provider.name,
    modelUsed: modelResult.provider.model,
    weatherSource: context.weather?.weatherSource || context.weather?.source || "unknown",
    weatherTimestamp: context.weather?.weatherTimestamp || context.weather?.lastUpdated || null,
    weatherStale: Boolean(context.weather?.stale),
    weatherAgeMinutes: context.weather?.freshness?.ageMinutes ?? null,
    dataSourcesChecked: ["field profile", "field memory", "weather", "irrigation logs", "observations", "deterministic signals", "RAG knowledge", "reasoning model"],
    ragSourcesUsed: rag.sources || [],
    deterministicRulesTriggered: signals.rulesTriggered,
    missingData: signals.missingData,
    guardrailsTriggered,
    fallbackStatus: {
      llmFallbackUsed: modelResult.fallbackUsed,
      llmFallbackReason: modelResult.fallbackReason || null,
      repairAttempted: modelResult.repairAttempted,
      ragFallbackUsed: Boolean(rag.fallbackUsed),
      ragFallbackReason: rag.fallbackReason || null,
      weatherFallbackStatus: context.weather?.fallbackStatus || null,
    },
    decisionTimestamp,
  };

  const finalDecision = {
    decisionId: `dec-${Date.now()}`,
    fieldId: context.fieldId,
    ...merged,
    risks: [...new Set([...(merged.risks || []), ...weatherRisk.risks])],
    confidenceScore,
    confidenceLabel: label(confidenceScore),
    evidenceQuality: {
      score: evidenceScore.confidenceScore,
      label: evidenceScore.confidenceLabel,
      evidenceChecked: evidenceScore.evidenceChecked,
      missingEvidence: evidenceScore.missingEvidence,
      conflictingEvidence: evidenceScore.conflictingEvidence,
      explanation: evidenceScore.explanation,
      improvementSuggestions: evidenceScore.improvementSuggestions,
    },
    deterministicSignals: {
      needScore: Number(signals.needScore.toFixed(2)),
      estimatedWaterPressure: signals.estimatedWaterPressure,
    },
    decisionTrace: {
      dataChecked: provenance.dataSourcesChecked,
      toolsUsed: plannerTools,
      confidenceDrivers: signals.confidenceDrivers,
      uncertainty: signals.missingData,
      deterministicRulesTriggered: signals.rulesTriggered,
    },
    knowledgeSources: provenance.ragSourcesUsed,
    provenance,
    verificationPlan: Array.isArray(merged.verificationPlan)
      ? { checks: merged.verificationPlan, when: "After action or by end of day" }
      : merged.verificationPlan,
  };

  const safeDecision = safetyGuardrails.enforce(finalDecision, { weather: context.weather, deterministicSignals: signals, fieldContext: context });
  safeDecision.provenance = {
    ...safeDecision.provenance,
    guardrailsTriggered: safeDecision.guardrailsTriggered || [],
  };
  return safeDecision;
}

export const irrigationDecisionAgent = {
  async decide({ field, weather = null, location = null, logs = [], observations = [], plannerTools = [] }) {
    const fieldMemory = memoryStore.getFieldMemory(field.id || field.fieldId || "unknown-field");
    const weatherContext = await resolveWeather({ field, providedWeather: weather, location });
    const normalizedContext = buildNormalizedFieldContext({
      field,
      weather: weatherContext,
      logs,
      observations,
      memory: fieldMemory,
    });

    const signals = calculateDeterministicSignals(normalizedContext);
    const fallbackDecision = deterministicDecisionFromSignals(signals, normalizedContext);
    const rag = await ragEngine.retrieve(`${normalizedContext.crop || "crop"} ${normalizedContext.soilType || "soil"} irrigation weather risk missing data verification`, { topK: 5 });
    const provider = modelRouter.llmProvider();
    const promptContext = redactableContextForPrompt({ context: normalizedContext, signals, memory: fieldMemory, rag });
    const prompt = buildReasoningPrompt(promptContext);
    const modelResult = await callReasoningModel({ prompt, fallbackDecision, provider });
    const finalDecision = mergeDecision({
      modelDecision: modelResult.decision,
      fallbackDecision,
      signals,
      context: normalizedContext,
      rag,
      modelResult,
      plannerTools,
    });

    memoryStore.updateFieldMemory(normalizedContext.fieldId, { type: "decision", payload: finalDecision });
    return finalDecision;
  },
};
