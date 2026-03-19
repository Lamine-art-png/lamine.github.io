/**
 * Maps Talgil API responses to D1 row shapes.
 *
 * Design decisions:
 *   - Sensor catalog is populated from the full image response, NOT from
 *     a separate /sensors call. Kosta explicitly said separate sensor
 *     requests make no sense because sensors are already in the full image.
 *   - Sensor log rows come from /sensors/log historical batch.
 *   - Event log rows come from /eventlog historical batch.
 *   - Water consumption rows come from /wc/valves historical batch.
 */

import type {
  TalgilFullImage,
  TalgilSensorEntry,
  TalgilSensorLogEntry,
  TalgilEventLogEntry,
  TalgilWcEntry,
} from "../connectors/talgil";

// ── Row types for D1 ────────────────────────────────────

export interface SensorCatalogRow {
  tenant_id: string;
  controller_id: number;
  sensor_uid: string;
  sensor_name: string | null;
  sensor_type: string | null;
  units: string | null;
  data_source: string;
  last_seen_at_ms: number;
  last_seen_at: string;
  raw_json: string;
}

export interface SensorLogRow {
  tenant_id: string;
  controller_id: number;
  sensor_uid: string;
  observed_at_ms: number;
  observed_at: string;
  value_num: number | null;
  raw_json: string;
}

export interface EventLogRow {
  tenant_id: string;
  controller_id: number;
  event_key: string;
  event_at_ms: number;
  event_at: string;
  event_type: string | null;
  source_key: string | null;
  raw_json: string;
}

export interface ValveWcRow {
  tenant_id: string;
  controller_id: number;
  valve_uid: string;
  bucket_start_ms: number;
  bucket_start_at: string;
  bucket_end_ms: number;
  bucket_end_at: string;
  rate: string;
  amount_value: number | null;
  raw_json: string;
}

// ── Helpers ─────────────────────────────────────────────

function msToIso(ms: number): string {
  return new Date(ms).toISOString();
}

// ── Mapper: Full image → sensor catalog rows ────────────

export function mapSensorCatalogFromImage(
  tenantId: string,
  controllerId: number,
  image: TalgilFullImage,
): SensorCatalogRow[] {
  const sensors: TalgilSensorEntry[] = image.Sensors ?? [];
  const nowMs = Date.now();
  const nowIso = msToIso(nowMs);

  return sensors
    .filter((s) => s.UID)
    .map((s) => ({
      tenant_id: tenantId,
      controller_id: controllerId,
      sensor_uid: String(s.UID),
      sensor_name: s.Name ?? null,
      sensor_type: s.Type ?? null,
      units: s.Units ?? null,
      data_source: "full_image",
      last_seen_at_ms: nowMs,
      last_seen_at: nowIso,
      raw_json: JSON.stringify(s),
    }));
}

// ── Mapper: Sensor log entries → D1 rows ────────────────

export function mapSensorLogRows(
  tenantId: string,
  controllerId: number,
  entries: TalgilSensorLogEntry[],
): SensorLogRow[] {
  return entries
    .filter((e) => e.UID && typeof e.Time === "number")
    .map((e) => ({
      tenant_id: tenantId,
      controller_id: controllerId,
      sensor_uid: String(e.UID),
      observed_at_ms: e.Time!,
      observed_at: msToIso(e.Time!),
      value_num: typeof e.Value === "number" ? e.Value : null,
      raw_json: JSON.stringify(e),
    }));
}

// ── Mapper: Full image sensors → snapshot sensor log ────
// Captures current sensor values from the full image as point-in-time readings.

export function mapSensorSnapshotFromImage(
  tenantId: string,
  controllerId: number,
  image: TalgilFullImage,
): SensorLogRow[] {
  const sensors: TalgilSensorEntry[] = image.Sensors ?? [];
  const nowMs = Date.now();
  const nowIso = msToIso(nowMs);

  return sensors
    .filter((s) => s.UID && typeof s.Value === "number")
    .map((s) => ({
      tenant_id: tenantId,
      controller_id: controllerId,
      sensor_uid: String(s.UID),
      observed_at_ms: nowMs,
      observed_at: nowIso,
      value_num: s.Value!,
      raw_json: JSON.stringify(s),
    }));
}

// ── Mapper: Event log entries → D1 rows ─────────────────

export function mapEventLogRows(
  tenantId: string,
  controllerId: number,
  entries: TalgilEventLogEntry[],
): EventLogRow[] {
  return entries
    .filter((e) => typeof e.Time === "number")
    .map((e) => {
      const timeMs = e.Time!;
      const eventKey = `${controllerId}:${timeMs}:${e.Type ?? "unknown"}`;
      return {
        tenant_id: tenantId,
        controller_id: controllerId,
        event_key: eventKey,
        event_at_ms: timeMs,
        event_at: msToIso(timeMs),
        event_type: e.Type ?? null,
        source_key: e.Source ?? null,
        raw_json: JSON.stringify(e),
      };
    });
}

// ── Mapper: Water consumption entries → D1 rows ─────────

export function mapValveWcRows(
  tenantId: string,
  controllerId: number,
  entries: TalgilWcEntry[],
  rate: string,
): ValveWcRow[] {
  return entries
    .filter(
      (e) =>
        e.ValveUID &&
        typeof e.Start === "number" &&
        typeof e.End === "number",
    )
    .map((e) => ({
      tenant_id: tenantId,
      controller_id: controllerId,
      valve_uid: String(e.ValveUID),
      bucket_start_ms: e.Start!,
      bucket_start_at: msToIso(e.Start!),
      bucket_end_ms: e.End!,
      bucket_end_at: msToIso(e.End!),
      rate,
      amount_value: typeof e.Amount === "number" ? e.Amount : null,
      raw_json: JSON.stringify(e),
    }));
}
