/**
 * AGRO-AI Cloudflare Worker — Talgil Integration API
 *
 * Routes:
 *   POST /v1/integrations/talgil/connect       → discover controller, fetch initial image
 *   POST /v1/integrations/talgil/sync           → operational sync (filtered image)
 *   POST /v1/integrations/talgil/backfill       → historical sensor log (batch, per-sensor)
 *   POST /v1/integrations/talgil/disconnect     → mark integration disconnected
 *   POST /v1/integrations/talgil/test/eventlog  → diagnostic: test eventlog permissions
 *   POST /v1/integrations/talgil/test/wc        → diagnostic: test water consumption permissions
 *   GET  /v1/integrations/talgil/status         → integration status + row counts
 *   GET  /v1/integrations/talgil/sensors/catalog → sensor catalog (metadata)
 *   GET  /v1/integrations/talgil/sensors/latest  → latest sensor values with catalog metadata
 *   GET  /v1/integrations/talgil/sensors/history → historical sensor values (filterable)
 *   GET  /v1/integrations/talgil/events          → stored event log entries
 *   GET  /v1/integrations/talgil/wc              → stored water consumption data
 *   GET  /v1/integrations/talgil/audit           → recent audit log entries
 *   GET  /health                                 → health check
 */

import { TalgilSyncDO } from "./sync/TalgilSyncDO";
import type { Env } from "./sync/TalgilSyncDO";
import { ensureTenant } from "./lib/db";

// Re-export Durable Object class for wrangler
export { TalgilSyncDO };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // ── Health ──────────────────────────────────────────
    if (path === "/health") {
      return Response.json({
        status: "ok",
        service: "agroai-talgil-connector",
        version: "2.3.0",
        timestamp: new Date().toISOString(),
      });
    }

    // ── CORS preflight ──────────────────────────────────
    if (method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, x-admin-token, Authorization",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    // ── Auth guard ──────────────────────────────────────
    const adminToken = request.headers.get("x-admin-token") ??
      request.headers.get("Authorization")?.replace("Bearer ", "");

    if (adminToken !== env.ADMIN_TOKEN) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }

    const tenantId = url.searchParams.get("tenantId");
    if (!tenantId && path.startsWith("/v1/integrations/talgil")) {
      return Response.json({ error: "tenantId query param required" }, { status: 400 });
    }

    // ── Sync DO routes (POST) ───────────────────────────
    if (method === "POST" && path.startsWith("/v1/integrations/talgil/")) {
      const action = path.replace("/v1/integrations/talgil/", "");

      // Ensure tenant row exists before any FK-constrained writes
      if (action === "connect") {
        await ensureTenant(env.DB, tenantId!);
      }

      return routeToSyncDO(env, tenantId!, action, url);
    }

    // ── Read routes (GET) ───────────────────────────────
    if (method === "GET") {
      switch (path) {
        case "/v1/integrations/talgil/status":
          return handleStatus(env, tenantId!);
        case "/v1/integrations/talgil/sensors/catalog":
          return handleSensorsCatalog(env, tenantId!);
        case "/v1/integrations/talgil/sensors/latest":
          return handleSensorsLatest(env, tenantId!);
        case "/v1/integrations/talgil/sensors/history":
          return handleSensorsHistory(env, tenantId!, url);
        case "/v1/integrations/talgil/events":
          return handleEvents(env, tenantId!, url);
        case "/v1/integrations/talgil/wc":
          return handleWaterConsumption(env, tenantId!, url);
        case "/v1/integrations/talgil/audit":
          return handleAuditLog(env, tenantId!);
        default:
          return Response.json({ error: "Not found" }, { status: 404 });
      }
    }

    return Response.json({ error: "Not found" }, { status: 404 });
  },
};

// ── Route POST actions to Durable Object ────────────────

async function routeToSyncDO(
  env: Env,
  tenantId: string,
  action: string,
  requestUrl: URL,
): Promise<Response> {
  let mode: string;
  switch (action) {
    case "connect":
      mode = "connect";
      break;
    case "sync":
      mode = "sync";
      break;
    case "backfill":
      mode = "backfill";
      break;
    case "disconnect":
      return handleDisconnect(env, tenantId);
    case "test/eventlog":
      mode = "test_eventlog";
      break;
    case "test/wc":
      mode = "test_wc";
      break;
    default:
      return Response.json({ error: `Unknown action: ${action}` }, { status: 404 });
  }

  // Build DO request URL with params
  const doUrl = new URL("https://do-internal/sync");
  doUrl.searchParams.set("tenantId", tenantId);
  doUrl.searchParams.set("mode", mode);

  // Forward backfill params to DO
  for (const key of ["from", "until", "batch", "offset"]) {
    const val = requestUrl.searchParams.get(key);
    if (val) doUrl.searchParams.set(key, val);
  }

  const doId = env.TALGIL_SYNC.idFromName(tenantId);
  const doStub = env.TALGIL_SYNC.get(doId);
  return doStub.fetch(doUrl.toString());
}

// ── Disconnect ──────────────────────────────────────────

async function handleDisconnect(env: Env, tenantId: string): Promise<Response> {
  await env.DB
    .prepare(
      `UPDATE integrations_talgil
       SET status = 'disconnected', updated_at = datetime('now')
       WHERE tenant_id = ?`,
    )
    .bind(tenantId)
    .run();

  return Response.json({ ok: true, tenantId, status: "disconnected" });
}

// ── Status ──────────────────────────────────────────────

async function handleStatus(env: Env, tenantId: string): Promise<Response> {
  // Batch all count queries for performance
  const [integration, sensorRows, catalogRows, eventRows, wcRows, auditRows] =
    await Promise.all([
      env.DB
        .prepare(`SELECT * FROM integrations_talgil WHERE tenant_id = ?`)
        .bind(tenantId)
        .first(),
      env.DB
        .prepare(`SELECT COUNT(*) AS n FROM talgil_sensor_log WHERE tenant_id = ?`)
        .bind(tenantId)
        .first<{ n: number }>(),
      env.DB
        .prepare(`SELECT COUNT(*) AS n FROM talgil_sensor_catalog WHERE tenant_id = ?`)
        .bind(tenantId)
        .first<{ n: number }>(),
      env.DB
        .prepare(`SELECT COUNT(*) AS n FROM talgil_event_log WHERE tenant_id = ?`)
        .bind(tenantId)
        .first<{ n: number }>(),
      env.DB
        .prepare(`SELECT COUNT(*) AS n FROM talgil_valve_wc WHERE tenant_id = ?`)
        .bind(tenantId)
        .first<{ n: number }>(),
      env.DB
        .prepare(`SELECT COUNT(*) AS n FROM audit_log WHERE tenant_id = ?`)
        .bind(tenantId)
        .first<{ n: number }>(),
    ]);

  return Response.json({
    integration: integration ?? null,
    counts: {
      sensorLogRows: sensorRows?.n ?? 0,
      sensorCatalogRows: catalogRows?.n ?? 0,
      eventLogRows: eventRows?.n ?? 0,
      valveWcRows: wcRows?.n ?? 0,
      auditLogRows: auditRows?.n ?? 0,
    },
  });
}

// ── Sensors Catalog (metadata) ───────────────────────────

async function handleSensorsCatalog(
  env: Env,
  tenantId: string,
): Promise<Response> {
  const rows = await env.DB
    .prepare(
      `SELECT sensor_uid, sensor_name, sensor_type, units,
              data_source, last_seen_at, last_seen_at_ms,
              min_limit, max_limit, low_threshold, high_threshold,
              reading_rate, units_descriptor
       FROM talgil_sensor_catalog
       WHERE tenant_id = ?
       ORDER BY sensor_uid`,
    )
    .bind(tenantId)
    .all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    sensors: rows.results ?? [],
  });
}

// ── Sensors Latest (with catalog metadata) ──────────────

async function handleSensorsLatest(
  env: Env,
  tenantId: string,
): Promise<Response> {
  const rows = await env.DB
    .prepare(
      `SELECT
         sl.sensor_uid,
         sl.observed_at,
         sl.observed_at_ms,
         sl.value_num,
         sc.sensor_name,
         sc.sensor_type,
         sc.units,
         sc.units_descriptor,
         sc.min_limit,
         sc.max_limit
       FROM talgil_sensor_log sl
       LEFT JOIN talgil_sensor_catalog sc
         ON sl.tenant_id = sc.tenant_id
         AND sl.controller_id = sc.controller_id
         AND sl.sensor_uid = sc.sensor_uid
       WHERE sl.tenant_id = ?
         AND sl.observed_at_ms = (
           SELECT MAX(sl2.observed_at_ms)
           FROM talgil_sensor_log sl2
           WHERE sl2.tenant_id = sl.tenant_id
             AND sl2.controller_id = sl.controller_id
             AND sl2.sensor_uid = sl.sensor_uid
         )
       ORDER BY sl.sensor_uid`,
    )
    .bind(tenantId)
    .all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    sensors: rows.results ?? [],
  });
}

// ── Sensors History ─────────────────────────────────────

async function handleSensorsHistory(
  env: Env,
  tenantId: string,
  url: URL,
): Promise<Response> {
  const sensorUid = url.searchParams.get("sensor_uid");
  const fromMs = url.searchParams.get("from");
  const untilMs = url.searchParams.get("until");
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "100", 10), 1000);

  let query: string;
  const params: unknown[] = [tenantId];

  if (sensorUid) {
    query = `SELECT
               sl.sensor_uid, sl.observed_at, sl.observed_at_ms, sl.value_num,
               sc.sensor_name, sc.sensor_type, sc.units
             FROM talgil_sensor_log sl
             LEFT JOIN talgil_sensor_catalog sc
               ON sl.tenant_id = sc.tenant_id
               AND sl.controller_id = sc.controller_id
               AND sl.sensor_uid = sc.sensor_uid
             WHERE sl.tenant_id = ? AND sl.sensor_uid = ?`;
    params.push(sensorUid);
  } else {
    query = `SELECT
               sl.sensor_uid, sl.observed_at, sl.observed_at_ms, sl.value_num,
               sc.sensor_name, sc.sensor_type, sc.units
             FROM talgil_sensor_log sl
             LEFT JOIN talgil_sensor_catalog sc
               ON sl.tenant_id = sc.tenant_id
               AND sl.controller_id = sc.controller_id
               AND sl.sensor_uid = sc.sensor_uid
             WHERE sl.tenant_id = ?`;
  }

  if (fromMs) {
    query += ` AND sl.observed_at_ms >= ?`;
    params.push(parseInt(fromMs, 10));
  }
  if (untilMs) {
    query += ` AND sl.observed_at_ms <= ?`;
    params.push(parseInt(untilMs, 10));
  }

  query += ` ORDER BY sl.observed_at_ms DESC LIMIT ?`;
  params.push(limit);

  const stmt = env.DB.prepare(query);
  const bound = stmt.bind(...params);

  const rows = await bound.all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    readings: rows.results ?? [],
  });
}

// ── Events ──────────────────────────────────────────────

async function handleEvents(
  env: Env,
  tenantId: string,
  url: URL,
): Promise<Response> {
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "100", 10), 1000);

  const rows = await env.DB
    .prepare(
      `SELECT event_key, event_at, event_at_ms, event_type, source_key, message
       FROM talgil_event_log
       WHERE tenant_id = ?
       ORDER BY event_at_ms DESC
       LIMIT ?`,
    )
    .bind(tenantId, limit)
    .all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    events: rows.results ?? [],
  });
}

// ── Water Consumption ───────────────────────────────────

async function handleWaterConsumption(
  env: Env,
  tenantId: string,
  url: URL,
): Promise<Response> {
  const valveUid = url.searchParams.get("valve_uid");
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "100", 10), 1000);

  let query = `SELECT valve_uid, bucket_start_at, bucket_end_at,
                      bucket_start_ms, bucket_end_ms, rate,
                      amount_value, value_per_area
               FROM talgil_valve_wc
               WHERE tenant_id = ?`;
  const params: unknown[] = [tenantId];

  if (valveUid) {
    query += ` AND valve_uid = ?`;
    params.push(valveUid);
  }

  query += ` ORDER BY bucket_start_ms DESC LIMIT ?`;
  params.push(limit);

  const stmt = env.DB.prepare(query);
  const bound = stmt.bind(...params);

  const rows = await bound.all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    consumption: rows.results ?? [],
  });
}

// ── Audit Log ───────────────────────────────────────────

async function handleAuditLog(env: Env, tenantId: string): Promise<Response> {
  const rows = await env.DB
    .prepare(
      `SELECT * FROM audit_log
       WHERE tenant_id = ?
       ORDER BY created_at DESC
       LIMIT 100`,
    )
    .bind(tenantId)
    .all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    entries: rows.results ?? [],
  });
}
