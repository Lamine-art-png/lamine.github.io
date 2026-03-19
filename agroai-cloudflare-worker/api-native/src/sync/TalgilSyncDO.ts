/**
 * TalgilSyncDO — Durable Object that orchestrates Talgil data sync.
 *
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║  ARCHITECTURE DECISIONS (driven by Kosta's direct feedback)    ║
 * ╠══════════════════════════════════════════════════════════════════╣
 * ║  1. /mytargets is called ONCE during connect, never on sync.   ║
 * ║  2. Operational sync uses full image ONLY (/targets/{id}/).    ║
 * ║  3. NO separate /sensors call — sensors are in full image.     ║
 * ║  4. Sensor catalog is populated FROM the full image.           ║
 * ║  5. Historical sensor log is a SEPARATE batch process.         ║
 * ║  6. Historical batch stays within simulator date range.        ║
 * ║  7. Event log + water consumption are DISABLED by default.     ║
 * ║  8. Operational sync runs every 20 minutes (not every minute). ║
 * ╚══════════════════════════════════════════════════════════════════╝
 *
 * Sync modes:
 *   "connect"          → discover controller via /mytargets, fetch first full image
 *   "sync"             → operational: fetch full image, update catalog + snapshot
 *   "backfill"         → historical: fetch sensor log in day-sized chunks
 *   "test_eventlog"    → diagnostic: single event log request to test permissions
 *   "test_wc"          → diagnostic: single water consumption request to test permissions
 */

import {
  talgilListTargets,
  talgilGetFullImage,
  talgilGetSensorLog,
  talgilGetEventLog,
  talgilGetWaterConsumption,
  SIMULATOR_FROM_MS,
  SIMULATOR_UNTIL_MS,
} from "../connectors/talgil";

import {
  mapSensorCatalogFromImage,
  mapSensorSnapshotFromImage,
  mapSensorLogRows,
  mapEventLogRows,
  mapValveWcRows,
} from "../mappers/talgil_map";

import {
  upsertIntegration,
  setIntegrationError,
  getIntegration,
  upsertSensorCatalog,
  upsertSensorLog,
  upsertEventLog,
  upsertValveWc,
} from "../lib/db";

import { writeAudit } from "../lib/audit";

// ── Env type ────────────────────────────────────────────

export interface Env {
  DB: D1Database;
  TALGIL_SYNC: DurableObjectNamespace;
  TALGIL_API_KEY: string;
  TALGIL_BASE_URL: string;
  ADMIN_TOKEN: string;
}

// ── Constants ───────────────────────────────────────────

const ONE_DAY_MS = 86_400_000;

// Historical backfill: chunk size = 1 day to stay polite
const BACKFILL_CHUNK_MS = ONE_DAY_MS;

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
        default:
          return Response.json(
            { error: `Unknown mode: ${mode}` },
            { status: 400 },
          );
      }
    } catch (err) {
      const msg = (err as Error).message;
      await setIntegrationError(this.env.DB, tenantId, msg);
      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: `sync.${mode}`,
        detail: "Unhandled exception in sync DO",
        outcome: "failure",
        error_message: msg,
      });
      return Response.json({ error: msg }, { status: 500 });
    }
  }

  // ────────────────────────────────────────────────────────
  // MODE: connect
  // Called once. Discovers controller, fetches full image,
  // populates integration row + sensor catalog.
  // ────────────────────────────────────────────────────────
  private async handleConnect(tenantId: string): Promise<Response> {
    const baseUrl = this.env.TALGIL_BASE_URL;
    const apiKey = this.env.TALGIL_API_KEY;

    // Step 1: Discover controller via /mytargets
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
        url: targetsResult.url,
        http_status: targetsResult.status,
      });
    }

    // Use the first target (simulator controller 6115 in dev)
    const target = targetsResult.data[0];
    const controllerId = target.ID;
    const controllerName = target.Name ?? `Controller ${controllerId}`;

    // Step 2: Fetch full image to get sensors and metadata
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
        url: imageResult.url,
        http_status: imageResult.status,
      });
    }

    const image = imageResult.data;
    const controllerOnline = image.Online ?? 0;

    // Step 3: Populate integration row
    await upsertIntegration(
      this.env.DB,
      tenantId,
      controllerId,
      controllerName,
      controllerOnline,
      "connected",
      JSON.stringify(image).slice(0, 50000), // cap stored JSON
    );

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

    return Response.json({
      ok: true,
      controller_id: controllerId,
      controller_name: controllerName,
      controller_online: controllerOnline,
      sensor_catalog_count: catalogCount,
      sensor_snapshot_count: snapshotCount,
      sensors_in_image: image.Sensors?.length ?? 0,
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: sync (operational)
  // Fetches full image ONLY. No /mytargets. No /sensors.
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

    // Single request: full image
    const imageResult = await talgilGetFullImage(baseUrl, apiKey, controllerId);

    await writeAudit(this.env.DB, {
      tenant_id: tenantId,
      action: "sync.full_image",
      detail: `GET /targets/${controllerId}/ operational sync`,
      outcome: imageResult.ok ? "success" : "failure",
      url: imageResult.url,
      http_status: imageResult.status,
      error_message: imageResult.error,
    });

    if (!imageResult.ok || !imageResult.data) {
      const errMsg = imageResult.error ?? "Full image fetch failed";
      await setIntegrationError(this.env.DB, tenantId, errMsg);
      return Response.json({
        ok: false,
        error: errMsg,
        url: imageResult.url,
        http_status: imageResult.status,
      });
    }

    const image = imageResult.data;

    // Update integration row (status, online, timestamp)
    await upsertIntegration(
      this.env.DB,
      tenantId,
      controllerId,
      image.Name ?? `Controller ${controllerId}`,
      image.Online ?? 0,
      "connected",
      JSON.stringify(image).slice(0, 50000),
    );

    // Update sensor catalog from full image
    const catalogRows = mapSensorCatalogFromImage(tenantId, controllerId, image);
    const catalogCount = await upsertSensorCatalog(this.env.DB, catalogRows);

    // Capture sensor snapshot from full image
    const snapshotRows = mapSensorSnapshotFromImage(tenantId, controllerId, image);
    const snapshotCount = await upsertSensorLog(this.env.DB, snapshotRows);

    return Response.json({
      ok: true,
      mode: "sync",
      controller_id: controllerId,
      controller_online: image.Online ?? 0,
      catalog_upserted: catalogCount,
      snapshot_stored: snapshotCount,
      sensors_in_image: image.Sensors?.length ?? 0,
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: backfill (historical sensor log)
  // Fetches /sensors/log in day-sized chunks within simulator range.
  // This is a SEPARATE process from operational sync.
  // Accepts optional from/until query params (ms).
  // Defaults to full simulator date range.
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

    // Default to simulator date range; allow override
    const fromMs = parseInt(url.searchParams.get("from") ?? String(SIMULATOR_FROM_MS), 10);
    const untilMs = parseInt(url.searchParams.get("until") ?? String(SIMULATOR_UNTIL_MS), 10);

    // Clamp to simulator range for safety
    const clampedFrom = Math.max(fromMs, SIMULATOR_FROM_MS);
    const clampedUntil = Math.min(untilMs, SIMULATOR_UNTIL_MS);

    if (clampedFrom >= clampedUntil) {
      return Response.json({
        ok: false,
        error: "Invalid or empty date range after clamping to simulator window",
        simulator_from: new Date(SIMULATOR_FROM_MS).toISOString(),
        simulator_until: new Date(SIMULATOR_UNTIL_MS).toISOString(),
        requested_from: new Date(fromMs).toISOString(),
        requested_until: new Date(untilMs).toISOString(),
      });
    }

    const chunks: Array<{ from: number; until: number }> = [];
    let cursor = clampedFrom;
    while (cursor < clampedUntil) {
      const chunkEnd = Math.min(cursor + BACKFILL_CHUNK_MS, clampedUntil);
      chunks.push({ from: cursor, until: chunkEnd });
      cursor = chunkEnd;
    }

    let totalRows = 0;
    const chunkResults: Array<{
      from: string;
      until: string;
      ok: boolean;
      rows: number;
      url: string;
      error?: string;
    }> = [];

    for (const chunk of chunks) {
      const result = await talgilGetSensorLog(
        baseUrl,
        apiKey,
        controllerId,
        chunk.from,
        chunk.until,
      );

      await writeAudit(this.env.DB, {
        tenant_id: tenantId,
        action: "backfill.sensor_log",
        detail: `GET /targets/${controllerId}/sensors/log chunk`,
        outcome: result.ok ? "success" : "failure",
        url: result.url,
        http_status: result.status,
        row_count: Array.isArray(result.data) ? result.data.length : 0,
        error_message: result.error,
      });

      if (result.ok && Array.isArray(result.data)) {
        const logRows = mapSensorLogRows(tenantId, controllerId, result.data);
        const inserted = await upsertSensorLog(this.env.DB, logRows);
        totalRows += inserted;
        chunkResults.push({
          from: new Date(chunk.from).toISOString(),
          until: new Date(chunk.until).toISOString(),
          ok: true,
          rows: inserted,
          url: result.url,
        });
      } else {
        chunkResults.push({
          from: new Date(chunk.from).toISOString(),
          until: new Date(chunk.until).toISOString(),
          ok: false,
          rows: 0,
          url: result.url,
          error: result.error,
        });
      }

      // Respect 15-second minimum interval between log requests
      // (Talgil API behavior guidelines v8)
      if (chunks.indexOf(chunk) < chunks.length - 1) {
        await new Promise((resolve) => setTimeout(resolve, 16_000));
      }
    }

    return Response.json({
      ok: true,
      mode: "backfill",
      controller_id: controllerId,
      date_range: {
        from: new Date(clampedFrom).toISOString(),
        until: new Date(clampedUntil).toISOString(),
      },
      chunks_processed: chunkResults.length,
      total_rows_stored: totalRows,
      chunk_details: chunkResults,
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: test_eventlog (diagnostic)
  // Single request to /eventlog to test permissions.
  // Uses middle of simulator date range.
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
      detail: `Diagnostic: GET /targets/${controllerId}/eventlog`,
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
      });
    }

    return Response.json({
      ok: false,
      endpoint: "eventlog",
      url: result.url,
      http_status: result.status,
      error: result.error,
      entries_received: Array.isArray(result.data) ? result.data.length : 0,
      diagnosis:
        result.status === 403
          ? "HTTP 403: Dev account may lack eventlog permission. Confirm with Kosta."
          : result.status === 0
            ? "Network error: Request may not have reached Talgil server."
            : `Unexpected status ${result.status}. Check URL construction.`,
    });
  }

  // ────────────────────────────────────────────────────────
  // MODE: test_wc (diagnostic)
  // Single request to /wc/valves to test permissions.
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
      detail: `Diagnostic: GET /targets/${controllerId}/wc/valves`,
      outcome: result.ok ? "success" : "failure",
      url: result.url,
      http_status: result.status,
      row_count: Array.isArray(result.data) ? result.data.length : 0,
      error_message: result.error,
    });

    if (result.ok && Array.isArray(result.data) && result.data.length > 0) {
      const wcRows = mapValveWcRows(tenantId, controllerId, result.data, "daily");
      const inserted = await upsertValveWc(this.env.DB, wcRows);
      return Response.json({
        ok: true,
        endpoint: "wc/valves",
        url: result.url,
        http_status: result.status,
        entries_received: result.data.length,
        rows_stored: inserted,
        sample: result.data.slice(0, 3),
      });
    }

    return Response.json({
      ok: false,
      endpoint: "wc/valves",
      url: result.url,
      http_status: result.status,
      error: result.error,
      entries_received: Array.isArray(result.data) ? result.data.length : 0,
      diagnosis:
        result.status === 403
          ? "HTTP 403: Dev account may lack water consumption permission. Confirm with Kosta."
          : result.status === 0
            ? "Network error: Request may not have reached Talgil server."
            : `Unexpected status ${result.status}. Check URL construction.`,
    });
  }
}
