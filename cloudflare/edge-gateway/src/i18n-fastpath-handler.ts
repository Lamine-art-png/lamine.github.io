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
  workersAiModel as dedicatedTranslationModel,
} from "./i18n-translation-engine-v3";
import { fallbackModel, translateFallback } from "./i18n-locale-fallback";

export interface I18nFastpathEnv extends BaseEnv { AI: AiRunner }

type BaseFetch = <Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv) => Promise<Response>;
type LocaleManifest = { locales?: Array<{ code?: string; englishName?: string; nativeName?: string }> };

const LOCAL_LOCALES: LocaleEntry[] = ((localeManifest as LocaleManifest).locales || []).map((locale) => ({
  code: locale.code,
  name: locale.englishName || locale.nativeName || locale.code,
}));

function jsonResponse(payload: unknown, reference?: Response, status = 200): Response {
  const headers = new Headers(reference?.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-agroai-i18n-fallback", "cloudflare-workers-ai");
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

async function translateValidatedCatalog(
  ai: AiRunner,
  locale: string,
  language: string,
  source: Record<string, string>,
): Promise<{ catalog: Record<string, string>; models: string[] }> {
  try {
    const catalog = await translateChunkedCatalog(ai, locale, source, language);
    return { catalog, models: [workersAiModel] };
  } catch (chunkedError) {
    console.warn("workers_ai_chunked_i18n_failed", { locale, error: String(chunkedError) });
    try {
      if (locale.split("-", 1)[0].toLowerCase() === "te") {
        const catalog = await translateFallback(ai, source);
        return { catalog, models: [fallbackModel] };
      }
      const catalog = await translateDedicatedCatalog(ai, locale, source, language);
      return { catalog, models: [dedicatedTranslationModel] };
    } catch (dedicatedError) {
      console.error("workers_ai_dedicated_i18n_failed", {
        locale,
        chunkedError: String(chunkedError),
        dedicatedError: String(dedicatedError),
      });
      throw dedicatedError;
    }
  }
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
    const translated = await translateValidatedCatalog(env.AI, locale.code, locale.name, source);
    const catalog = translated.catalog;
    if (isCanary) {
      const changed = Object.keys(source).filter((key) => catalog[key] !== source[key]);
      if (changed.length < 2) throw new Error("workers_ai_canary_stayed_english");
      return jsonResponse({
        status: "ok",
        locale: locale.code,
        language: locale.name,
        changed_count: changed.length,
        key_count: Object.keys(source).length,
        changed_keys: changed,
        catalog_sha256: await catalogSha256(catalog),
        providers: ["cloudflare_workers_ai"],
        models: translated.models,
        chunks: Math.ceil(Object.keys(source).length / workersAiChunkSize),
      });
    }
    return jsonResponse({
      status: "ok",
      locale: locale.code,
      catalog,
      source: "cloudflare_workers_ai",
      chunks: Math.ceil(Object.keys(source).length / workersAiChunkSize),
      key_count: Object.keys(source).length,
      providers: ["cloudflare_workers_ai"],
      models: translated.models,
    });
  } catch (error) {
    console.error("workers_ai_i18n_generation_failed", { locale: locale.code, error: String(error) });
    try {
      const upstream = await baseFetch(fallback, env);
      return markUpstreamFallback(upstream);
    } catch (upstreamError) {
      console.error("upstream_i18n_fallback_failed", {
        locale: locale.code,
        workersAiError: String(error),
        upstreamError: String(upstreamError),
      });
      return jsonResponse({ status: "error", error: "ui_catalog_generation_unavailable", locale: locale.code }, undefined, 503);
    }
  }
}
