import type { DecisionOutput } from "../../schemas/decision";

export type AuditStep = "normalize" | "decide" | "report" | "llm" | "live_fetch" | "demo_fallback";
export type AuditStatus = "ok" | "error" | "fallback";

export interface EarthDailyAuditEntry {
  decision_id: string;
  step: AuditStep;
  status: AuditStatus;
  duration_ms: number;
  request_id: string;
  meta?: Record<string, unknown>;
  created_at?: string;
}

export async function writeEarthDailyAudit(db: D1Database, entry: EarthDailyAuditEntry): Promise<void> {
  await db
    .prepare(
      `INSERT INTO earthdaily_audit
         (audit_id, decision_id, step, status, duration_ms, request_id, meta_json, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      crypto.randomUUID(),
      entry.decision_id,
      entry.step,
      entry.status,
      Math.max(0, Math.round(entry.duration_ms)),
      entry.request_id,
      entry.meta ? JSON.stringify(sanitizeAuditMeta(entry.meta)) : null,
      entry.created_at ?? new Date().toISOString(),
    )
    .run();
}

export async function persistEarthDailyDecision(
  db: D1Database,
  decision: DecisionOutput,
  mode: "demo" | "live",
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO earthdaily_decisions
         (decision_id, field_id, provider, mode, input_hash, recommendation_action, priority,
          confidence_score, rules_version, model_version, decision_json, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(decision_id) DO UPDATE SET
         decision_json = excluded.decision_json`,
    )
    .bind(
      decision.decision_id,
      decision.field_id,
      decision.trace.provider,
      mode,
      decision.trace.input_hash,
      decision.recommendation.action,
      decision.recommendation.priority,
      decision.confidence.score,
      decision.trace.rules_version,
      decision.trace.model_version,
      JSON.stringify(decision),
      decision.trace.created_at,
    )
    .run();
}

export function sanitizeAuditMeta(value: Record<string, unknown>): Record<string, unknown> {
  const output: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(value)) {
    const lower = key.toLowerCase();
    if (lower.includes("secret") || lower.includes("token") || lower.includes("api_key") || lower.includes("client_id")) {
      output[key] = "[redacted]";
      continue;
    }
    if (typeof raw === "string") {
      output[key] = raw.length > 500 ? `${raw.slice(0, 500)}...` : raw;
    } else if (typeof raw === "number" || typeof raw === "boolean" || raw === null) {
      output[key] = raw;
    } else if (Array.isArray(raw)) {
      output[key] = raw.slice(0, 20);
    } else if (typeof raw === "object") {
      output[key] = "[object metadata redacted]";
    }
  }
  return output;
}

