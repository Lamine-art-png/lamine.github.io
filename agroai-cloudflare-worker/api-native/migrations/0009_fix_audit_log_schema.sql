-- Migration 0009: Fix audit_log schema
--
-- The original audit_log was created by an earlier migration with only
-- (tenant_id, at, event, detail). Migration 0006 used CREATE TABLE IF NOT EXISTS
-- so it never replaced the old table. The code expects the richer schema.
--
-- Strategy: rename old table, create new one, copy compatible data, drop old.

ALTER TABLE audit_log RENAME TO audit_log_old;

CREATE TABLE audit_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     TEXT NOT NULL,
  action        TEXT NOT NULL,
  detail        TEXT,
  outcome       TEXT NOT NULL,
  url           TEXT,
  http_status   INTEGER,
  row_count     INTEGER,
  error_message TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_log_tenant
  ON audit_log (tenant_id, created_at DESC);

-- Migrate existing rows (map old columns to new)
INSERT INTO audit_log (tenant_id, action, detail, outcome, created_at)
  SELECT
    COALESCE(tenant_id, 'unknown'),
    COALESCE(event, 'legacy'),
    detail,
    'unknown',
    COALESCE(at, datetime('now'))
  FROM audit_log_old;

DROP TABLE audit_log_old;
