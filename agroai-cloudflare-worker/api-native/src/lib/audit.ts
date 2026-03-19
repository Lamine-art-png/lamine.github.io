/**
 * Audit logging for Talgil integration.
 * Every sync action, connection event, and error is logged
 * with enough detail to reconstruct exactly what happened.
 */

export interface AuditEntry {
  tenant_id: string;
  action: string;
  detail: string;
  outcome: "success" | "failure" | "skipped";
  url?: string;
  http_status?: number;
  row_count?: number;
  error_message?: string;
}

export async function writeAudit(
  db: D1Database,
  entry: AuditEntry,
): Promise<void> {
  try {
    await db
      .prepare(
        `INSERT INTO audit_log (tenant_id, action, detail, outcome, url, http_status, row_count, error_message, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))`,
      )
      .bind(
        entry.tenant_id,
        entry.action,
        entry.detail,
        entry.outcome,
        entry.url ?? null,
        entry.http_status ?? null,
        entry.row_count ?? null,
        entry.error_message ?? null,
      )
      .run();
  } catch {
    // Audit write failure must not break the sync flow.
    console.error("[audit] Failed to write audit entry:", entry.action);
  }
}
