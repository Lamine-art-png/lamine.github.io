export interface DecisionReadEnv {
  DB?: D1Database;
}

export async function handleDecisionRead(env: DecisionReadEnv, decisionId: string) {
  if (!env.DB) {
    throw Object.assign(new Error("D1 database is not configured."), { code: "db_unavailable", status: 503 });
  }
  const row = await env.DB
    .prepare(`SELECT decision_json FROM earthdaily_decisions WHERE decision_id = ?`)
    .bind(decisionId)
    .first<{ decision_json: string }>();

  if (!row) {
    throw Object.assign(new Error("Decision not found."), { code: "decision_not_found", status: 404 });
  }
  return JSON.parse(row.decision_json) as unknown;
}

