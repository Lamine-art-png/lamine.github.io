import { modelRouter } from "./modelRouter.js";
import { agentPlanner } from "./agentPlanner.js";
import { createToolRegistry } from "./toolRegistry.js";
import { irrigationDecisionAgent } from "./irrigationDecisionAgent.js";
import { verificationAgent } from "./verificationAgent.js";
import { translationAgent } from "./translationAgent.js";
import { multimodalProcessor } from "./multimodalProcessor.js";

export function createAiOrchestrator(context) {
  const tools = createToolRegistry(context);

  return {
    runGoal({ goal, fieldId, language = "en", payload = {} }) {
      const planner = agentPlanner.plan(goal);
      const modelInfo = modelRouter.route(goal.includes("translate") ? "translate" : "reasoning");

      if (goal === "daily irrigation decision") {
        const decision = irrigationDecisionAgent.decide({ fieldId, tools, planner });
        const verification = verificationAgent.verify({ recommendation: decision, irrigationLogs: context.getIrrigationLogs(fieldId), observations: context.getFieldObservations(fieldId) });
        const localizedExplanation = translationAgent.translate(decision.reasons[0], language);
        return { type: "decision", model: modelInfo.id, decision, verification, localizedExplanation };
      }

      if (goal === "explain recommendation") {
        const latest = context.getRecommendationHistory(fieldId)[0]?.rec;
        const explanation = tools.get("generateExplanation").execute({ decision: latest || payload.decision || {} });
        return { type: "explanation", model: modelInfo.id, text: translationAgent.translate(explanation, language), decisionTrace: planner.steps };
      }

      if (goal === "analyze field note") {
        return { type: "note_analysis", model: modelInfo.id, analysis: multimodalProcessor.classifyTextNote(payload.note || ""), decisionTrace: planner.steps };
      }

      if (goal === "translate response") {
        return { type: "translation", model: modelInfo.id, translated: translationAgent.translate(payload.text || "", language) };
      }

      return { type: "generic", model: modelInfo.id, decisionTrace: planner.steps, summary: `Goal '${goal}' handled with mock orchestration.` };
    },
    tools,
  };
}
