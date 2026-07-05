export interface Env {
  UPSTREAM_API_ORIGIN: string;
  EDGE_ENVIRONMENT?: string;
  ALLOWED_ORIGINS?: string;
  QUEUE_PUBLISH_TOKEN: string;
  QUEUE_CONSUMER_TOKEN: string;
  CONNECTOR_TASKS: Queue<ConnectorTaskEnvelope>;
}

export interface ConnectorTaskEnvelope {
  job_id: string;
  tenant_id: string;
  task_type: string;
  enqueued_at?: string;
  attempt?: number;
}

const DEFAULT_ALLOWED_ORIGINS = [
  "https://app.agroai-pilot.com",
  "https://agroai-pilot.com",
  "https://www.agroai-pilot.com",
];
const PAGES_ORIGIN = /^https:\/\/(?:[a-z0-9-]+\.)?(?:agroai-portal|lamine-github-io|agroai-command-center-v2-preview)\.pages\.dev$/i;
const TRANSIENT_UPSTREAM_STATUS = new Set([408, 429, 502, 503, 504]);
const EDGE_VERSION = "cloudflare-edge-v1";
const MAX_TASK_FIELD_LENGTH = 256;

export function configuredOrigins(env: Pick<Env, "ALLOWED_ORIGINS">): Set<string> {
  const configured = (env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return new Set([...DEFAULT_ALLOWED_ORIGINS, ...configured]);
}

export function originAllowed(origin: string | null, env: Pick<Env, "ALLOWED_ORIGINS">): boolean {
  if (!origin) return false;
  return configuredOrigins(env).has(origin) || PAGES_ORIGIN.test(origin);
}

export function validatedUpstreamOrigin(raw: string, requestUrl?: URL): URL {
  if (!raw?.trim()) throw new Error("UPSTREAM_API_ORIGIN is not configured");
  const upstream = new URL(raw.trim());
  if (upstream.protocol !== "https:") throw new Error("UPSTREAM_API_ORIGIN must use HTTPS");
  if (upstream.username || upstream.password || upstream.search || upstream.hash) {
    throw new Error("UPSTREAM_API_ORIGIN must be a clean origin URL");
  }
  if (requestUrl && upstream.host.toLowerCase() === requestUrl.host.toLowerCase()) {
    throw new Error("UPSTREAM_API_ORIGIN cannot point back to the edge gateway");
  }
  upstream.pathname = upstream.pathname.replace(/\/$/, "");
  return upstream;
}

export function validTask(value: unknown): value is ConnectorTaskEnvelope {
  if (!value || typeof value !== "object") return false;
  const task = value as Record<string, unknown>;
  for (const field of ["job_id", "tenant_id", "task_type"] as const) {
    const item = task[field];
    if (typeof item !== "string" || !item.trim() || item.length > MAX_TASK_FIELD_LENGTH) return false;
  }
  return true;
}

function bearerToken(request: Request): string {
  const auth = request.headers.get("authorization") || "";
  return auth.toLowerCase().startsWith("bearer ") ? auth.slice(7).trim() : "";
}

function constantTimeEqual(left: string, right: string): boolean {
  if (!left || !right || left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return mismatch === 0;
}

function json(payload: unknown, status = 200, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...headers },
  });
}

function requestId(request: Request): string {
  return request.headers.get("cf-ray") || request.headers.get("x-request-id") || crypto.randomUUID();
}

function securityHeaders(headers: Headers, id: string): void {
  headers.set("x-agroai-edge", EDGE_VERSION);
  headers.set("x-request-id", id);
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  headers.delete("server");
  headers.delete("x-powered-by");
}

function corsHeaders(origin: string | null, env: Pick<Env, "ALLOWED_ORIGINS">): Headers {
  const headers = new Headers();
  if (originAllowed(origin, env) && origin) {
    headers.set("access-control-allow-origin", origin);
    headers.set("access-control-allow-credentials", "true");
    headers.set("access-control-allow-methods", "GET,HEAD,POST,PUT,PATCH,DELETE,OPTIONS");
    headers.set("access-control-allow-headers", "authorization,content-type,x-request-id,idempotency-key");
    headers.set("access-control-max-age", "86400");
    headers.set("vary", "Origin");
  }
  return headers;
}

function mergeCors(response: Response, origin: string | null, env: Pick<Env, "ALLOWED_ORIGINS">, id: string): Response {
  const headers = new Headers(response.headers);
  corsHeaders(origin, env).forEach((value, key) => headers.set(key, value));
  securityHeaders(headers, id);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function retryDelay(attempts: number): number {
  return Math.min(900, 15 * 2 ** Math.min(Math.max(attempts, 0), 6));
}

async function fetchWithTimeout(request: Request, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("upstream_timeout"), timeoutMs);
  try {
    return await fetch(request, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function timeoutForPath(pathname: string): number {
  return /\/(?:brain|intelligence|ai)(?:\/|$)/.test(pathname) ? 120_000 : 45_000;
}

function upstreamRequest(request: Request, upstream: URL, id: string): Request {
  const incoming = new URL(request.url);
  const target = new URL(upstream.toString());
  target.pathname = `${upstream.pathname}${incoming.pathname}`.replace(/\/+/g, "/");
  target.search = incoming.search;

  const headers = new Headers(request.headers);
  for (const header of [
    "host",
    "cf-connecting-ip",
    "cf-ray",
    "cf-visitor",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-real-ip",
    "x-agroai-internal-token",
    "x-agroai-edge",
  ]) headers.delete(header);
  headers.set("x-request-id", id);
  headers.set("x-agroai-edge", EDGE_VERSION);
  headers.set("x-forwarded-host", incoming.host);
  headers.set("x-forwarded-proto", "https");

  return new Request(target.toString(), {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    redirect: "manual",
  });
}

async function proxyToUpstream(request: Request, env: Env): Promise<Response> {
  const incoming = new URL(request.url);
  const upstream = validatedUpstreamOrigin(env.UPSTREAM_API_ORIGIN, incoming);
  const id = requestId(request);
  const origin = request.headers.get("origin");
  const retryableMethod = request.method === "GET" || request.method === "HEAD";
  const timeoutMs = timeoutForPath(incoming.pathname);
  const attempts = retryableMethod ? 2 : 1;
  let lastError: unknown;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetchWithTimeout(upstreamRequest(request, upstream, id), timeoutMs);
      if (attempt + 1 < attempts && TRANSIENT_UPSTREAM_STATUS.has(response.status)) continue;
      return mergeCors(response, origin, env, id);
    } catch (error) {
      lastError = error;
      if (attempt + 1 >= attempts) break;
    }
  }

  console.error("edge_upstream_unavailable", { request_id: id, path: incoming.pathname, error: String(lastError) });
  return mergeCors(
    json({ status: "error", error: "upstream_unavailable", request_id: id }, 503),
    origin,
    env,
    id,
  );
}

async function enqueueTask(request: Request, env: Env): Promise<Response> {
  if (!constantTimeEqual(bearerToken(request), env.QUEUE_PUBLISH_TOKEN || "")) {
    return json({ error: "unauthorized" }, 401);
  }
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }
  if (!validTask(payload)) return json({ error: "invalid_connector_task" }, 400);
  const task: ConnectorTaskEnvelope = {
    job_id: payload.job_id.trim(),
    tenant_id: payload.tenant_id.trim(),
    task_type: payload.task_type.trim(),
    enqueued_at: new Date().toISOString(),
    attempt: 0,
  };
  await env.CONNECTOR_TASKS.send(task, { contentType: "json" });
  return json({ status: "queued", job_id: task.job_id }, 202);
}

async function consumeTask(message: Message<ConnectorTaskEnvelope>, env: Env): Promise<void> {
  const task = message.body;
  if (!validTask(task)) {
    console.error("queue_invalid_task", { message_id: message.id });
    message.ack();
    return;
  }

  let upstream: URL;
  try {
    upstream = validatedUpstreamOrigin(env.UPSTREAM_API_ORIGIN);
  } catch (error) {
    console.error("queue_upstream_misconfigured", { error: String(error) });
    message.retry({ delaySeconds: retryDelay(message.attempts) });
    return;
  }
  const target = new URL("/v1/internal/queue/connector-task", upstream);
  let response: Response;
  try {
    response = await fetchWithTimeout(new Request(target.toString(), {
      method: "POST",
      headers: {
        "authorization": `Bearer ${env.QUEUE_CONSUMER_TOKEN}`,
        "content-type": "application/json",
        "x-request-id": `queue-${message.id}`,
      },
      body: JSON.stringify(task),
    }), 120_000);
  } catch (error) {
    console.error("queue_delivery_network_error", { message_id: message.id, error: String(error) });
    message.retry({ delaySeconds: retryDelay(message.attempts) });
    return;
  }

  if (response.ok) {
    message.ack();
    return;
  }
  if (TRANSIENT_UPSTREAM_STATUS.has(response.status) || response.status >= 500) {
    console.warn("queue_delivery_retry", { message_id: message.id, status: response.status, attempts: message.attempts });
    message.retry({ delaySeconds: retryDelay(message.attempts) });
    return;
  }
  console.error("queue_delivery_terminal_rejection", { message_id: message.id, status: response.status });
  message.ack();
}

async function drainOutbox(env: Env): Promise<void> {
  try {
    const upstream = validatedUpstreamOrigin(env.UPSTREAM_API_ORIGIN);
    const target = new URL("/v1/internal/queue/drain-outbox", upstream);
    const response = await fetchWithTimeout(new Request(target.toString(), {
      method: "POST",
      headers: {
        "authorization": `Bearer ${env.QUEUE_CONSUMER_TOKEN}`,
        "content-type": "application/json",
      },
      body: "{}",
    }), 45_000);
    if (!response.ok) console.error("outbox_drain_failed", { status: response.status });
  } catch (error) {
    console.error("outbox_drain_error", { error: String(error) });
  }
}

async function handleFetch(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const origin = request.headers.get("origin");
  const id = requestId(request);

  if (request.method === "OPTIONS") {
    if (origin && !originAllowed(origin, env)) return mergeCors(json({ error: "origin_not_allowed" }, 403), origin, env, id);
    return mergeCors(new Response(null, { status: 204 }), origin, env, id);
  }

  if (url.pathname === "/v1/edge-health" && request.method === "GET") {
    return mergeCors(json({ status: "ok", service: "agroai-api-edge", version: EDGE_VERSION, environment: env.EDGE_ENVIRONMENT || "unknown" }), origin, env, id);
  }

  if (url.pathname === "/v1/internal/edge/connector-tasks" && request.method === "POST") {
    const response = await enqueueTask(request, env);
    return mergeCors(response, origin, env, id);
  }

  if (!url.pathname.startsWith("/v1/")) {
    return mergeCors(json({ error: "not_found" }, 404), origin, env, id);
  }

  return proxyToUpstream(request, env);
}

export default {
  fetch: handleFetch,
  async queue(batch: MessageBatch<ConnectorTaskEnvelope>, env: Env): Promise<void> {
    await Promise.all(batch.messages.map((message) => consumeTask(message, env)));
  },
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(drainOutbox(env));
  },
} satisfies ExportedHandler<Env, ConnectorTaskEnvelope>;
