import baseHandler, { originAllowed, requestId, type ConnectorTaskEnvelope } from "./index";
import { handleI18nFastpath, type I18nFastpathEnv } from "./i18n-fastpath-handler";
import { matchesConfiguredToken } from "./queue-policy";

const translationPaths = new Set(["/v1/i18n/catalog", "/v1/i18n/internal/canary"]);
const I18N_EDGE_RELEASE = "provider-chain-v2";
const FIELD_TRANSCRIPTION_PATH = "/v1/internal/edge/field-transcription";
const FIELD_TRANSCRIPTION_MODEL = "@cf/openai/whisper-large-v3-turbo";
const FIELD_TRANSCRIPTION_MAX_BYTES = 25 * 1024 * 1024;
const FIELD_TRANSCRIPTION_MAX_BASE64 = Math.ceil(FIELD_TRANSCRIPTION_MAX_BYTES / 3) * 4 + 4;
const SAFE_LANGUAGE = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;

async function baseFetch<Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv): Promise<Response> {
  const fetcher = baseHandler.fetch as unknown as (request: Request<Host, Cf>, env: I18nFastpathEnv) => Promise<Response>;
  return fetcher(request, env);
}

function bearerToken(request: Request): string {
  const value = request.headers.get("authorization") || "";
  return value.toLowerCase().startsWith("bearer ") ? value.slice(7).trim() : "";
}

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function validBase64Audio(value: unknown): value is string {
  if (typeof value !== "string" || value.length < 4 || value.length > FIELD_TRANSCRIPTION_MAX_BASE64) return false;
  if (value.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(value)) return false;
  const padding = value.endsWith("==") ? 2 : value.endsWith("=") ? 1 : 0;
  const decodedBytes = (value.length * 3) / 4 - padding;
  return decodedBytes > 0 && decodedBytes <= FIELD_TRANSCRIPTION_MAX_BYTES;
}

export async function handleFieldTranscription(request: Request, env: I18nFastpathEnv): Promise<Response> {
  if (!matchesConfiguredToken(bearerToken(request), env.QUEUE_CONSUMER_TOKEN)) {
    return json({ success: false, error: "unauthorized" }, 401);
  }
  const declared = Number(request.headers.get("content-length") || 0);
  if (Number.isFinite(declared) && declared > FIELD_TRANSCRIPTION_MAX_BASE64 + 4096) {
    return json({ success: false, error: "audio_too_large" }, 413);
  }

  let payload: Record<string, unknown>;
  try {
    const candidate = await request.json();
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) throw new Error("invalid");
    payload = candidate as Record<string, unknown>;
  } catch {
    return json({ success: false, error: "invalid_json" }, 400);
  }

  const model = String(payload.model || FIELD_TRANSCRIPTION_MODEL).trim();
  if (model !== FIELD_TRANSCRIPTION_MODEL) {
    return json({ success: false, error: "unsupported_model" }, 400);
  }
  if (!validBase64Audio(payload.audio)) {
    return json({ success: false, error: "invalid_audio" }, 400);
  }
  const language = typeof payload.language === "string" && SAFE_LANGUAGE.test(payload.language)
    ? payload.language
    : undefined;

  try {
    const result = await env.AI.run(FIELD_TRANSCRIPTION_MODEL, {
      audio: payload.audio,
      task: "transcribe",
      vad_filter: true,
      condition_on_previous_text: false,
      ...(language ? { language } : {}),
    });
    return json({ success: true, result });
  } catch {
    return json({ success: false, error: "workers_ai_unavailable" }, 502);
  }
}

function mergeFastpathHeaders(response: Response, request: Request, env: I18nFastpathEnv): Response {
  const headers = new Headers(response.headers);
  const origin = request.headers.get("origin");
  if (origin && originAllowed(origin, env)) {
    headers.set("access-control-allow-origin", origin);
    headers.set("access-control-allow-credentials", "true");
    headers.set("access-control-allow-methods", "GET,HEAD,POST,PUT,PATCH,DELETE,OPTIONS");
    headers.set("access-control-allow-headers", "authorization,content-type,x-request-id,idempotency-key");
    headers.set("access-control-max-age", "86400");
    headers.set("vary", "Origin");
  }
  headers.set("x-agroai-edge", "cloudflare-edge-v1");
  headers.set("x-agroai-i18n-release", I18N_EDGE_RELEASE);
  headers.set("x-request-id", requestId(request));
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  headers.delete("server");
  headers.delete("x-powered-by");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: I18nFastpathEnv): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && pathname === FIELD_TRANSCRIPTION_PATH) {
      const response = await handleFieldTranscription(request, env);
      return mergeFastpathHeaders(response, request, env);
    }
    if (request.method === "POST" && translationPaths.has(pathname)) {
      const response = await handleI18nFastpath(request, env, baseFetch);
      return mergeFastpathHeaders(response, request, env);
    }
    return baseFetch(request, env);
  },
  async queue(batch: MessageBatch<ConnectorTaskEnvelope>, env: I18nFastpathEnv): Promise<void> {
    await baseHandler.queue(batch, env);
  },
  async scheduled(controller: ScheduledController, env: I18nFastpathEnv, ctx: ExecutionContext): Promise<void> {
    await baseHandler.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<I18nFastpathEnv, ConnectorTaskEnvelope>;
