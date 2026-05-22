import { buildReportObject } from "../../core/reporting/report";
import { isDecisionOutput } from "../../schemas/decision";
import { writeEarthDailyAudit } from "../../lib/audit/trace";
import { isNormalizedSignalPack, type NormalizedSignalPack } from "../../schemas/signals";

export interface ReportRouteEnv {
  DB?: D1Database;
  AGROAI_LLM_API_KEY?: string;
  AGROAI_LLM_MODEL?: string;
}

export async function handleEarthDailyReport(body: unknown, env: ReportRouteEnv, requestId: string) {
  const started = Date.now();
  const candidate = (body as { decision_output?: unknown })?.decision_output ?? body;
  if (!isDecisionOutput(candidate)) {
    throw Object.assign(new Error("Report input must include a DecisionOutput."), {
      code: "invalid_decision_output",
      status: 400,
    });
  }
  const pack: NormalizedSignalPack | null = isNormalizedSignalPack((body as { normalized_signal_pack?: unknown })?.normalized_signal_pack)
    ? (body as { normalized_signal_pack: NormalizedSignalPack }).normalized_signal_pack
    : null;
  const result = await buildReportObject(candidate, pack, env);
  if (env.DB) {
    await writeEarthDailyAudit(env.DB, {
      decision_id: candidate.decision_id,
      step: "report",
      status: result.ai_review.used_llm ? "ok" : "fallback",
      duration_ms: Date.now() - started,
      request_id: requestId,
      meta: { deterministic_template: result.ai_review.fallback_used, model: result.ai_review.model ?? "none" },
    });
  }
  return result.report_object;
}
