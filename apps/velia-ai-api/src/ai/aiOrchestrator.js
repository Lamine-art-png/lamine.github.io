import { modelRouter } from "./modelRouter.js";
import { agentPlanner } from "./agentPlanner.js";
import { createToolRegistry } from "./toolRegistry.js";
import { irrigationDecisionAgent } from "./irrigationDecisionAgent.js";
import { verificationAgent } from "./verificationAgent.js";
import { translationAgent } from "./translationAgent.js";
import { multimodalProcessor } from "./multimodalProcessor.js";
import { memoryStore } from "./memoryStore.js";

function compactList(items = [], fallback = "None recorded") {
  return items.length ? items.join("; ") : fallback;
}

function describeChange(history = []) {
  if (history.length < 2) return "I do not have a prior decision to compare yet.";
  const [latest, previous] = history;
  const latestRec = latest.rec || latest;
  const previousRec = previous.rec || previous;
  const changes = [];
  if (latestRec.action !== previousRec.action) changes.push(`action changed from ${previousRec.action} to ${latestRec.action}`);
  if (latestRec.urgency !== previousRec.urgency) changes.push(`urgency changed from ${previousRec.urgency} to ${latestRec.urgency}`);
  if ((latestRec.missingData || []).join(",") !== (previousRec.missingData || []).join(",")) changes.push("missing-data list changed");
  return changes.length ? changes.join("; ") : "The latest decision is broadly similar to the previous one.";
}

function buildAssistantAnswer({ query = "", decision = {}, memory = {}, verification = null }) {
  const q = query.toLowerCase();
  const sources = decision.knowledgeSources || decision.provenance?.ragSourcesUsed || [];
  const provenance = decision.provenance || {};
  let answer;

  if (/should i irrigate|irrigate today/.test(q)) {
    answer = `Terris recommends: ${decision.action || "check field first"}. Timing: ${decision.timing || "today"}. Confidence is ${decision.confidenceLabel || "moderate"} because ${compactList(decision.reasons || [])}.`;
  } else if (/why\b|reason|explain/.test(q)) {
    answer = `The main reasons are: ${compactList(decision.reasons || [])}. Deterministic rules checked: ${compactList(provenance.deterministicRulesTriggered || [])}.`;
  } else if (/missing|need from me|what information/.test(q)) {
    answer = `Terris is missing: ${compactList(decision.missingData || [])}. Improving those items should raise confidence more than adding general notes.`;
  } else if (/check.*field|field check|what should i check/.test(q)) {
    answer = `Check: ${compactList(decision.fieldChecks || [])}. Then record the result so tomorrow's recommendation has stronger field evidence.`;
  } else if (/changed since yesterday|what changed/.test(q)) {
    answer = describeChange(memory.recommendationHistory || []);
  } else if (/did i follow|followed|verification/.test(q)) {
    const status = verification?.status || memory.verificationOutcomes?.[0]?.status || "no_confirmation";
    answer = `Verification status: ${status}. ${verification?.details || memory.verificationOutcomes?.[0]?.details || "I do not see enough logged evidence yet."}`;
  } else if (/weather risk|heat|frost|rain/.test(q)) {
    answer = `Weather risk: ${compactList(decision.risks || [])}. Weather source: ${provenance.weatherSource || "unknown"}${provenance.weatherStale ? " (stale)" : ""}.`;
  } else {
    answer = `Best next action: ${decision.nextBestAction || "update field condition"}. Confidence is ${decision.confidenceLabel || "moderate"}; missing data: ${compactList(decision.missingData || [])}.`;
  }

  return {
    answer,
    sources,
    provenance: {
      providerMode: provenance.providerMode || "local",
      modelUsed: provenance.modelUsed || null,
      weatherSource: provenance.weatherSource || null,
      weatherStale: Boolean(provenance.weatherStale),
      ragSourcesUsed: sources,
      fallbackStatus: provenance.fallbackStatus || null,
    },
  };
}

export const aiOrchestrator = {
  async run(goal, payload = {}) {
    const planner = agentPlanner.plan(goal);
    const tools = createToolRegistry(payload);
    const model = modelRouter.route(goal.includes("translate") ? "translate" : "reasoning");

    if (goal === "daily irrigation decision") {
      const decision = await irrigationDecisionAgent.decide({
        field: payload.field,
        weather: payload.weather,
        location: payload.location,
        logs: payload.logs || [],
        observations: payload.observations || [],
        plannerTools: planner.tools,
      });
      const verification = verificationAgent.verify({ recommendation: decision, logs: payload.logs || [], observations: payload.observations || [] });
      memoryStore.updateFieldMemory(decision.fieldId, { type: "verification", payload: verification });
      return { type: "decision", model: decision.provenance?.modelUsed || model.id, decision, verification, decisionTrace: decision.decisionTrace };
    }

    if (goal === "assistant query" || goal === "explain recommendation") {
      const decision = payload.decision || payload.recommendationHistory?.[0]?.rec || {};
      const fieldId = payload.fieldId || decision.fieldId || payload.field?.id || "unknown-field";
      const memory = memoryStore.summarizeFieldMemory(fieldId);
      const verification = payload.verification || null;
      const grounded = buildAssistantAnswer({ query: payload.query || "Why?", decision, memory, verification });
      return {
        type: "assistant",
        model: decision.provenance?.modelUsed || model.id,
        answer: await translationAgent.translate(grounded.answer, payload.language || "en"),
        decisionTrace: planner.decisionTrace,
        toolsUsed: planner.tools,
        confidence: decision.confidenceScore || 0.5,
        sources: grounded.sources,
        provenance: grounded.provenance,
      };
    }

    if (goal === "analyze field note") {
      return { type: "analysis", model: model.id, result: multimodalProcessor.classifyText(payload.note || ""), decisionTrace: planner.decisionTrace };
    }

    if (goal === "translate response") {
      return { type: "translation", model: model.id, translated: await translationAgent.translate(payload.text || "", payload.language || "en") };
    }

    return { type: "generic", model: model.id, decisionTrace: planner.decisionTrace, toolsUsed: planner.tools, answer: "Goal processed with grounded local orchestration." };
  },
};
