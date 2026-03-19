/**
 * D1 database helpers for Talgil integration tables.
 * All upserts use INSERT OR REPLACE to avoid duplicates.
 */

import type {
  SensorCatalogRow,
  SensorLogRow,
  EventLogRow,
  ValveWcRow,
} from "../mappers/talgil_map";

// ── integrations_talgil ─────────────────────────────────

export interface IntegrationRow {
  tenant_id: string;
  controller_id: number;
  controller_name: string;
  controller_online: number;
  status: string;
  last_sync_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  consecutive_failures: number;
  last_full_image_json: string | null;
  created_at: string;
  updated_at: string;
}

export async function upsertIntegration(
  db: D1Database,
  tenantId: string,
  controllerId: number,
  controllerName: string,
  controllerOnline: number,
  status: string,
  fullImageJson: string | null,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO integrations_talgil
         (tenant_id, controller_id, controller_name, controller_online, status,
          last_sync_at, last_error, consecutive_failures, last_full_image_json, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, datetime('now'), NULL, 0, ?, datetime('now'), datetime('now'))
       ON CONFLICT (tenant_id) DO UPDATE SET
         controller_id = excluded.controller_id,
         controller_name = excluded.controller_name,
         controller_online = excluded.controller_online,
         status = excluded.status,
         last_sync_at = datetime('now'),
         last_error = NULL,
         consecutive_failures = 0,
         last_full_image_json = excluded.last_full_image_json,
         updated_at = datetime('now')`,
    )
    .bind(
      tenantId,
      controllerId,
      controllerName,
      controllerOnline,
      status,
      fullImageJson,
    )
    .run();
}

export async function setIntegrationError(
  db: D1Database,
  tenantId: string,
  error: string,
): Promise<void> {
  await db
    .prepare(
      `UPDATE integrations_talgil
       SET last_error = ?, last_error_at = datetime('now'),
           consecutive_failures = consecutive_failures + 1,
           updated_at = datetime('now')
       WHERE tenant_id = ?`,
    )
    .bind(error, tenantId)
    .run();
}

export async function disconnectIntegration(
  db: D1Database,
  tenantId: string,
): Promise<void> {
  await db
    .prepare(
      `UPDATE integrations_talgil
       SET status = 'disconnected', updated_at = datetime('now')
       WHERE tenant_id = ?`,
    )
    .bind(tenantId)
    .run();
}

export async function getIntegration(
  db: D1Database,
  tenantId: string,
): Promise<IntegrationRow | null> {
  return db
    .prepare(`SELECT * FROM integrations_talgil WHERE tenant_id = ?`)
    .bind(tenantId)
    .first<IntegrationRow>();
}

// ── talgil_sensor_catalog ───────────────────────────────

export async function upsertSensorCatalog(
  db: D1Database,
  rows: SensorCatalogRow[],
): Promise<number> {
  let count = 0;
  for (const r of rows) {
    await db
      .prepare(
        `INSERT INTO talgil_sensor_catalog
           (tenant_id, controller_id, sensor_uid, sensor_name, sensor_type, units,
            data_source, last_seen_at_ms, last_seen_at, raw_json)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, controller_id, sensor_uid) DO UPDATE SET
           sensor_name = excluded.sensor_name,
           sensor_type = excluded.sensor_type,
           units = excluded.units,
           data_source = excluded.data_source,
           last_seen_at_ms = excluded.last_seen_at_ms,
           last_seen_at = excluded.last_seen_at,
           raw_json = excluded.raw_json`,
      )
      .bind(
        r.tenant_id,
        r.controller_id,
        r.sensor_uid,
        r.sensor_name,
        r.sensor_type,
        r.units,
        r.data_source,
        r.last_seen_at_ms,
        r.last_seen_at,
        r.raw_json,
      )
      .run();
    count++;
  }
  return count;
}

// ── talgil_sensor_log ───────────────────────────────────

export async function upsertSensorLog(
  db: D1Database,
  rows: SensorLogRow[],
): Promise<number> {
  let count = 0;
  for (const r of rows) {
    await db
      .prepare(
        `INSERT INTO talgil_sensor_log
           (tenant_id, controller_id, sensor_uid, observed_at_ms, observed_at, value_num, raw_json)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, controller_id, sensor_uid, observed_at_ms) DO NOTHING`,
      )
      .bind(
        r.tenant_id,
        r.controller_id,
        r.sensor_uid,
        r.observed_at_ms,
        r.observed_at,
        r.value_num,
        r.raw_json,
      )
      .run();
    count++;
  }
  return count;
}

// ── talgil_event_log ────────────────────────────────────

export async function upsertEventLog(
  db: D1Database,
  rows: EventLogRow[],
): Promise<number> {
  let count = 0;
  for (const r of rows) {
    await db
      .prepare(
        `INSERT INTO talgil_event_log
           (tenant_id, controller_id, event_key, event_at_ms, event_at, event_type, source_key, raw_json)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, controller_id, event_key) DO NOTHING`,
      )
      .bind(
        r.tenant_id,
        r.controller_id,
        r.event_key,
        r.event_at_ms,
        r.event_at,
        r.event_type,
        r.source_key,
        r.raw_json,
      )
      .run();
    count++;
  }
  return count;
}

// ── talgil_valve_wc ─────────────────────────────────────

export async function upsertValveWc(
  db: D1Database,
  rows: ValveWcRow[],
): Promise<number> {
  let count = 0;
  for (const r of rows) {
    await db
      .prepare(
        `INSERT INTO talgil_valve_wc
           (tenant_id, controller_id, valve_uid, bucket_start_ms, bucket_start_at,
            bucket_end_ms, bucket_end_at, rate, amount_value, raw_json)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (tenant_id, controller_id, valve_uid, bucket_start_ms) DO NOTHING`,
      )
      .bind(
        r.tenant_id,
        r.controller_id,
        r.valve_uid,
        r.bucket_start_ms,
        r.bucket_start_at,
        r.bucket_end_ms,
        r.bucket_end_at,
        r.rate,
        r.amount_value,
        r.raw_json,
      )
      .run();
    count++;
  }
  return count;
}
