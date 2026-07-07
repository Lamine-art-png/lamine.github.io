import baseHandler, { type ConnectorTaskEnvelope, type Env as BaseEnv } from "./index";

const MODEL = "@cf/zai-org/glm-4.7-flash";
const TRANSLATION_PATHS = new Set(["/v1/i18n/catalog", "/v1/i18n/internal/canary"]);
const CANARY_SOURCE: Record<string, string> = {
  language: "Language",
  settings: "Settings",
  save: "Save",
  support: "Support",
};
const PLACEHOLDER_RE = /\{[A-Za-z_][A-Za-z0-9_]*\}/g;
const CHUNK_SIZE = 36;
const MAX_PARALLEL = 4;

interface WrapperEnv extends BaseEnv {
  AI: Ai;
}

function jsonFromUpstream(payload: unknown, upstream: Response, status = 200): Response {
  const headers = new Headers(upstream.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-agroai-i18n-fallback", "cloudflare-workers-ai");
  headers.delete("content-length");
  return new Response(JSON.stringify(payload), { status, headers });
}

function stripFences(value: string): string {
  return value.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "").trim();
}

function aiText(result: unknown): string {
  if (!result || typeof result !== "object") return "";
  const body = result as Record<string, unknown>;
  if (typeof body.response === "string") return body.response;
  const nested = body.result;
  if (nested && typeof nested === "object" && typeof (nested as Record<string, unknown>).response === "string") {
    return String((nested as Record<string, unknown>).response);
  }
  const choices = body.choices;
  if (Array.isArray(choices)) {
    const first = choices[0] as Record<string, unknown> | undefined;
    const message = first?.message as Record<string, unknown> | undefined;
    if (typeof message?.content === "string") return message.content;
  }
  return "";
}

function placeholderSignature(value: string): string[] {
  return (value.match(PLACEHOLDER_RE) || []).sort();
}

function validCatalog(source: Record<string, string>, candidate: unknown): candidate is Record<string, string> {
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
  const translated = candidate as Record<string, unknown>;
  const sourceKeys = Object.keys(source).sort();
  const translatedKeys = Object.keys(translated).sort();
  if (sourceKeys.length !== translatedKeys.length || sourceKeys.some((key, index) => key !== translatedKeys[index])) return false;
  return sourceKeys.every((key) => {
    const value = translated[key];
    return typeof value === "string" && value.trim().length > 0 &&
      JSON.stringify(placeholderSignature(value)) === JSON.stringify(placeholderSignature(source[key]));
  });
}

async function translateChunk(env: WrapperEnv, locale: string, source: Record<string, string>): Promise<Record<string, string>> {
  const messages = [
    {
      role: "system",
      content: `Translate every JSON string value from English into locale ${locale}. Return one JSON object only. Preserve every key exactly. Preserve placeholders in braces exactly. Preserve AGRO-AI, product names, URLs, units, numbers, and Markdown syntax. Translate naturally and concisely.`,
    },
    { role: "user", content: JSON.stringify(source) },
  ];
  let result = await env.AI.run(MODEL, { messages, temperature: 0, max_completion_tokens: 4096 });
  let raw = stripFences(aiText(result));
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { parsed = null; }
  if (!validCatalog(source, parsed)) {
    result = await env.AI.run(MODEL, {
      messages: [
        ...messages,
        { role: "assistant", content: raw },
        { role: "user", content: "Repair the answer. Return JSON only with exactly the original keys, non-empty translated values, and unchanged placeholders." },
      ],
      temperature: 0,
      max_completion_tokens: 4096,
    });
    raw = stripFences(aiText(result));
    try { parsed = JSON.parse(raw); } catch { parsed = null; }
  }
  if (!validCatalog(source, parsed)) throw new Error("workers_ai_invalid_catalog");
  return parsed;
}

async function translateCatalog(env: WrapperEnv, locale: string, source: Record<string, string>): Promise<Record<string, string>> {
  const entries = Object.entries(source);
  const chunks: Record<string, string>[] = [];
  for (let index = 0; index < entries.length; index += CHUNK_SIZE) {
    chunks.push(Object.fromEntries(entries.slice(index, index + CHUNK_SIZE)));
  }
  const output: Record<string, string> = {};
  for (let index = 0; index < chunks.length; index += MAX_PARALLEL) {
    const batch = chunks.slice(index, index + MAX_PARALLEL);
    const results = await Promise.all(batch.map((chunk) => translateChunk(env, locale, chunk)));
    for (const result of results) Object.assign(output, result);
  }
  if (!validCatalog(source, output)) throw new Error("workers_ai_catalog_reconciliation_failed");
  return output;
}

async function sha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((item) => item.toString(16).padStart(2, "0")).join("");
}

async function upstreamGenerationFailure(response: Response): Promise<boolean> {
  if (response.status !== 503) return false;
  try {
    const body = await response.clone().json() as { detail?: { code?: string } };
    return body.detail?.code === "ui_catalog_generation_unavailable" || body.detail?.code === "ui_canary_generation_unavailable";
  } catch {
    return false;
  }
}

async function workersAiFallback(request: Request, env: WrapperEnv, upstream: Response): Promise<Response> {
  if (!(await upstreamGenerationFailure(upstream))) return upstream;
  let payload: { locale?: unknown; source?: unknown };
  try { payload = await request.clone().json(); } catch { return upstream; }
  const locale = typeof payload.locale === "string" ? payload.locale.replace("_", "-") : "";
  if (!locale || locale === "en" || locale === "auto") return upstream;
  const pathname = new URL(request.url).pathname;
  const source = pathname.endsWith("/internal/canary")
    ? CANARY_SOURCE
    : payload.source && typeof payload.source === "object" && !Array.isArray(payload.source)
      ? payload.source as Record<string, string>
      : null;
  if (!source || !Object.values(source).every((value) => typeof value === "string")) return upstream;

  try {
    const catalog = await translateCatalog(env, locale, source);
    if (pathname.endsWith("/internal/canary")) {
      const changedKeys = Object.keys(source).filter((key) => catalog[key] !== source[key]);
      if (changedKeys.length < 2) return upstream;
      return jsonFromUpstream({
        status: "ok",
        locale,
        language: locale,
        changed_count: changedKeys.length,
        key_count: Object.keys(source).length,
        changed_keys: changedKeys,
        catalog_sha256: await sha256(catalog),
        providers: ["cloudflare_workers_ai"],
        models: [MODEL],
        chunks: Math.ceil(Object.keys(source).length / CHUNK_SIZE),
      }, upstream);
    }
    return jsonFromUpstream({
      status: "ok",
      locale,
      catalog,
      source: "cloudflare_workers_ai",
      chunks: Math.ceil(Object.keys(source).length / CHUNK_SIZE),
      key_count: Object.keys(source).length,
      providers: ["cloudflare_workers_ai"],
      models: [MODEL],
    }, upstream);
  } catch (error) {
    console.error("workers_ai_i18n_fallback_failed", { locale, error: String(error) });
    return upstream;
  }
}

export default {
  async fetch(request: Request, env: WrapperEnv, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    const clone = TRANSLATION_PATHS.has(pathname) && request.method === "POST" ? request.clone() : null;
    const response = await baseHandler.fetch(request, env, ctx);
    if (!clone) return response;
    return workersAiFallback(clone, env, response);
  },
  async queue(batch: MessageBatch<ConnectorTaskEnvelope>, env: WrapperEnv, ctx: ExecutionContext): Promise<void> {
    await baseHandler.queue(batch, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: WrapperEnv, ctx: ExecutionContext): Promise<void> {
    await baseHandler.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<WrapperEnv, ConnectorTaskEnvelope>;
