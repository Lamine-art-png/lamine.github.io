export function addAuditLog(state, action, actor, metadata) {
  state.app.auditLogs.unshift({
    id: `audit_${Math.random().toString(36).slice(2, 8)}`,
    action,
    actor,
    at: new Date().toISOString(),
    metadata,
  });
}
