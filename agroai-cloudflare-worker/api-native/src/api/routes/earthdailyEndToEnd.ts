import { loadEarthDailyInput } from "../../adapters/earthdaily";
import { runDecisionEngine } from "../../core/decision/engine";
import { normalizeEarthDailyInput } from "../../core/normalization/normalize";
import { hashEarthDailyInput } from "../../lib/audit/hash";
import { persistEarthDailyDecision, writeEarthDailyAudit } from "../../lib/audit/trace";
import { validateEarthDailyRawInput, type EarthDailyRawInput } from "../../schemas/earthdaily";
import type { Env } from "../../lib/cloudflare/env";
import { buildReportObject } from "../../core/reporting/report";

export async function handleEarthDailyEndToEnd(body: unknown, env: Env, requestId: string) {
  const adapterResult = await loadEarthDailyInput(env, resolveAdapterRequest(body));
  const rawCandidate = adapterResult.input;
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
  const reportStart = Date.now();
  const reportResult = await buildReportObject(decision, normalized, env);
  const decisionWithReport = reportResult.decision_output;

  if (env.DB) {
    await persistEarthDailyDecision(env.DB, decisionWithReport, raw.mode);
    await writeEarthDailyAudit(env.DB, {
      decision_id: decisionWithReport.decision_id,
      step: "normalize",
      status: "ok",
      duration_ms: decisionStart - normalizedStart,
      request_id: requestId,
      meta: { field_id: raw.field.field_id, provider_mode: raw.mode, input_hash: inputHash },
    });
    await writeEarthDailyAudit(env.DB, {
      decision_id: decisionWithReport.decision_id,
      step: "decide",
      status: "ok",
      duration_ms: Date.now() - decisionStart,
      request_id: requestId,
      meta: { action: decisionWithReport.recommendation.action, priority: decisionWithReport.recommendation.priority },
    });
    await writeEarthDailyAudit(env.DB, {
      decision_id: decisionWithReport.decision_id,
      step: "report",
      status: reportResult.ai_review.used_llm ? "ok" : "fallback",
      duration_ms: Date.now() - reportStart,
      request_id: requestId,
      meta: { deterministic_template: reportResult.ai_review.fallback_used, model: reportResult.ai_review.model ?? "none" },
    });
    if (adapterResult.usedFallback) {
      await writeEarthDailyAudit(env.DB, {
        decision_id: decisionWithReport.decision_id,
        step: "demo_fallback",
        status: "fallback",
        duration_ms: 0,
        request_id: requestId,
        meta: { reason: "live_fetch_unavailable_or_disabled" },
      });
    }
  }

  return {
    earthdaily_raw_input: raw,
    normalized_signal_pack: normalized,
    decision_output: decisionWithReport,
    ai_review: reportResult.ai_review,
    report_object: reportResult.report_object,
    audit_trace: [
      { step: "normalize", status: "ok" },
      { step: "decide", status: "ok" },
      { step: "report", status: "fallback" },
      ...(adapterResult.usedFallback ? [{ step: "demo_fallback", status: "fallback" }] : []),
    ],
    integration_metadata: {
      provider: "earthdaily",
      mode: raw.mode,
      request_id: requestId,
      decision_id: decisionWithReport.decision_id,
      live_claim: false,
      source: raw.metadata.source,
      used_fallback: adapterResult.usedFallback,
    },
  };
}

function resolveAdapterRequest(body: unknown) {
  if (!body || (typeof body === "object" && Object.keys(body as Record<string, unknown>).length === 0)) {
    return {};
  }
  const record = body as { earthdaily_raw_input?: unknown; raw?: unknown };
  const raw = record.earthdaily_raw_input ?? record.raw ?? body;
  return { raw: raw as EarthDailyRawInput };
}
