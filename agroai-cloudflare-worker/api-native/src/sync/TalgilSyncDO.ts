/**
 * TalgilSyncDO — Durable Object that orchestrates Talgil data sync.
 *
 * ╔══════════════════════════════════════════════════════════════════════╗
 * ║  ARCHITECTURE DECISIONS (driven by Kosta's feedback + API v1.47)   ║
 * ╠══════════════════════════════════════════════════════════════════════╣
 * ║  1. /mytargets is called ONCE during connect, never on sync.       ║
 * ║  2. Operational sync uses FILTERED full image.                     ║
 * ║  3. NO separate /sensors call — sensors are in full image.         ║
 * ║  4. Sensor catalog is populated FROM the full image.               ║
 * ║  5. Historical sensor log uses per-sensor /sensors/{id}/log.       ║
 * ║  6. Historical batch stays within simulator date range (dev).      ║
 * ║  7. Event log + water consumption are DIAGNOSTIC until proven.     ║
 * ║  8. Operational sync runs every 20 minutes (not every minute).     ║
 * ║  9. Rate-aware chunking for DB queries (max ranges enforced).      ║
 * ║ 10. Filtered image reduces traffic per behavior guidelines.        ║
 * ╚══════════════════════════════════════════════════════════════════════╝
 *
 * Sync modes:
 *   "connect"          → discover via /mytargets, fetch first full image
 *   "sync"             → operational: filtered image, update catalog + snapshot
 *   "backfill"         → historical: per-sensor log in day chunks
 *   "test_eventlog"    → diagnostic: single event log request
 *   "test_wc"          → diagnostic: single water consumption request
 */

import {
  talgilListTargets,
  talgilGetFullImage,
  talgilGetFilteredImage,
  talgilGetAllSensorLogs,
  talgilGetEventLog,
  talgilGetWaterConsumption,
  SIMULATOR_FROM_MS,
  SIMULATOR_UNTIL_MS,
  SYNC_FILTER,
  MIN_INTERVAL,
  diagnoseError,
  extractSensors,
  extractControllerName,
  extractOnlineStatus,
  normalizeSensorUid,
} from "../connectors/talgil";

import type {
  TalgilWcResponse,
} from "../connectors/talgil";

import {
  mapSensorCatalogFromImage,
  mapSensorSnapshotFromImage,
  mapBulkSensorLogRows,
  mapEventLogRows,
  mapValveWcRows,
} from "../mappers/talgil_map";

import {
  ensureTenant,
  upsertIntegration,
  setIntegrationError,
  getIntegration,
  upsertSensorCatalog,
  upsertSensorLog,
  upsertEventLog,
  upsertValveWc,
} from "../lib/db";

import { writeAudit } from "../lib/audit";

// ── Helpers ─────────────────────────────────────────────

/** Parse a date query param: accepts epoch-ms number or ISO/YYYY-MM-DD string */
function parseDateParam(raw: string | null, fallback: number): number {
  if (raw === null) return fallback;
  // If it looks like a pure number, treat as epoch-ms
  if (/^\d{10,}$/.test(raw)) return parseInt(raw, 10);
  // Otherwise parse as date string
  const ms = new Date(raw).getTime();
  return Number.isNaN(ms) ? fallback : ms;
}

// ── Env type ────────────────────────────────────────────

export interface Env {
  DB: D1Database;
  TALGIL_SYNC: DurableObjectNamespace;
  TALGIL_API_KEY: string;
  TALGIL_BASE_URL: string;
  ADMIN_TOKEN: string;
  ENVIRONMENT?: string;
}

// ── Constants ───────────────────────────────────────────

const ONE_DAY_MS = 86_400_000;
const BACKFILL_CHUNK_MS = ONE_DAY_MS; // 1-day chunks for sensor log backfill

// ── Durable Object ──────────────────────────────────────

export class TalgilSyncDO implements DurableObject {
  private state: DurableObjectState;
  private env: Env;

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const tenantId = url.searchParams.get("tenantId");
    const mode = url.searchParams.get("mode") ?? "sync";

    if (!tenantId) {
      return Response.json({ error: "tenantId required" }, { status: 400 });
    }

    try {
      switch (mode) {
        case "connect":
          return await this.handleConnect(tenantId);
        case "sync":
          return await this.handleSync(tenantId);
        case "backfill":
          return await this.handleBackfill(tenantId, url);
        case "test_eventlog":
          return await this.handleTestEventLog(tenantId);
        case "test_wc":
          return await this.handleTestWaterConsumption(tenantId);
        case "loadtest":
          return await this.handleLoadTestStart(tenantId, url);
        case "loadtest_stop":
          return await this.handleLoadTestStop(tenantId);
        default:
          return Response.json(
            { error: `Unknown mode: ${mode}` },
            { status: 400 },
          );
      }
    } catch (err) {
      const msg = (err as Error).message ?? String(err);
      try {
        await setIntegrationError(this.env.DB, tenantId, msg);
      } catch { /* best-effort */ }
      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: `sync.${mode}`,
        detail: "Unhandled exception in sync DO",
        outcome: "failure",
        error_message: msg,
      });
      return Response.json({ error: msg, code_version: "v2.4.0" }, { status: 500 });
    }
  }

  // ────────────────────────────────────────────────────────
  // MODE: connect
  // Called once. Discovers controller, fetches FULL (unfiltered) image
  // to get complete sensor metadata, populates integration + catalog.
  // IDEMPOTENT: if already connected, skips /mytargets and reuses
  // the stored controller ID to avoid unnecessary API calls.
  // ────────────────────────────────────────────────────────
  private async handleConnect(tenantId: string): Promise<Response> {
    // Ensure tenant row exists (FK target for integrations_talgil)
    try {
      await ensureTenant(this.env.DB, tenantId);
    } catch (tenantErr) {
      const msg = (tenantErr as Error).message ?? String(tenantErr);
      return Response.json({
        error: `ensureTenant failed: ${msg}`,
        code_version: "v2.4.0",
      }, { status: 500 });
    }

    const baseUrl = this.env.TALGIL_BASE_URL;
    const apiKey = this.env.TALGIL_API_KEY;

    let controllerId: number;
    let controllerName: string;

    // Check if already connected — skip /mytargets if so
    const existing = await getIntegration(this.env.DB, tenantId);
    if (existing && existing.controller_id > 0) {
      // Already discovered — reuse stored controller ID
      controllerId = existing.controller_id;
      controllerName = existing.controller_name;

      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: "connect.skip_mytargets",
        detail: `Already connected to controller ${controllerId} — skipping /mytargets`,
        outcome: "skipped",
      });
    } else {
      // Step 1: Discover controller via /mytargets (first time only)
      const targetsResult = await talgilListTargets(baseUrl, apiKey);

      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: "connect.list_targets",
        detail: "GET /mytargets to discover controller ID",
        outcome: targetsResult.ok ? "success" : "failure",
        url: targetsResult.url,
        http_status: targetsResult.status,
        row_count: targetsResult.data?.length ?? 0,
        error_message: targetsResult.error,
      });

      if (!targetsResult.ok || !targetsResult.data?.length) {
        const errMsg = targetsResult.error ?? "No targets returned from /mytargets";
        await setIntegrationError(this.env.DB, tenantId, errMsg);
        return Response.json({
          ok: false,
          error: errMsg,
          diagnosis: diagnoseError(targetsResult.status),
          url: targetsResult.url,
          http_status: targetsResult.status,
        });
      }

      // Use the first target (simulator controller 6115 in dev)
      const target = targetsResult.data[0];
      controllerId = Math.floor(Number(target.serial ?? target.ID ?? target.id ?? 0));
      controllerName = extractControllerName(target);

      // Log raw target shape for debugging field name mismatches
      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: "connect.target_debug",
        detail: `Raw target keys: ${Object.keys(target).join(", ")}; controllerId=${controllerId}`,
        outcome: controllerId ? "success" : "failure",
      });

      // Rate limiting between API calls is enforced automatically by talgilFetch
    }

    // Step 2: Fetch FULL image (unfiltered) to get complete sensor metadata
    // Connect uses unfiltered because we need all metadata fields for catalog
    const imageResult = await talgilGetFullImage(baseUrl, apiKey, controllerId);

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "connect.full_image",
      detail: `GET /targets/${controllerId}/ for initial full image`,
      outcome: imageResult.ok ? "success" : "failure",
      url: imageResult.url,
      http_status: imageResult.status,
      error_message: imageResult.error,
    });

    if (!imageResult.ok || !imageResult.data) {
      const errMsg = imageResult.error ?? "Failed to fetch full image";
      await setIntegrationError(this.env.DB, tenantId, errMsg);
      return Response.json({
        ok: false,
        error: errMsg,
        diagnosis: diagnoseError(imageResult.status),
        url: imageResult.url,
        http_status: imageResult.status,
      });
    }

    const image = imageResult.data;

    // Detect Talgil logical errors returned as HTTP 200 with { rc, message }
    // rc:1101 = "Controller is not currently connected to server"
    const rc = (image as Record<string, unknown>).rc as number | undefined;
    const rcMessage = (image as Record<string, unknown>).message as string | undefined;
    const controllerOffline = rc !== undefined && rc !== 0;

    const controllerOnline = controllerOffline ? 0 : extractOnlineStatus(image);

    // Step 3: Populate integration row — mark connected even if controller offline
    // (we verified the API key + controller exist; sensors will populate on next sync when online)
    await upsertIntegration(
      this.env.DB,
      tenantId,
      controllerId,
      controllerName,
      controllerOnline,
      "connected",
      JSON.stringify(image).slice(0, 50000), // cap stored JSON
    );

    if (controllerOffline) {
      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: "connect.controller_offline",
        detail: `Controller ${controllerId} offline (rc=${rc}): ${rcMessage}. Sensors will be populated on next sync when controller comes online.`,
        outcome: "skipped",
      });

      return Response.json({
        ok: true,
        controller_id: controllerId,
        controller_name: controllerName,
        controller_online: 0,
        controller_offline_reason: rcMessage,
        controller_offline_rc: rc,
        sensor_catalog_count: 0,
        sensor_snapshot_count: 0,
        sensors_in_image: 0,
        sensor_uids: [],
        state: null,
        note: "Controller is offline. Integration is connected — sensors will be populated automatically on the next sync when the controller comes online.",
      });
    }

    // Step 4: Populate sensor catalog FROM FULL IMAGE (not separate /sensors)
    const catalogRows = mapSensorCatalogFromImage(tenantId, controllerId, image);
    const catalogCount = await upsertSensorCatalog(this.env.DB, catalogRows);

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "connect.sensor_catalog",
      detail: `Populated sensor catalog from full image (${catalogCount} sensors)`,
      outcome: catalogCount > 0 ? "success" : "skipped",
      row_count: catalogCount,
    });

    // Step 5: Capture sensor snapshot from full image
    const snapshotRows = mapSensorSnapshotFromImage(tenantId, controllerId, image);
    const snapshotCount = await upsertSensorLog(this.env.DB, snapshotRows);

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "connect.sensor_snapshot",
      detail: `Stored ${snapshotCount} sensor readings from full image snapshot`,
      outcome: snapshotCount > 0 ? "success" : "skipped",
      row_count: snapshotCount,
    });

    // List discovered sensor UIDs for debugging
    const sensorUids = catalogRows.map((r) => r.sensor_uid);

    return Response.json({
      ok: true,
      controller_id: controllerId,
      controller_name: controllerName,
      controller_online: controllerOnline,
      sensor_catalog_count: catalogCount,
      sensor_snapshot_count: snapshotCount,
      sensors_in_image: extractSensors(image).length,
      sensor_uids: sensorUids,
      state: image.state ?? null,
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: sync (operational)
  // Fetches FILTERED image. No /mytargets. No /sensors.
  // Updates catalog + takes sensor snapshot.
  // Designed to run every 20 minutes.
  // ────────────────────────────────────────────────────────
  private async handleSync(tenantId: string): Promise<Response> {
    const baseUrl = this.env.TALGIL_BASE_URL;
    const apiKey = this.env.TALGIL_API_KEY;

    // Look up existing integration
    const integration = await getIntegration(this.env.DB, tenantId);
    if (!integration || integration.status !== "connected") {
      return Response.json(
        { error: "Not connected. Call connect first.", status: integration?.status },
        { status: 400 },
      );
    }

    const controllerId = integration.controller_id;

    // Use filtered image to reduce traffic
    // Filter: sensors container + key fields (uid, name, type, units, value, updateTime, state, online)
    const imageResult = await talgilGetFilteredImage(
      baseUrl,
      apiKey,
      controllerId,
      SYNC_FILTER,
    );

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "sync.filtered_image",
      detail: `GET /targets/${controllerId}/?filter=${SYNC_FILTER}`,
      outcome: imageResult.ok ? "success" : "failure",
      url: imageResult.url,
      http_status: imageResult.status,
      error_message: imageResult.error,
    });

    if (!imageResult.ok || !imageResult.data) {
      const errMsg = imageResult.error ?? "Filtered image fetch failed";
      await setIntegrationError(this.env.DB, tenantId, errMsg);
      return Response.json({
        ok: false,
        error: errMsg,
        diagnosis: diagnoseError(imageResult.status),
        url: imageResult.url,
        http_status: imageResult.status,
      });
    }

    const image = imageResult.data;

    // Detect Talgil logical errors (e.g. rc:1101 = controller offline)
    const rc = (image as Record<string, unknown>).rc as number | undefined;
    const rcMessage = (image as Record<string, unknown>).message as string | undefined;
    const controllerOffline = rc !== undefined && rc !== 0;

    // Update integration row (status, online, timestamp)
    await upsertIntegration(
      this.env.DB,
      tenantId,
      controllerId,
      controllerOffline ? integration.controller_name : (extractControllerName(image) || integration.controller_name),
      controllerOffline ? 0 : extractOnlineStatus(image),
      "connected",
      JSON.stringify(image).slice(0, 50000),
    );

    if (controllerOffline) {
      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: "sync.controller_offline",
        detail: `Controller ${controllerId} offline (rc=${rc}): ${rcMessage}`,
        outcome: "skipped",
      });

      return Response.json({
        ok: true,
        controller_id: controllerId,
        controller_online: 0,
        controller_offline_reason: rcMessage,
        sensor_catalog_count: 0,
        sensor_snapshot_count: 0,
        note: "Controller offline — sync skipped. Will retry on next cycle.",
      });
    }

    // Update sensor catalog from filtered image
    const catalogRows = mapSensorCatalogFromImage(tenantId, controllerId, image);
    const catalogCount = await upsertSensorCatalog(this.env.DB, catalogRows);

    // Capture sensor snapshot from filtered image
    const snapshotRows = mapSensorSnapshotFromImage(tenantId, controllerId, image);
    const snapshotCount = await upsertSensorLog(this.env.DB, snapshotRows);

    return Response.json({
      ok: true,
      mode: "sync",
      controller_id: controllerId,
      controller_online: extractOnlineStatus(image),
      catalog_upserted: catalogCount,
      snapshot_stored: snapshotCount,
      sensors_in_image: extractSensors(image).length,
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: backfill (historical sensor log)
  // Uses BULK endpoint: GET /targets/{id}/sensors/log (no sensor ID)
  // to fetch ALL sensors' historical data in a SINGLE request.
  // Per Kosta: "Remove the number(ID) of the sensor and you will
  // get all sensors at once."
  // ────────────────────────────────────────────────────────
  private async handleBackfill(
    tenantId: string,
    url: URL,
  ): Promise<Response> {
    const baseUrl = this.env.TALGIL_BASE_URL;
    const apiKey = this.env.TALGIL_API_KEY;

    const integration = await getIntegration(this.env.DB, tenantId);
    if (!integration || integration.status !== "connected") {
      return Response.json(
        { error: "Not connected. Call connect first." },
        { status: 400 },
      );
    }

    const controllerId = integration.controller_id;

    // Default: last 24 hours. Use real time ranges per Kosta's guidance.
    // Accept either epoch-ms numbers or ISO/YYYY-MM-DD date strings.
    const nowMs = Date.now();
    const defaultFrom = nowMs - 86_400_000; // 24 hours ago
    const fromMs = parseDateParam(url.searchParams.get("from"), defaultFrom);
    const untilMs = parseDateParam(url.searchParams.get("until"), nowMs);

    if (fromMs >= untilMs) {
      return Response.json({
        ok: false,
        error: "Invalid date range: 'from' must be before 'until'",
        requested_from: new Date(fromMs).toISOString(),
        requested_until: new Date(untilMs).toISOString(),
      });
    }

    const errors: string[] = [];

    // Single bulk request — gets ALL sensors at once
    const result = await talgilGetAllSensorLogs(
      baseUrl,
      apiKey,
      controllerId,
      fromMs,
      untilMs,
    );

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "backfill.bulk_sensor_log",
      detail: `GET /targets/${controllerId}/sensors/log (bulk, all sensors)`,
      outcome: result.ok ? "success" : "failure",
      url: result.url,
      http_status: result.status,
      row_count: Array.isArray(result.data) ? result.data.length : 0,
      error_message: result.error,
    });

    let totalRows = 0;
    let sensorCount = 0;

    if (!result.ok) {
      const errDetail = `HTTP ${result.status}: ${result.error}`;
      errors.push(errDetail);
    } else if (result.data != null) {
      if (!Array.isArray(result.data)) {
        const raw = JSON.stringify(result.data).slice(0, 300);
        errors.push(`Unexpected response shape: ${raw}`);
      } else if (result.data.length > 0) {
        const logRows = mapBulkSensorLogRows(tenantId, controllerId, result.data);
        totalRows = await upsertSensorLog(this.env.DB, logRows);
        // Count unique sensors in response
        const uniqueUids = new Set(logRows.map((r) => r.sensor_uid));
        sensorCount = uniqueUids.size;
      }
    }

    // Debug: include sample of raw response to understand the shape
    const sample = Array.isArray(result.data) && result.data.length > 0
      ? result.data.slice(0, 2).map((e) => JSON.stringify(e).slice(0, 300))
      : [];

    return Response.json({
      ok: errors.length === 0,
      mode: "backfill",
      controller_id: controllerId,
      date_range: {
        from: new Date(fromMs).toISOString(),
        until: new Date(untilMs).toISOString(),
      },
      entries_received: Array.isArray(result.data) ? result.data.length : 0,
      sensors_in_response: sensorCount,
      total_rows_stored: totalRows,
      errors,
      sample,
      url: result.url,
      http_status: result.status,
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: test_eventlog (diagnostic)
  // Single request to /eventlog to test permissions.
  // API v1.47: returns array of {time, context, subcontext, message}
  // ────────────────────────────────────────────────────────
  private async handleTestEventLog(tenantId: string): Promise<Response> {
    const baseUrl = this.env.TALGIL_BASE_URL;
    const apiKey = this.env.TALGIL_API_KEY;

    const integration = await getIntegration(this.env.DB, tenantId);
    if (!integration || integration.status !== "connected") {
      return Response.json({ error: "Not connected" }, { status: 400 });
    }

    const controllerId = integration.controller_id;
    // Use a 1-day window in the middle of the simulator range
    const midpoint = Math.floor((SIMULATOR_FROM_MS + SIMULATOR_UNTIL_MS) / 2);
    const fromMs = midpoint;
    const untilMs = midpoint + ONE_DAY_MS;

    const result = await talgilGetEventLog(
      baseUrl,
      apiKey,
      controllerId,
      fromMs,
      untilMs,
    );

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "test.eventlog",
      detail: `Diagnostic: GET /targets/${controllerId}/eventlog?from=${fromMs}&until=${untilMs}`,
      outcome: result.ok ? "success" : "failure",
      url: result.url,
      http_status: result.status,
      row_count: Array.isArray(result.data) ? result.data.length : 0,
      error_message: result.error,
    });

    if (result.ok && Array.isArray(result.data) && result.data.length > 0) {
      const eventRows = mapEventLogRows(tenantId, controllerId, result.data);
      const inserted = await upsertEventLog(this.env.DB, eventRows);
      return Response.json({
        ok: true,
        endpoint: "eventlog",
        url: result.url,
        http_status: result.status,
        entries_received: result.data.length,
        rows_stored: inserted,
        sample: result.data.slice(0, 3),
        date_range: {
          from: new Date(fromMs).toISOString(),
          until: new Date(untilMs).toISOString(),
        },
      });
    }

    return Response.json({
      ok: false,
      endpoint: "eventlog",
      url: result.url,
      http_status: result.status,
      error: result.error,
      entries_received: Array.isArray(result.data) ? result.data.length : 0,
      diagnosis: diagnoseError(result.status),
      date_range: {
        from: new Date(fromMs).toISOString(),
        until: new Date(untilMs).toISOString(),
      },
      note: "If 403, permission or access scope may be limiting this endpoint. Confirm with Kosta.",
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: test_wc (diagnostic)
  // Single request to /wc/valves to test permissions.
  // API v1.47: returns object keyed by valve uid → array of {from, until, value, valuePerArea}
  // ────────────────────────────────────────────────────────
  private async handleTestWaterConsumption(
    tenantId: string,
  ): Promise<Response> {
    const baseUrl = this.env.TALGIL_BASE_URL;
    const apiKey = this.env.TALGIL_API_KEY;

    const integration = await getIntegration(this.env.DB, tenantId);
    if (!integration || integration.status !== "connected") {
      return Response.json({ error: "Not connected" }, { status: 400 });
    }

    const controllerId = integration.controller_id;
    const midpoint = Math.floor((SIMULATOR_FROM_MS + SIMULATOR_UNTIL_MS) / 2);
    const fromMs = midpoint;
    const untilMs = midpoint + ONE_DAY_MS;

    const result = await talgilGetWaterConsumption(
      baseUrl,
      apiKey,
      controllerId,
      fromMs,
      untilMs,
      "daily",
    );

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "test.wc",
      detail: `Diagnostic: GET /targets/${controllerId}/wc/valves?from=${fromMs}&until=${untilMs}&rate=daily`,
      outcome: result.ok ? "success" : "failure",
      url: result.url,
      http_status: result.status,
      error_message: result.error,
    });

    if (result.ok && result.data && typeof result.data === "object") {
      const wcResponse = result.data as TalgilWcResponse;
      const valveCount = Object.keys(wcResponse).length;

      if (valveCount > 0) {
        const wcRows = mapValveWcRows(tenantId, controllerId, wcResponse, "daily");
        const inserted = await upsertValveWc(this.env.DB, wcRows);
        return Response.json({
          ok: true,
          endpoint: "wc/valves",
          url: result.url,
          http_status: result.status,
          valves_received: valveCount,
          buckets_stored: inserted,
          sample_valves: Object.keys(wcResponse).slice(0, 5),
          date_range: {
            from: new Date(fromMs).toISOString(),
            until: new Date(untilMs).toISOString(),
          },
        });
      }
    }

    return Response.json({
      ok: false,
      endpoint: "wc/valves",
      url: result.url,
      http_status: result.status,
      error: result.error,
      diagnosis: diagnoseError(result.status),
      date_range: {
        from: new Date(fromMs).toISOString(),
        until: new Date(untilMs).toISOString(),
      },
      note: "If 403, permission or access scope may be limiting this endpoint. Confirm with Kosta.",
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: loadtest (48-hour load test with multiple controllers)
  // Runs a scheduled cycle every 20 minutes:
  //   1. Filtered image (sync) for each controller — 2s gap
  //   2. Bulk sensor log for each controller — 16s gap
  //   3. Event log for each controller — 16s gap
  //   4. Water consumption for each controller — 61s gap
  // Uses Durable Object alarms for scheduling.
  // ────────────────────────────────────────────────────────

  private async handleLoadTestStart(
    tenantId: string,
    url: URL,
  ): Promise<Response> {
    const controllers = (url.searchParams.get("controllers") ?? "6115,61151,61152,61153")
      .split(",")
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !isNaN(n));
    const durationHours = parseInt(url.searchParams.get("hours") ?? "48", 10);
    const cycleMinutes = parseInt(url.searchParams.get("cycle") ?? "20", 10);

    const startMs = Date.now();
    const endMs = startMs + durationHours * 3_600_000;

    // Store load test config in DO storage
    await this.state.storage.put("loadtest", {
      tenantId,
      controllers,
      startMs,
      endMs,
      cycleMinutes,
      cyclesCompleted: 0,
    });

    // Schedule first alarm immediately
    await this.state.storage.setAlarm(Date.now() + 1000);

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "loadtest.start",
      detail: `Started ${durationHours}h load test: controllers=${controllers.join(",")}, cycle=${cycleMinutes}min`,
      outcome: "success",
    });

    return Response.json({
      ok: true,
      mode: "loadtest",
      controllers,
      duration_hours: durationHours,
      cycle_minutes: cycleMinutes,
      start: new Date(startMs).toISOString(),
      end: new Date(endMs).toISOString(),
      message: `Load test started. ${controllers.length} controllers, ${cycleMinutes}-min cycles for ${durationHours} hours.`,
    });
  }

  private async handleLoadTestStop(tenantId: string): Promise<Response> {
    await this.state.storage.delete("loadtest");
    await this.state.storage.deleteAlarm();

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "loadtest.stop",
      detail: "Load test stopped manually",
      outcome: "success",
    });

    return Response.json({ ok: true, message: "Load test stopped." });
  }

  // Durable Object alarm handler — runs each load test cycle
  // Schedule per Kosta's approval:
  //   - Sync (filtered image): every 20 min (every cycle)
  //   - Sensor log + Event log: every 6 hours (every 18th cycle at 20-min intervals)
  //   - Water consumption: every 24 hours (every 72nd cycle at 20-min intervals)
  async alarm(): Promise<void> {
    const config = await this.state.storage.get<{
      tenantId: string;
      controllers: number[];
      startMs: number;
      endMs: number;
      cycleMinutes: number;
      cyclesCompleted: number;
    }>("loadtest");

    if (!config) return; // No active load test

    const now = Date.now();
    if (now >= config.endMs) {
      await writeAudit(this.env.DB, {
        tenant_id: config.tenantId,
        action: "loadtest.complete",
        detail: `Load test completed after ${config.cyclesCompleted} cycles`,
        outcome: "success",
      });
      await this.state.storage.delete("loadtest");
      return;
    }

    const baseUrl = this.env.TALGIL_BASE_URL;
    const apiKey = this.env.TALGIL_API_KEY;
    const cycleStart = Date.now();
    const cycleNum = config.cyclesCompleted + 1;
    let requestCount = 0;
    let errorCount = 0;

    // Determine which phases to run this cycle
    const cyclesPerSixHours = Math.round((6 * 60) / config.cycleMinutes); // 18 at 20-min cycles
    const cyclesPerDay = Math.round((24 * 60) / config.cycleMinutes);     // 72 at 20-min cycles
    const runDbLogs = cycleNum === 1 || cycleNum % cyclesPerSixHours === 0;
    const runWc = cycleNum === 1 || cycleNum % cyclesPerDay === 0;

    // Time window for DB queries: last 6 hours for logs, last 24 hours for wc
    const untilMs = Date.now();
    const logFromMs = untilMs - 6 * 3_600_000;
    const wcFromMs = untilMs - 24 * 3_600_000;

    // ── Phase 1: Filtered image sync — EVERY cycle (every 20 min) ──
    for (const cid of config.controllers) {
      const result = await talgilGetFilteredImage(baseUrl, apiKey, cid, SYNC_FILTER);
      requestCount++;
      if (!result.ok) errorCount++;

      await writeAudit(this.env.DB, {
        tenant_id: config.tenantId,
        action: "loadtest.sync",
        detail: `Cycle ${cycleNum}: GET /targets/${cid}/?filter=...`,
        outcome: result.ok ? "success" : "failure",
        url: result.url,
        http_status: result.status,
        error_message: result.error,
      });
    }

    // ── Phase 2: Sensor log — every 6 hours ──
    if (runDbLogs) {
      for (const cid of config.controllers) {
        const result = await talgilGetAllSensorLogs(baseUrl, apiKey, cid, logFromMs, untilMs);
        requestCount++;
        if (!result.ok) errorCount++;

        await writeAudit(this.env.DB, {
          tenant_id: config.tenantId,
          action: "loadtest.sensor_log",
          detail: `Cycle ${cycleNum}: GET /targets/${cid}/sensors/log (6h window)`,
          outcome: result.ok ? "success" : "failure",
          url: result.url,
          http_status: result.status,
          row_count: Array.isArray(result.data) ? result.data.length : 0,
          error_message: result.error,
        });
      }

      // ── Phase 3: Event log — every 6 hours ──
      for (const cid of config.controllers) {
        const result = await talgilGetEventLog(baseUrl, apiKey, cid, logFromMs, untilMs);
        requestCount++;
        if (!result.ok) errorCount++;

        await writeAudit(this.env.DB, {
          tenant_id: config.tenantId,
          action: "loadtest.event_log",
          detail: `Cycle ${cycleNum}: GET /targets/${cid}/eventlog (6h window)`,
          outcome: result.ok ? "success" : "failure",
          url: result.url,
          http_status: result.status,
          row_count: Array.isArray(result.data) ? result.data.length : 0,
          error_message: result.error,
        });
      }
    }

    // ── Phase 4: Water consumption — every 24 hours ──
    if (runWc) {
      for (const cid of config.controllers) {
        const result = await talgilGetWaterConsumption(baseUrl, apiKey, cid, wcFromMs, untilMs, "daily");
        requestCount++;
        if (!result.ok) errorCount++;

        await writeAudit(this.env.DB, {
          tenant_id: config.tenantId,
          action: "loadtest.wc",
          detail: `Cycle ${cycleNum}: GET /targets/${cid}/wc/valves (24h window)`,
          outcome: result.ok ? "success" : "failure",
          url: result.url,
          http_status: result.status,
          error_message: result.error,
        });
      }
    }

    const phases = ["sync" + (runDbLogs ? "+sensor_log+event_log" : "") + (runWc ? "+wc" : "")];
    const cycleMs = Date.now() - cycleStart;

    await writeAudit(this.env.DB, {
      tenant_id: config.tenantId,
      action: "loadtest.cycle_complete",
      detail: `Cycle ${cycleNum}: ${requestCount} requests, ${errorCount} errors, ${Math.round(cycleMs / 1000)}s, phases=${phases[0]}`,
      outcome: errorCount === 0 ? "success" : "failure",
    });

    config.cyclesCompleted++;
    await this.state.storage.put("loadtest", config);

    // Schedule next cycle
    const nextAlarmMs = cycleStart + config.cycleMinutes * 60_000;
    const delay = Math.max(nextAlarmMs - Date.now(), 10_000); // at least 10s gap
    await this.state.storage.setAlarm(Date.now() + delay);
  }
}
