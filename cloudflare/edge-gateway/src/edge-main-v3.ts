import baseHandler, { originAllowed, requestId, type ConnectorTaskEnvelope } from "./index";
import { handleI18nFastpath, type I18nFastpathEnv } from "./i18n-fastpath-handler";

const translationPaths = new Set(["/v1/i18n/catalog", "/v1/i18n/internal/canary"]);
const I18N_EDGE_RELEASE = "public-fallback-v1";

async function baseFetch<Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv): Promise<Response> {
  const fetcher = baseHandler.fetch as unknown as (request: Request<Host, Cf>, env: I18nFastpathEnv) => Promise<Response>;
  return fetcher(request, env);
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
