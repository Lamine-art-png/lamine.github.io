/**
 * AGRO-AI Cloudflare Worker — Talgil Integration API
 *
 * Routes:
 *   POST /v1/integrations/talgil/connect     → discover controller, fetch initial image
 *   POST /v1/integrations/talgil/sync         → operational sync (full image only)
 *   POST /v1/integrations/talgil/backfill     → historical sensor log (batch)
 *   POST /v1/integrations/talgil/disconnect   → mark integration disconnected
 *   POST /v1/integrations/talgil/test/eventlog → diagnostic: test eventlog permissions
 *   POST /v1/integrations/talgil/test/wc       → diagnostic: test water consumption permissions
 *   GET  /v1/integrations/talgil/status        → integration status + row counts
 *   GET  /v1/integrations/talgil/sensors/latest → latest sensor values with catalog metadata
 *   GET  /v1/integrations/talgil/sensors/history → historical sensor values
 *   GET  /v1/integrations/talgil/audit          → recent audit log entries
 *   GET  /health                                → health check
 */

import { TalgilSyncDO } from "./sync/TalgilSyncDO";
import { handleDecisionAudit } from "./api/routes/decisionAudit";
import { handleDecisionRead } from "./api/routes/decisionRead";
import { handleDemoSampleField } from "./api/routes/demoSampleField";
import { handleDemoSampleResponse } from "./api/routes/demoSampleResponse";
import { handleEarthDailyDecision } from "./api/routes/earthdailyDecision";
import { handleEarthDailyEndToEnd } from "./api/routes/earthdailyEndToEnd";
import { handleEarthDailyNormalize } from "./api/routes/earthdailyNormalize";
import { handleEarthDailyReport } from "./api/routes/earthdailyReport";
import { handleEarthDailyStatus } from "./api/routes/earthdailyStatus";
import { handleHealth } from "./api/routes/health";
import { attachCors, preflightResponse } from "./lib/cloudflare/cors";
import { codeFromError, errorEnvelope, readJsonBody, safeErrorMessage, statusFromError } from "./lib/cloudflare/errors";
import type { Env } from "./lib/cloudflare/env";
import { checkRateLimit } from "./lib/cloudflare/rateLimit";
import { requestIdFrom } from "./lib/cloudflare/requestId";

// Re-export Durable Object class for wrangler
export { TalgilSyncDO };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    const requestId = requestIdFrom(request);

    const finalize = (response: Response) => attachCors(response, request, env, requestId);
    const json = (data: unknown, status = 200, mode: "demo" | "live" = "demo") =>
      finalize(Response.json({ ok: true, request_id: requestId, provider: "earthdaily", mode, data }, { status }));
    const healthJson = (data: ReturnType<typeof handleHealth>) =>
      finalize(Response.json({ ...data, ok: true, request_id: requestId, provider: "earthdaily", mode: "demo", data }));

    if (method === "OPTIONS") {
      return preflightResponse(request, env, requestId);
    }

    // ── Health ──────────────────────────────────────────
    if (method === "GET" && path === "/health") {
      return healthJson(handleHealth(env));
    }

    const earthDailyResponse = await routeEarthDaily(request, env, path, method, requestId, json, finalize);
    if (earthDailyResponse) {
      return earthDailyResponse;
    }

    // ── Auth guard ──────────────────────────────────────
    const adminToken = request.headers.get("x-admin-token") ??
      request.headers.get("Authorization")?.replace("Bearer ", "");

    if (adminToken !== env.ADMIN_TOKEN) {
      return finalize(Response.json({ error: "Unauthorized" }, { status: 401 }));
    }

    const tenantId = url.searchParams.get("tenantId");
    if (!tenantId && path.startsWith("/v1/integrations/talgil")) {
      return finalize(Response.json({ error: "tenantId query param required" }, { status: 400 }));
    }

    // ── Sync DO routes (POST) ───────────────────────────
    if (method === "POST" && path.startsWith("/v1/integrations/talgil/")) {
      const action = path.replace("/v1/integrations/talgil/", "");
      return finalize(await routeToSyncDO(env, tenantId!, action, url));
    }

    // ── Read routes (GET) ───────────────────────────────
    if (method === "GET") {
      switch (path) {
        case "/v1/integrations/talgil/status":
          return finalize(await handleStatus(env, tenantId!));
        case "/v1/integrations/talgil/sensors/latest":
          return finalize(await handleSensorsLatest(env, tenantId!));
        case "/v1/integrations/talgil/sensors/history":
          return finalize(await handleSensorsHistory(env, tenantId!, url));
        case "/v1/integrations/talgil/audit":
          return finalize(await handleAuditLog(env, tenantId!));
        default:
          return finalize(Response.json({ error: "Not found" }, { status: 404 }));
      }
    }

    return finalize(Response.json({ error: "Not found" }, { status: 404 }));
  },
};

async function routeEarthDaily(
  request: Request,
  env: Env,
  path: string,
  method: string,
  requestId: string,
  json: (data: unknown, status?: number, mode?: "demo" | "live") => Response,
  finalize: (response: Response) => Response,
): Promise<Response | null> {
  const maybeDecision = path.match(/^\/api\/v1\/decisions\/([^/]+)$/);
  const maybeAudit = path.match(/^\/api\/v1\/decisions\/([^/]+)\/audit$/);
  const isEarthDailyPath = path.startsWith("/api/v1/partners/earthdaily/") ||
    path.startsWith("/api/v1/demo/earthdaily/") ||
    Boolean(maybeDecision || maybeAudit);
  if (!isEarthDailyPath) return null;

  const limit = await checkRateLimit(request, env);
  if (!limit.allowed) {
    return finalize(Response.json(errorEnvelope(requestId, {
      code: limit.code ?? "rate_limited",
      message: limit.message ?? "Rate limit exceeded.",
    }), { status: 429 }));
  }

  try {
    if (method === "GET" && path === "/api/v1/partners/earthdaily/status") {
      return json(handleEarthDailyStatus(env), 200, statusMode(env));
    }
    if (method === "GET" && path === "/api/v1/demo/earthdaily/sample-field") {
      return json(handleDemoSampleField(), 200, "demo");
    }
    if (method === "GET" && path === "/api/v1/demo/earthdaily/sample-response") {
      return json(handleDemoSampleResponse(), 200, "demo");
    }
    if (method === "GET" && maybeDecision) {
      return json(await handleDecisionRead(env, decodeURIComponent(maybeDecision[1])), 200, "demo");
    }
    if (method === "GET" && maybeAudit) {
      return json(await handleDecisionAudit(env, decodeURIComponent(maybeAudit[1])), 200, "demo");
    }

    if (method !== "POST") {
      throw Object.assign(new Error("Method not allowed."), { code: "method_not_allowed", status: 405 });
    }

    const body = await readJsonBody(request);
    if (path === "/api/v1/partners/earthdaily/normalize") {
      const pack = handleEarthDailyNormalize(body);
      return json(pack, 200, pack.provider_trace.mode);
    }
    if (path === "/api/v1/partners/earthdaily/decision") {
      const mode = inferMode(body);
      return json(await handleEarthDailyDecision(body, env, requestId, mode), 200, mode);
    }
    if (path === "/api/v1/partners/earthdaily/report") {
      return json(await handleEarthDailyReport(body, env, requestId), 200, inferMode(body));
    }
    if (path === "/api/v1/partners/earthdaily/end-to-end") {
      const data = await handleEarthDailyEndToEnd(body, env, requestId);
      return json(data, 200, data.integration_metadata.mode);
    }

    throw Object.assign(new Error("EarthDaily route not found."), { code: "not_found", status: 404 });
  } catch (error) {
    return finalize(Response.json(errorEnvelope(requestId, {
      code: codeFromError(error),
      message: safeErrorMessage(error),
      details: (error as { details?: unknown })?.details,
    }), { status: statusFromError(error) }));
  }
}

function statusMode(env: Env): "demo" | "live" {
  return env.LIVE_EARTHDAILY_ENABLED === "true" &&
    Boolean(env.EARTHDAILY_CLIENT_ID && env.EARTHDAILY_SECRET && env.EARTHDAILY_AUTH_URL && env.EARTHDAILY_API_URL)
    ? "live"
    : "demo";
}

function inferMode(body: unknown): "demo" | "live" {
  const record = body as {
    mode?: unknown;
    provider_trace?: { mode?: unknown };
    earthdaily_raw_input?: { mode?: unknown };
    raw?: { mode?: unknown };
    normalized_signal_pack?: { provider_trace?: { mode?: unknown } };
    decision_output?: { trace?: { provider?: unknown } };
  };
  const mode = record?.mode ??
    record?.earthdaily_raw_input?.mode ??
    record?.raw?.mode ??
    record?.provider_trace?.mode ??
    record?.normalized_signal_pack?.provider_trace?.mode;
  return mode === "live" ? "live" : "demo";
}

// ── Route POST actions to Durable Object ────────────────

async function routeToSyncDO(
  env: Env,
  tenantId: string,
  action: string,
  requestUrl: URL,
): Promise<Response> {
  // Map action paths to sync DO modes
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

  // Forward from/until params for backfill
  const from = requestUrl.searchParams.get("from");
  const until = requestUrl.searchParams.get("until");
  if (from) doUrl.searchParams.set("from", from);
  if (until) doUrl.searchParams.set("until", until);

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
  const integration = await env.DB
    .prepare(`SELECT * FROM integrations_talgil WHERE tenant_id = ?`)
    .bind(tenantId)
    .first();

  const sensorRows = await env.DB
    .prepare(`SELECT COUNT(*) AS n FROM talgil_sensor_log WHERE tenant_id = ?`)
    .bind(tenantId)
    .first<{ n: number }>();

  const catalogRows = await env.DB
    .prepare(`SELECT COUNT(*) AS n FROM talgil_sensor_catalog WHERE tenant_id = ?`)
    .bind(tenantId)
    .first<{ n: number }>();

  const eventRows = await env.DB
    .prepare(`SELECT COUNT(*) AS n FROM talgil_event_log WHERE tenant_id = ?`)
    .bind(tenantId)
    .first<{ n: number }>();

  const wcRows = await env.DB
    .prepare(`SELECT COUNT(*) AS n FROM talgil_valve_wc WHERE tenant_id = ?`)
    .bind(tenantId)
    .first<{ n: number }>();

  return Response.json({
    integration: integration ?? null,
    counts: {
      sensorRows: sensorRows?.n ?? 0,
      sensorCatalogRows: catalogRows?.n ?? 0,
      eventRows: eventRows?.n ?? 0,
      valveWcRows: wcRows?.n ?? 0,
    },
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
         sc.units
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
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "100", 10), 1000);

  let query: string;
  let params: unknown[];

  if (sensorUid) {
    query = `SELECT
               sl.sensor_uid, sl.observed_at, sl.observed_at_ms, sl.value_num,
               sc.sensor_name, sc.sensor_type, sc.units
             FROM talgil_sensor_log sl
             LEFT JOIN talgil_sensor_catalog sc
               ON sl.tenant_id = sc.tenant_id
               AND sl.controller_id = sc.controller_id
               AND sl.sensor_uid = sc.sensor_uid
             WHERE sl.tenant_id = ? AND sl.sensor_uid = ?
             ORDER BY sl.observed_at_ms DESC
             LIMIT ?`;
    params = [tenantId, sensorUid, limit];
  } else {
    query = `SELECT
               sl.sensor_uid, sl.observed_at, sl.observed_at_ms, sl.value_num,
               sc.sensor_name, sc.sensor_type, sc.units
             FROM talgil_sensor_log sl
             LEFT JOIN talgil_sensor_catalog sc
               ON sl.tenant_id = sc.tenant_id
               AND sl.controller_id = sc.controller_id
               AND sl.sensor_uid = sc.sensor_uid
             WHERE sl.tenant_id = ?
             ORDER BY sl.observed_at_ms DESC
             LIMIT ?`;
    params = [tenantId, limit];
  }

  const stmt = env.DB.prepare(query);
  const bound = params.length === 3
    ? stmt.bind(params[0], params[1], params[2])
    : stmt.bind(params[0], params[1]);

  const rows = await bound.all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    readings: rows.results ?? [],
  });
}

// ── Audit Log ───────────────────────────────────────────

async function handleAuditLog(env: Env, tenantId: string): Promise<Response> {
  const rows = await env.DB
    .prepare(
      `SELECT * FROM audit_log
       WHERE tenant_id = ?
       ORDER BY created_at DESC
       LIMIT 50`,
    )
    .bind(tenantId)
    .all();

  return Response.json({
    tenant_id: tenantId,
    count: rows.results?.length ?? 0,
    entries: rows.results ?? [],
  });
}
