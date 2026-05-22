import { emptyReportFromDecision } from "../../schemas/report";
import { isDecisionOutput } from "../../schemas/decision";
import { writeEarthDailyAudit } from "../../lib/audit/trace";

export interface ReportRouteEnv {
  DB?: D1Database;
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
  const report = emptyReportFromDecision(candidate);
  if (env.DB) {
    await writeEarthDailyAudit(env.DB, {
      decision_id: candidate.decision_id,
      step: "report",
      status: "fallback",
      duration_ms: Date.now() - started,
      request_id: requestId,
      meta: { deterministic_template: true },
    });
  }
  return report;
}

