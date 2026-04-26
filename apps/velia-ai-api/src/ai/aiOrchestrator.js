import { modelRouter } from "./modelRouter.js";
import { agentPlanner } from "./agentPlanner.js";
import { createToolRegistry } from "./toolRegistry.js";
import { irrigationDecisionAgent } from "./irrigationDecisionAgent.js";
import { verificationAgent } from "./verificationAgent.js";
import { translationAgent } from "./translationAgent.js";
import { multimodalProcessor } from "./multimodalProcessor.js";

async function llmAssist({ kind, prompt }) {
  const llm = modelRouter.llmProvider();
  const model = modelRouter.modelFor(kind);
  return llm.generate(prompt, { task: kind, model, temperature: 0.2 });
}

export const aiOrchestrator = {
  async run(goal, payload) {
    const planner = agentPlanner.plan(goal);
    const tools = createToolRegistry(payload);
    const routeKind = goal === "translate response" ? "translate" : goal === "analyze field note" ? "fast" : "reasoning";
    const model = modelRouter.route(routeKind);

    if (goal === "daily irrigation decision") {
      const decision = await irrigationDecisionAgent.decide({ field: payload.field, weather: payload.weather, logs: payload.logs || [], observations: payload.observations || [], plannerTools: planner.tools });
      const verification = verificationAgent.verify({ recommendation: decision, logs: payload.logs || [], observations: payload.observations || [] });
      return { type: "decision", model: model.id, decision, verification, decisionTrace: decision.decisionTrace };
    }

    if (goal === "explain recommendation") {
      const decision = payload.decision || payload.recommendationHistory?.[0]?.rec || {};
      const localExplanation = tools.get("generateExplanation").execute({ decision });
      let answer = localExplanation;

      try {
        const llmResult = await llmAssist({
          kind: "reasoning",
          prompt: `You are an irrigation assistant. Explain this recommendation in simple language with practical next step.\n\nRecommendation JSON: ${JSON.stringify(decision)}`,
        });
        if (llmResult?.text) answer = llmResult.text;
      } catch {
        // local fallback remains
      }

      return {
        type: "assistant",
        model: model.id,
        answer: await translationAgent.translate(answer, payload.language || "en"),
        decisionTrace: planner.decisionTrace,
        toolsUsed: planner.tools,
        confidence: decision.confidenceScore || 0.5,
        sources: decision.knowledgeSources || [],
      };
    }

    if (goal === "analyze field note") {
      const local = multimodalProcessor.classifyText(payload.note || "");
      try {
        const llmResult = await llmAssist({
          kind: "fast",
          prompt: `Classify this farm note as one of: dry, wet, stressed, normal, unknown. Return short reason.\n\nNote: ${payload.note || ""}`,
        });
        if (llmResult?.text) {
          return { type: "analysis", model: model.id, result: { label: local.label, llm: llmResult.text }, decisionTrace: planner.decisionTrace };
        }
      } catch {
        // fallback to local classification
      }

      return { type: "analysis", model: model.id, result: local, decisionTrace: planner.decisionTrace };
    }

    if (goal === "translate response") {
      return { type: "translation", model: model.id, translated: await translationAgent.translate(payload.text || "", payload.language || "en") };
    }

    return { type: "generic", model: model.id, decisionTrace: planner.decisionTrace, toolsUsed: planner.tools, answer: "Goal processed with mock orchestrator." };
  },
};
