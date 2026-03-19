-- Talgil integration tables
-- Migration 0006: Core connector tables

-- Integration state per tenant
CREATE TABLE IF NOT EXISTS integrations_talgil (
  tenant_id        TEXT PRIMARY KEY,
  controller_id    INTEGER NOT NULL,
  controller_name  TEXT NOT NULL DEFAULT '',
  controller_online INTEGER NOT NULL DEFAULT 0,
  status           TEXT NOT NULL DEFAULT 'disconnected',
  last_sync_at     TEXT,
  last_error       TEXT,
  last_error_at    TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_full_image_json TEXT,
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Historical sensor readings
CREATE TABLE IF NOT EXISTS talgil_sensor_log (
  tenant_id      TEXT NOT NULL,
  controller_id  INTEGER NOT NULL,
  sensor_uid     TEXT NOT NULL,
  observed_at_ms INTEGER NOT NULL,
  observed_at    TEXT NOT NULL,
  value_num      REAL,
  raw_json       TEXT,
  PRIMARY KEY (tenant_id, controller_id, sensor_uid, observed_at_ms)
);

CREATE INDEX IF NOT EXISTS idx_sensor_log_tenant
  ON talgil_sensor_log (tenant_id, sensor_uid, observed_at_ms DESC);

-- Event log
CREATE TABLE IF NOT EXISTS talgil_event_log (
  tenant_id      TEXT NOT NULL,
  controller_id  INTEGER NOT NULL,
  event_key      TEXT NOT NULL,
  event_at_ms    INTEGER NOT NULL,
  event_at       TEXT NOT NULL,
  event_type     TEXT,
  source_key     TEXT,
  raw_json       TEXT,
  PRIMARY KEY (tenant_id, controller_id, event_key)
);

CREATE INDEX IF NOT EXISTS idx_event_log_tenant
  ON talgil_event_log (tenant_id, event_at_ms DESC);

-- Water consumption
CREATE TABLE IF NOT EXISTS talgil_valve_wc (
  tenant_id        TEXT NOT NULL,
  controller_id    INTEGER NOT NULL,
  valve_uid        TEXT NOT NULL,
  bucket_start_ms  INTEGER NOT NULL,
  bucket_start_at  TEXT NOT NULL,
  bucket_end_ms    INTEGER NOT NULL,
  bucket_end_at    TEXT NOT NULL,
  rate             TEXT NOT NULL,
  amount_value     REAL,
  raw_json         TEXT,
  PRIMARY KEY (tenant_id, controller_id, valve_uid, bucket_start_ms)
);

CREATE INDEX IF NOT EXISTS idx_valve_wc_tenant
  ON talgil_valve_wc (tenant_id, valve_uid, bucket_start_ms DESC);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
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
