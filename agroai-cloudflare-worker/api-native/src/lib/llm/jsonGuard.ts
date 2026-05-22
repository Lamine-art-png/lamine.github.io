import type { LLMReportPayload } from "../../schemas/report";

export function parseStrictJsonPayload(text: string): LLMReportPayload | null {
  const trimmed = stripLeadingFence(text.trim());
  try {
    const parsed = JSON.parse(trimmed) as Partial<LLMReportPayload>;
    if (typeof parsed.executive_summary !== "string") return null;
    if (typeof parsed.decision_explanation !== "string") return null;
    if (typeof parsed.risk_interpretation !== "string") return null;
    if (!Array.isArray(parsed.recommended_next_actions) || parsed.recommended_next_actions.some((item) => typeof item !== "string")) return null;
    if (typeof parsed.limitations !== "string") return null;
    if (typeof parsed.commercial_demo_narrative !== "string") return null;
    return parsed as LLMReportPayload;
  } catch (_error) {
    return null;
  }
}

function stripLeadingFence(value: string): string {
  if (!value.startsWith("```")) return value;
  return value
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();
}

