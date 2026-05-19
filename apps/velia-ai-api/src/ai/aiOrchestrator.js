import { modelRouter } from "./modelRouter.js";
import { agentPlanner } from "./agentPlanner.js";
import { createToolRegistry } from "./toolRegistry.js";
import { irrigationDecisionAgent } from "./irrigationDecisionAgent.js";
import { verificationAgent } from "./verificationAgent.js";
import { translationAgent } from "./translationAgent.js";
import { multimodalProcessor } from "./multimodalProcessor.js";

export const aiOrchestrator = {
  async run(goal, payload) {
    const planner = agentPlanner.plan(goal);
    const tools = createToolRegistry(payload);
    const model = modelRouter.route(goal.includes("translate") ? "translate" : "reasoning");

    if (goal === "daily irrigation decision") {
      const decision = await irrigationDecisionAgent.decide({ field: payload.field, weather: payload.weather, logs: payload.logs || [], observations: payload.observations || [], plannerTools: planner.tools });
      const verification = verificationAgent.verify({ recommendation: decision, logs: payload.logs || [], observations: payload.observations || [] });
      return { type: "decision", model: model.id, decision, verification, decisionTrace: decision.decisionTrace };
    }

    if (goal === "explain recommendation") {
      const decision = payload.decision || payload.recommendationHistory?.[0]?.rec || {};
      const explanation = tools.get("generateExplanation").execute({ decision });
      return { type: "assistant", model: model.id, answer: await translationAgent.translate(explanation, payload.language || "en"), decisionTrace: planner.decisionTrace, toolsUsed: planner.tools, confidence: decision.confidenceScore || 0.5, sources: decision.knowledgeSources || [] };
    }

    if (goal === "analyze field note") {
      return { type: "analysis", model: model.id, result: multimodalProcessor.classifyText(payload.note || ""), decisionTrace: planner.decisionTrace };
    }

    if (goal === "translate response") {
      return { type: "translation", model: model.id, translated: await translationAgent.translate(payload.text || "", payload.language || "en") };
    }

    return { type: "generic", model: model.id, decisionTrace: planner.decisionTrace, toolsUsed: planner.tools, answer: "Goal processed with mock orchestrator." };
  },
};
