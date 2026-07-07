import type { Env as BaseEnv } from "./index";
import {
  canaryAuthorized,
  canarySource,
  canonicalLocale,
  englishValidationRequest,
  registryRequest,
  sourceObject,
  type LocaleEntry,
  type TranslationPayload,
} from "./i18n-edge-validation-v2";
import { catalogSha256, translateCatalog, workersAiChunkSize, workersAiModel, type AiRunner } from "./i18n-workers-ai-v2";

export interface I18nFastpathEnv extends BaseEnv { AI: AiRunner }

type BaseFetch = <Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv) => Promise<Response>;

function jsonResponse(payload: unknown, reference: Response, status = 200): Response {
  const headers = new Headers(reference.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-agroai-i18n-fallback", "cloudflare-workers-ai");
  headers.delete("content-length");
  return new Response(JSON.stringify(payload), { status, headers });
}

async function registry<Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv, baseFetch: BaseFetch) {
  const response = await baseFetch(registryRequest(request), env);
  if (!response.ok) return { response, entries: [] as LocaleEntry[] };
  try {
    const body = await response.clone().json() as { status?: unknown; languages?: unknown };
    if (body.status === "ok" && Array.isArray(body.languages)) return { response, entries: body.languages as LocaleEntry[] };
  } catch { /* fail closed below */ }
  return null;
}

export async function handleI18nFastpath<Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv, baseFetch: BaseFetch): Promise<Response> {
  const fallback = request.clone();
  const pathname = new URL(request.url).pathname;
  let payload: TranslationPayload;
  try { payload = await request.clone().json() as TranslationPayload; }
  catch { return baseFetch(fallback, env); }

  const currentRegistry = await registry(request, env, baseFetch);
  if (!currentRegistry) return new Response('{"status":"error","error":"invalid_i18n_registry_response"}', { status: 502, headers: { "content-type": "application/json" } });
  if (!currentRegistry.response.ok) return currentRegistry.response;
  const locale = canonicalLocale(payload.locale, currentRegistry.entries);
  if (!locale || locale.code === "auto" || locale.code === "en") return baseFetch(fallback, env);

  const isCanary = pathname.endsWith("/internal/canary");
  let source: Record<string, string> | null = null;
  let reference = currentRegistry.response;
  if (isCanary) {
    if (!canaryAuthorized(request, env.QUEUE_CONSUMER_TOKEN)) return baseFetch(fallback, env);
    source = canarySource;
  } else {
    const hasSource = Object.prototype.hasOwnProperty.call(payload, "source");
    const checked = await baseFetch(englishValidationRequest(request, payload.source, hasSource), env);
    if (!checked.ok) return checked;
    try {
      const body = await checked.clone().json() as { status?: unknown; locale?: unknown; catalog?: unknown };
      if (body.status !== "ok" || body.locale !== "en") return jsonResponse({ status: "error", error: "invalid_i18n_validation_response" }, checked, 502);
      source = sourceObject(body.catalog);
    } catch { return jsonResponse({ status: "error", error: "invalid_i18n_validation_response" }, checked, 502); }
    if (!source) return jsonResponse({ status: "error", error: "invalid_i18n_validation_response" }, checked, 502);
    reference = checked;
  }

  try {
    const catalog = await translateCatalog(env.AI, locale.code, source, locale.name);
    if (isCanary) {
      const changed = Object.keys(source).filter((key) => catalog[key] !== source[key]);
      if (changed.length < 2) throw new Error("workers_ai_canary_stayed_english");
      return jsonResponse({ status: "ok", locale: locale.code, language: locale.name, changed_count: changed.length, key_count: Object.keys(source).length, changed_keys: changed, catalog_sha256: await catalogSha256(catalog), providers: ["cloudflare_workers_ai"], models: [workersAiModel], chunks: Math.ceil(Object.keys(source).length / workersAiChunkSize) }, reference);
    }
    return jsonResponse({ status: "ok", locale: locale.code, catalog, source: "cloudflare_workers_ai", chunks: Math.ceil(Object.keys(source).length / workersAiChunkSize), key_count: Object.keys(source).length, providers: ["cloudflare_workers_ai"], models: [workersAiModel] }, reference);
  } catch (error) {
    console.error("workers_ai_i18n_generation_failed", { locale: locale.code, error: String(error) });
    return baseFetch(fallback, env);
  }
}
