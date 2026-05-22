import type { DecisionOutput } from "../../schemas/decision";
import type { LLMReportPayload } from "../../schemas/report";
import type { NormalizedSignalPack } from "../../schemas/signals";

export type ReportObjective = "advisor_summary" | "executive_summary" | "grower_message" | "technical_explanation";
export type ReportAudience = "technical" | "advisor" | "grower" | "executive";

export interface LLMReportInput {
  normalized_signal_pack: NormalizedSignalPack;
  decision_output: DecisionOutput;
  risk_flags: DecisionOutput["risk_flags"];
  confidence: DecisionOutput["confidence"];
  report_objective: ReportObjective;
  audience: ReportAudience;
}

const AUDIENCE_GUIDANCE: Record<ReportAudience, string> = {
  technical: "Use precise agronomic and API language suitable for integration review.",
  advisor: "Use concise advisory language suitable for an irrigation consultant.",
  grower: "Use plain grower-facing language without API terminology.",
  executive: "Use commercial-demo language focused on data-in, decision-out value.",
};

export function buildReportPrompt(input: LLMReportInput): string {
  return JSON.stringify({
    instruction: [
      "Return strict JSON only.",
      "Do not include markdown or code fences.",
      "Do not change any decision_output.recommendation fields.",
      "Translate deterministic reasoning tokens into concise report prose.",
      AUDIENCE_GUIDANCE[input.audience],
    ],
    required_schema: {
      executive_summary: "1-3 sentences",
      decision_explanation: "2-5 sentences",
      risk_interpretation: "string",
      recommended_next_actions: ["string"],
      limitations: "string",
      commercial_demo_narrative: "string",
    } satisfies Record<keyof LLMReportPayload, unknown>,
    input,
  });
}

