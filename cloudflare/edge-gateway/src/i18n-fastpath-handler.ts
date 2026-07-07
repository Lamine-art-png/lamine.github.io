import type { Env as BaseEnv } from "./index";
import localeManifest from "../../../shared/supported-locales.json";
import { canonicalRequestedSource } from "./i18n-canonical-source";
import {
  canaryAuthorized,
  canarySource,
  canonicalLocale,
  type LocaleEntry,
  type TranslationPayload,
} from "./i18n-edge-validation-v2";
import {
  catalogSha256,
  translateCatalog as translateChunkedCatalog,
  workersAiChunkSize,
  workersAiModel,
  type AiRunner,
} from "./i18n-workers-ai-v2";
import {
  translateCatalog as translateDedicatedCatalog,
  validCatalog,
  workersAiModel as dedicatedTranslationModel,
} from "./i18n-translation-engine-v3";
import { fallbackModel, translateFallback } from "./i18n-locale-fallback";
import { publicTranslationProvider, translateWithPublicFallback } from "./i18n-public-translate-fallback";

export interface I18nFastpathEnv extends BaseEnv { AI: AiRunner }

type BaseFetch = <Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv) => Promise<Response>;
type LocaleManifest = { locales?: Array<{ code?: string; englishName?: string; nativeName?: string }> };
type TranslationResult = { catalog: Record<string, string>; models: string[]; provider: string };
type CachedTranslationPayload = { catalog?: unknown; models?: unknown; provider?: unknown };

type EdgeCacheLike = {
  match(request: Request): Promise<Response | undefined>;
  put(request: Request, response: Response): Promise<void>;
};

type EdgeCacheStorageLike = { default?: EdgeCacheLike };

const LOCAL_LOCALES: LocaleEntry[] = ((localeManifest as LocaleManifest).locales || []).map((locale) => ({
  code: locale.code,
  name: locale.englishName || locale.nativeName || locale.code,
}));
const EDGE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60;
const I18N_UPSTREAM_TIMEOUT_MS = 120_000;
const TRANSLATION_INFLIGHT = new Map<string, Promise<TranslationResult>>();

function jsonResponse(payload: unknown, reference?: Response, status = 200): Response {
  const headers = new Headers(reference?.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.delete("content-length");
  return new Response(JSON.stringify(payload), { status, headers });
}

function markUpstreamFallback(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store");
  headers.set("x-agroai-i18n-fallback", "upstream-backend");
  headers.delete("content-length");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function diagnosticText(value: unknown): string {
  return String(value || "unknown_error").replace(/\s+/g, " ").slice(0, 1200);
}

function edgeCache(): EdgeCacheLike | null {
  const storage = (globalThis as unknown as { caches?: EdgeCacheStorageLike }).caches;
  return storage?.default || null;
}

async function edgeCacheRequest(locale: string, source: Record<string, string>): Promise<Request> {
  const digest = await catalogSha256(source);
  return new Request(`https://agroai-i18n-cache.invalid/catalog/${encodeURIComponent(locale)}/${digest}`, { method: "GET" });
}

async function readEdgeCachedTranslation(
  locale: string,
  source: Record<string, string>,
): Promise<TranslationResult | null> {
  const cache = edgeCache();
  if (!cache) return null;
  try {
    const key = await edgeCacheRequest(locale, source);
    const response = await cache.match(key);
    if (!response?.ok) return null;
    const payload = await response.json() as CachedTranslationPayload;
    if (!validCatalog(source, payload.catalog)) return null;
    const models = Array.isArray(payload.models) ? payload.models.filter((value): value is string => typeof value === "string") : [];
    return {
      catalog: payload.catalog,
      models,
      provider: typeof payload.provider === "string" && payload.provider ? payload.provider : "edge_catalog_cache",
    };
  } catch (error) {
    console.warn("edge_i18n_cache_read_failed", { locale, error: String(error) });
    return null;
  }
}

async function writeEdgeCachedTranslation(
  locale: string,
  source: Record<string, string>,
  translated: TranslationResult,
): Promise<void> {
  const cache = edgeCache();
  if (!cache) return;
  try {
    const key = await edgeCacheRequest(locale, source);
    const response = new Response(JSON.stringify(translated), {
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": `public, max-age=${EDGE_CACHE_TTL_SECONDS}`,
      },
    });
    await cache.put(key, response);
  } catch (error) {
    console.warn("edge_i18n_cache_write_failed", { locale, error: String(error) });
  }
}

function validatedI18nUpstreamOrigin(raw: string, incoming: URL): URL {
  if (!raw?.trim()) throw new Error("UPSTREAM_API_ORIGIN is not configured");
  const upstream = new URL(raw.trim());
  if (upstream.protocol !== "https:" || upstream.username || upstream.password || upstream.search || upstream.hash) {
    throw new Error("UPSTREAM_API_ORIGIN is invalid");
  }
  if (upstream.host.toLowerCase() === incoming.host.toLowerCase()) {
    throw new Error("UPSTREAM_API_ORIGIN cannot point back to the edge gateway");
  }
  upstream.pathname = upstream.pathname.replace(/\/$/, "");
  return upstream;
}

async function directI18nUpstreamFetch(request: Request, env: I18nFastpathEnv): Promise<Response> {
  const incoming = new URL(request.url);
  const upstream = validatedI18nUpstreamOrigin(env.UPSTREAM_API_ORIGIN, incoming);
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
  headers.set("x-agroai-edge", "cloudflare-edge-v1");
  headers.set("x-forwarded-host", incoming.host);
  headers.set("x-forwarded-proto", "https");

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("i18n_upstream_timeout"), I18N_UPSTREAM_TIMEOUT_MS);
  try {
    return await fetch(new Request(target.toString(), {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      redirect: "manual",
    }), { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function translateValidatedCatalog(
  ai: AiRunner,
  locale: string,
  language: string,
  source: Record<string, string>,
): Promise<TranslationResult> {
  try {
    const catalog = await translateChunkedCatalog(ai, locale, source, language);
    return { catalog, models: [workersAiModel], provider: "cloudflare_workers_ai" };
  } catch (chunkedError) {
    console.warn("workers_ai_chunked_i18n_failed", { locale, error: String(chunkedError) });
    try {
      if (locale.split("-", 1)[0].toLowerCase() === "te") {
        const catalog = await translateFallback(ai, source);
        return { catalog, models: [fallbackModel], provider: "cloudflare_workers_ai" };
      }
      const catalog = await translateDedicatedCatalog(ai, locale, source, language);
      return { catalog, models: [dedicatedTranslationModel], provider: "cloudflare_workers_ai" };
    } catch (dedicatedError) {
      console.error("workers_ai_dedicated_i18n_failed", {
        locale,
        chunkedError: String(chunkedError),
        dedicatedError: String(dedicatedError),
      });
      try {
        const catalog = await translateWithPublicFallback(locale, source);
        return { catalog, models: [], provider: publicTranslationProvider };
      } catch (publicError) {
        console.error("public_i18n_fallback_failed", { locale, error: String(publicError) });
        throw new Error(
          `chunked=${diagnosticText(chunkedError)}; dedicated=${diagnosticText(dedicatedError)}; public=${diagnosticText(publicError)}`,
        );
      }
    }
  }
}

async function translateWithDurableEdgeCache(
  ai: AiRunner,
  locale: string,
  language: string,
  source: Record<string, string>,
): Promise<TranslationResult> {
  const cached = await readEdgeCachedTranslation(locale, source);
  if (cached) return { ...cached, provider: "edge_catalog_cache" };

  const cacheKey = `${locale}:${await catalogSha256(source)}`;
  const existing = TRANSLATION_INFLIGHT.get(cacheKey);
  if (existing) return existing;

  const pending = translateValidatedCatalog(ai, locale, language, source)
    .then(async (translated) => {
      await writeEdgeCachedTranslation(locale, source, translated);
      return translated;
    })
    .finally(() => {
      TRANSLATION_INFLIGHT.delete(cacheKey);
    });
  TRANSLATION_INFLIGHT.set(cacheKey, pending);
  return pending;
}

export async function handleI18nFastpath<Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv, baseFetch: BaseFetch): Promise<Response> {
  const fallback = request.clone();
  const pathname = new URL(request.url).pathname;
  let payload: TranslationPayload;
  try { payload = await request.clone().json() as TranslationPayload; }
  catch { return baseFetch(fallback, env); }

  const locale = canonicalLocale(payload.locale, LOCAL_LOCALES);
  if (!locale || locale.code === "auto" || locale.code === "en") return baseFetch(fallback, env);

  const isCanary = pathname.endsWith("/internal/canary");
  let source: Record<string, string> | null;
  if (isCanary) {
    if (!canaryAuthorized(request, env.QUEUE_CONSUMER_TOKEN)) return baseFetch(fallback, env);
    source = canarySource;
  } else {
    source = canonicalRequestedSource(payload.source);
    if (!source) {
      return jsonResponse({ status: "error", error: "ui_source_catalog_mismatch" }, undefined, 409);
    }
  }

  try {
    const translated = await translateWithDurableEdgeCache(env.AI, locale.code, locale.name, source);
    const catalog = translated.catalog;
    if (isCanary) {
      const changed = Object.keys(source).filter((key) => catalog[key] !== source[key]);
      if (changed.length < 2) throw new Error("ui_canary_stayed_english");
      return jsonResponse({
        status: "ok",
        locale: locale.code,
        language: locale.name,
        changed_count: changed.length,
        key_count: Object.keys(source).length,
        changed_keys: changed,
        catalog_sha256: await catalogSha256(catalog),
        providers: [translated.provider],
        models: translated.models,
        chunks: Math.ceil(Object.keys(source).length / workersAiChunkSize),
      });
    }
    return jsonResponse({
      status: "ok",
      locale: locale.code,
      catalog,
      source: translated.provider,
      chunks: Math.ceil(Object.keys(source).length / workersAiChunkSize),
      key_count: Object.keys(source).length,
      providers: [translated.provider],
      models: translated.models,
    });
  } catch (error) {
    console.error("edge_i18n_generation_failed", { locale: locale.code, error: String(error) });
    try {
      let upstream: Response;
      try {
        upstream = await directI18nUpstreamFetch(fallback.clone(), env);
      } catch (directError) {
        console.warn("direct_i18n_upstream_failed", { locale: locale.code, error: String(directError) });
        upstream = await baseFetch(fallback, env);
      }
      if (isCanary && !upstream.ok) {
        const upstreamBody = await upstream.clone().text().catch(() => "");
        return jsonResponse({
          status: "error",
          error: "ui_canary_generation_unavailable",
          locale: locale.code,
          edge_error: diagnosticText(error),
          upstream_status: upstream.status,
          upstream_body: upstreamBody.slice(0, 2000),
        }, upstream, upstream.status);
      }
      return markUpstreamFallback(upstream);
    } catch (upstreamError) {
      console.error("upstream_i18n_fallback_failed", {
        locale: locale.code,
        edgeError: String(error),
        upstreamError: String(upstreamError),
      });
      return jsonResponse({ status: "error", error: "ui_catalog_generation_unavailable", locale: locale.code }, undefined, 503);
    }
  }
}
