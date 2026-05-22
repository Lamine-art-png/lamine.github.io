import { buildDemoEarthDailyInput } from "../../adapters/earthdaily/demoAdapter";
import { runDecisionEngine } from "../../core/decision/engine";
import { normalizeEarthDailyInput } from "../../core/normalization/normalize";
import { hashEarthDailyInput } from "../../lib/audit/hash";
import { persistEarthDailyDecision, writeEarthDailyAudit } from "../../lib/audit/trace";
import { validateEarthDailyRawInput } from "../../schemas/earthdaily";
import { emptyReportFromDecision } from "../../schemas/report";

export interface EndToEndRouteEnv {
  DB?: D1Database;
}

export async function handleEarthDailyEndToEnd(body: unknown, env: EndToEndRouteEnv, requestId: string) {
  const rawCandidate = resolveRawCandidate(body);
  const validation = validateEarthDailyRawInput(rawCandidate);
  if (!validation.ok || !validation.value) {
    throw Object.assign(new Error("EarthDaily end-to-end payload failed validation."), {
      code: validation.issues[0]?.code ?? "invalid_payload",
      status: 400,
      details: validation.issues,
    });
  }

  const raw = validation.value;
  const normalizedStart = Date.now();
  const normalized = normalizeEarthDailyInput(raw);
  const inputHash = await hashEarthDailyInput(raw);
  const decisionStart = Date.now();
  const decision = runDecisionEngine({ signalPack: normalized, inputHash });
  const report = emptyReportFromDecision(decision);

  if (env.DB) {
    await persistEarthDailyDecision(env.DB, decision, raw.mode);
    await writeEarthDailyAudit(env.DB, {
      decision_id: decision.decision_id,
      step: "normalize",
      status: "ok",
      duration_ms: decisionStart - normalizedStart,
      request_id: requestId,
      meta: { field_id: raw.field.field_id, provider_mode: raw.mode, input_hash: inputHash },
    });
    await writeEarthDailyAudit(env.DB, {
      decision_id: decision.decision_id,
      step: "decide",
      status: "ok",
      duration_ms: Date.now() - decisionStart,
      request_id: requestId,
      meta: { action: decision.recommendation.action, priority: decision.recommendation.priority },
    });
    await writeEarthDailyAudit(env.DB, {
      decision_id: decision.decision_id,
      step: "report",
      status: "fallback",
      duration_ms: 0,
      request_id: requestId,
      meta: { deterministic_template: true },
    });
  }

  return {
    earthdaily_raw_input: raw,
    normalized_signal_pack: normalized,
    decision_output: decision,
    ai_review: {
      skipped: true,
      reason: "AGROAI_LLM_API_KEY not evaluated in route phase; deterministic fallback report returned.",
    },
    report_object: report,
    audit_trace: [
      { step: "normalize", status: "ok" },
      { step: "decide", status: "ok" },
      { step: "report", status: "fallback" },
    ],
    integration_metadata: {
      provider: "earthdaily",
      mode: raw.mode,
      request_id: requestId,
      decision_id: decision.decision_id,
      live_claim: false,
      source: raw.metadata.source,
    },
  };
}

function resolveRawCandidate(body: unknown) {
  if (!body || (typeof body === "object" && Object.keys(body as Record<string, unknown>).length === 0)) {
    return buildDemoEarthDailyInput();
  }
  const record = body as { earthdaily_raw_input?: unknown; raw?: unknown };
  return record.earthdaily_raw_input ?? record.raw ?? body;
}

