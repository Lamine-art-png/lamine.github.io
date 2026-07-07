import baseHandler, { type ConnectorTaskEnvelope } from "./index";
import { handleI18nFastpath, type I18nFastpathEnv } from "./i18n-fastpath-handler";
import {
  translateCatalog as translateWithDedicatedModel,
  workersAiModel as dedicatedTranslationModel,
  type AiRunner,
} from "./i18n-translation-engine-v3";
import { fallbackModel, translateFallback } from "./i18n-locale-fallback";

const translationPaths = new Set(["/v1/i18n/catalog", "/v1/i18n/internal/canary"]);

type ChatMessage = { role?: unknown; content?: unknown };
type ChatInput = { messages?: unknown };

function translationRequest(input: unknown): { locale: string; source: Record<string, string> } | null {
  if (!input || typeof input !== "object") return null;
  const messages = (input as ChatInput).messages;
  if (!Array.isArray(messages)) return null;
  const normalized = messages as ChatMessage[];
  const system = normalized.find((item) => item.role === "system" && typeof item.content === "string");
  const user = normalized.find((item) => item.role === "user" && typeof item.content === "string");
  if (typeof system?.content !== "string" || typeof user?.content !== "string") return null;
  const localeMatch = system.content.match(/BCP-47 locale\s+([A-Za-z0-9-]+)/i)
    || system.content.match(/locale\s+([A-Za-z0-9-]+)/i);
  if (!localeMatch) return null;
  let source: unknown;
  try { source = JSON.parse(user.content); } catch { return null; }
  if (!source || typeof source !== "object" || Array.isArray(source)) return null;
  const record = source as Record<string, unknown>;
  if (!Object.keys(record).length || !Object.values(record).every((value) => typeof value === "string")) return null;
  return { locale: localeMatch[1], source: record as Record<string, string> };
}

class DedicatedTranslationAdapter implements AiRunner {
  usedModel = dedicatedTranslationModel;

  constructor(private readonly realAi: AiRunner) {}

  async run(model: string, input: unknown): Promise<unknown> {
    const parsed = translationRequest(input);
    if (!parsed) return this.realAi.run(model, input);
    const root = parsed.locale.split("-", 1)[0].toLowerCase();
    if (root === "te") {
      this.usedModel = fallbackModel;
      const catalog = await translateFallback(this.realAi, parsed.source);
      return { response: JSON.stringify(catalog) };
    }
    this.usedModel = dedicatedTranslationModel;
    const catalog = await translateWithDedicatedModel(this.realAi, parsed.locale, parsed.source);
    return { response: JSON.stringify(catalog) };
  }
}

async function baseFetch<Host, Cf>(request: Request<Host, Cf>, env: I18nFastpathEnv): Promise<Response> {
  const fetcher = baseHandler.fetch as unknown as (request: Request<Host, Cf>, env: I18nFastpathEnv) => Promise<Response>;
  return fetcher(request, env);
}

async function accurateModelEvidence(response: Response, model: string): Promise<Response> {
  if (!response.ok) return response;
  let payload: Record<string, unknown>;
  try { payload = await response.clone().json() as Record<string, unknown>; } catch { return response; }
  if (payload.status !== "ok" || !Array.isArray(payload.models)) return response;
  payload.models = [model];
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("content-type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(payload), { status: response.status, headers });
}

export default {
  async fetch(request: Request, env: I18nFastpathEnv): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && translationPaths.has(pathname)) {
      const adapter = new DedicatedTranslationAdapter(env.AI);
      const adaptedEnv = { ...env, AI: adapter } as I18nFastpathEnv;
      const response = await handleI18nFastpath(request, adaptedEnv, baseFetch);
      return accurateModelEvidence(response, adapter.usedModel);
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
