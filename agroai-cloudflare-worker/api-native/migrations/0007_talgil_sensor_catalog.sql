-- Talgil sensor catalog
-- Migration 0007: Sensor metadata populated from full image response
--
-- Design note: This table is populated from the full controller image
-- (GET /targets/{id}/), NOT from a separate /sensors call.
-- Kosta explicitly stated that requesting sensors separately makes no sense
-- because they are already included in the full image.

CREATE TABLE IF NOT EXISTS talgil_sensor_catalog (
  tenant_id        TEXT NOT NULL,
  controller_id    INTEGER NOT NULL,
  sensor_uid       TEXT NOT NULL,
  sensor_name      TEXT,
  sensor_type      TEXT,
  units            TEXT,
  data_source      TEXT NOT NULL DEFAULT 'full_image',
  last_seen_at_ms  INTEGER NOT NULL,
  last_seen_at     TEXT NOT NULL,
  raw_json         TEXT,
  PRIMARY KEY (tenant_id, controller_id, sensor_uid)
);

CREATE INDEX IF NOT EXISTS idx_sensor_catalog_tenant
  ON talgil_sensor_catalog (tenant_id, controller_id);
