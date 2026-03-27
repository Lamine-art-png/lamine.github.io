/**
 * Maps Talgil API responses to D1 row shapes.
 *
 * Aligned with rest.api.external v1.47:
 *   - Sensor catalog populated from full image (NOT separate /sensors call)
 *   - Event log fields: time, context, subcontext, message
 *   - Water consumption: response is object keyed by valve uid → array of {from, until, value, valuePerArea}
 *   - Sensor log: per-sensor entries with time + value
 *   - Handles both camelCase and PascalCase field names from API
 */

import type {
  TalgilFullImage,
  TalgilSensorEntry,
  TalgilSensorLogEntry,
  TalgilEventLogEntry,
  TalgilWcResponse,
} from "../connectors/talgil";

import {
  extractSensors,
  normalizeSensorUid,
  normalizeSensorName,
  normalizeSensorValue,
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
  min_limit: number | null;
  max_limit: number | null;
  low_threshold: number | null;
  high_threshold: number | null;
  reading_rate: number | null;
  units_descriptor: string | null;
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
  message: string | null;
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
  value_per_area: number | null;
  raw_json: string;
}

// ── Helpers ─────────────────────────────────────────────

function msToIso(ms: number): string {
  return new Date(ms).toISOString();
}

function getSensorType(s: TalgilSensorEntry): string | null {
  const t = s.type ?? s.Type;
  if (t === undefined || t === null) return null;
  return String(t);
}

function getSensorUnits(s: TalgilSensorEntry): string | null {
  return (s.units ?? s.Units) ?? null;
}

// ── Mapper: Full image → sensor catalog rows ────────────

export function mapSensorCatalogFromImage(
  tenantId: string,
  controllerId: number,
  image: TalgilFullImage,
): SensorCatalogRow[] {
  const sensors = extractSensors(image);
  const nowMs = Date.now();
  const nowIso = msToIso(nowMs);

  return sensors
    .filter((s) => normalizeSensorUid(s))
    .map((s) => ({
      tenant_id: tenantId,
      controller_id: controllerId,
      sensor_uid: String(normalizeSensorUid(s)),
      sensor_name: normalizeSensorName(s) ?? null,
      sensor_type: getSensorType(s),
      units: getSensorUnits(s),
      data_source: "full_image",
      last_seen_at_ms: nowMs,
      last_seen_at: nowIso,
      min_limit: s.minLimit ?? null,
      max_limit: s.maxLimit ?? null,
      low_threshold: s.lowThreshold ?? null,
      high_threshold: s.highThreshold ?? null,
      reading_rate: s.readingRate ?? null,
      units_descriptor: s.unitsDescriptor ?? null,
      raw_json: JSON.stringify(s),
    }));
}

// ── Mapper: Sensor log entries → D1 rows ────────────────

export function mapSensorLogRows(
  tenantId: string,
  controllerId: number,
  sensorUid: string,
  entries: TalgilSensorLogEntry[],
): SensorLogRow[] {
  return entries
    .filter((e) => typeof (e.time ?? e.Time) === "number")
    .map((e) => {
      const timeMs = (e.time ?? e.Time)!;
      const val = e.value ?? e.Value;
      return {
        tenant_id: tenantId,
        controller_id: controllerId,
        sensor_uid: sensorUid,
        observed_at_ms: timeMs,
        observed_at: msToIso(timeMs),
        value_num: typeof val === "number" ? val : null,
        raw_json: JSON.stringify(e),
      };
    });
}

// ── Mapper: Bulk sensor log entries → D1 rows ────────────
// Used with the bulk endpoint GET /targets/{id}/sensors/log (no sensor ID).
// Each entry includes its own uid field.

export function mapBulkSensorLogRows(
  tenantId: string,
  controllerId: number,
  entries: TalgilSensorLogEntry[],
): SensorLogRow[] {
  return entries
    .filter((e) => typeof (e.time ?? e.Time) === "number" && (e.uid ?? e.UID))
    .map((e) => {
      const timeMs = (e.time ?? e.Time)!;
      const val = e.value ?? e.Value;
      const uid = (e.uid ?? e.UID)!;
      return {
        tenant_id: tenantId,
        controller_id: controllerId,
        sensor_uid: uid,
        observed_at_ms: timeMs,
        observed_at: msToIso(timeMs),
        value_num: typeof val === "number" ? val : null,
        raw_json: JSON.stringify(e),
      };
    });
}

// ── Mapper: Full image sensors → snapshot sensor log ────
// Captures current sensor values from the full image as point-in-time readings.

export function mapSensorSnapshotFromImage(
  tenantId: string,
  controllerId: number,
  image: TalgilFullImage,
): SensorLogRow[] {
  const sensors = extractSensors(image);
  const nowMs = Date.now();
  const nowIso = msToIso(nowMs);

  return sensors
    .filter((s) => normalizeSensorUid(s) && typeof normalizeSensorValue(s) === "number")
    .map((s) => ({
      tenant_id: tenantId,
      controller_id: controllerId,
      sensor_uid: String(normalizeSensorUid(s)),
      observed_at_ms: nowMs,
      observed_at: nowIso,
      value_num: normalizeSensorValue(s)!,
      raw_json: JSON.stringify(s),
    }));
}

// ── Mapper: Event log entries → D1 rows ─────────────────
// API v1.47 says eventlog returns: time, context, subcontext, message

export function mapEventLogRows(
  tenantId: string,
  controllerId: number,
  entries: TalgilEventLogEntry[],
): EventLogRow[] {
  return entries
    .filter((e) => typeof (e.time ?? e.Time) === "number")
    .map((e) => {
      const timeMs = (e.time ?? e.Time)!;
      // Build event_type from context/subcontext for categorization
      const context = e.context ?? e.Type ?? "unknown";
      const subcontext = e.subcontext ?? e.Source ?? "";
      const eventType = subcontext ? `${context}/${subcontext}` : context;
      const eventKey = `${controllerId}:${timeMs}:${eventType}`;
      return {
        tenant_id: tenantId,
        controller_id: controllerId,
        event_key: eventKey,
        event_at_ms: timeMs,
        event_at: msToIso(timeMs),
        event_type: eventType,
        source_key: subcontext || null,
        message: e.message ?? null,
        raw_json: JSON.stringify(e),
      };
    });
}

// ── Mapper: Water consumption response → D1 rows ────────
// API v1.47: response is object keyed by valve uid, each value is array of
// { from, until, value, valuePerArea }

export function mapValveWcRows(
  tenantId: string,
  controllerId: number,
  wcResponse: TalgilWcResponse,
  rate: string,
): ValveWcRow[] {
  const rows: ValveWcRow[] = [];

  for (const [valveUid, buckets] of Object.entries(wcResponse)) {
    if (!Array.isArray(buckets)) continue;

    for (const bucket of buckets) {
      const fromMs = bucket.from;
      const untilMs = bucket.until;
      if (typeof fromMs !== "number" || typeof untilMs !== "number") continue;

      rows.push({
        tenant_id: tenantId,
        controller_id: controllerId,
        valve_uid: valveUid,
        bucket_start_ms: fromMs,
        bucket_start_at: msToIso(fromMs),
        bucket_end_ms: untilMs,
        bucket_end_at: msToIso(untilMs),
        rate,
        amount_value: typeof bucket.value === "number" ? bucket.value : null,
        value_per_area: typeof bucket.valuePerArea === "number" ? bucket.valuePerArea : null,
        raw_json: JSON.stringify(bucket),
      });
    }
  }

  return rows;
}
