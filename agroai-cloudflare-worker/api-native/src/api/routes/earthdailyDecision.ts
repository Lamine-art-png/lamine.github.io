import { runDecisionEngine } from "../../core/decision/engine";
import { normalizeEarthDailyInput } from "../../core/normalization/normalize";
import { hashEarthDailyInput, sha256Hex, canonicalJson } from "../../lib/audit/hash";
import { persistEarthDailyDecision, writeEarthDailyAudit } from "../../lib/audit/trace";
import { validateEarthDailyRawInput } from "../../schemas/earthdaily";
import { isNormalizedSignalPack, type NormalizedSignalPack } from "../../schemas/signals";

export interface DecisionRouteEnv {
  DB?: D1Database;
}

export async function handleEarthDailyDecision(body: unknown, env: DecisionRouteEnv, requestId: string, mode: "demo" | "live" = "demo") {
  const started = Date.now();
  const { pack, inputHash } = await resolvePack(body);
  const decision = runDecisionEngine({ signalPack: pack, inputHash });

  if (env.DB) {
    await persistEarthDailyDecision(env.DB, decision, mode);
    await writeEarthDailyAudit(env.DB, {
      decision_id: decision.decision_id,
      step: "decide",
      status: "ok",
      duration_ms: Date.now() - started,
      request_id: requestId,
      meta: {
        field_id: decision.field_id,
        action: decision.recommendation.action,
        priority: decision.recommendation.priority,
        input_hash: inputHash,
        provider_mode: mode,
      },
    });
  }

  return decision;
}

export async function resolvePack(body: unknown): Promise<{ pack: NormalizedSignalPack; inputHash: string; mode: "demo" | "live" }> {
  if (isNormalizedSignalPack(body)) {
    return {
      pack: body,
      inputHash: await sha256Hex(canonicalJson(body)),
      mode: body.provider_trace.mode,
    };
  }

  const maybeBody = body as { normalized_signal_pack?: unknown; earthdaily_raw_input?: unknown; raw?: unknown };
  if (isNormalizedSignalPack(maybeBody?.normalized_signal_pack)) {
    const pack = maybeBody.normalized_signal_pack;
    return {
      pack,
      inputHash: await sha256Hex(canonicalJson(pack)),
      mode: pack.provider_trace.mode,
    };
  }

  const rawCandidate = maybeBody?.earthdaily_raw_input ?? maybeBody?.raw ?? body;
  const validation = validateEarthDailyRawInput(rawCandidate);
  if (!validation.ok || !validation.value) {
    throw routeError(validation.issues[0]?.code ?? "invalid_payload", "Decision input must be raw EarthDaily input or a normalized signal pack.", 400, validation.issues);
  }

  return {
    pack: normalizeEarthDailyInput(validation.value),
    inputHash: await hashEarthDailyInput(validation.value),
    mode: validation.value.mode,
  };
}

function routeError(code: string, message: string, status: number, details?: unknown): Error {
  return Object.assign(new Error(message), { code, status, details });
}

