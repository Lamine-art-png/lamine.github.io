export interface DecisionAuditEnv {
  DB?: D1Database;
}

export async function handleDecisionAudit(env: DecisionAuditEnv, decisionId: string) {
  if (!env.DB) {
    throw Object.assign(new Error("D1 database is not configured."), { code: "db_unavailable", status: 503 });
  }
  const rows = await env.DB
    .prepare(
      `SELECT audit_id, decision_id, step, status, duration_ms, request_id, meta_json, created_at
       FROM earthdaily_audit
       WHERE decision_id = ?
       ORDER BY created_at ASC`,
    )
    .bind(decisionId)
    .all();

  return {
    decision_id: decisionId,
    entries: rows.results ?? [],
  };
}

