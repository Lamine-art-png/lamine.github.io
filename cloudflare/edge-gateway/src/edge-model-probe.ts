import productionHandler from "./edge-main-v3";
import { type Env as BaseEnv, type ConnectorTaskEnvelope } from "./index";
import { matchesConfiguredToken } from "./queue-policy";
import type { AiRunner } from "./i18n-translation-engine-v3";

interface ProbeEnv extends BaseEnv {
  AI: AiRunner;
}

const CANDIDATES = [
  "@cf/meta/llama-3.1-8b-instruct-fast",
  "@cf/meta/llama-3.2-3b-instruct",
  "@cf/qwen/qwen1.5-14b-chat-awq",
];

function bearer(request: Request): string {
  const value = request.headers.get("authorization") || "";
  return value.toLowerCase().startsWith("bearer ") ? value.slice(7).trim() : "";
}

function textFrom(result: unknown): string {
  if (!result || typeof result !== "object") return "";
  const body = result as Record<string, unknown>;
  if (typeof body.response === "string") return body.response;
  const nested = body.result;
  if (nested && typeof nested === "object" && typeof (nested as Record<string, unknown>).response === "string") {
    return String((nested as Record<string, unknown>).response);
  }
  return "";
}

async function bounded<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error("probe_timeout")), ms);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function runProbe(env: ProbeEnv): Promise<Response> {
  const source = { language: "Language", settings: "Settings", save: "Save", support: "Support" };
  const output: Array<Record<string, unknown>> = [];
  for (const model of CANDIDATES) {
    const started = Date.now();
    try {
      const result = await bounded(env.AI.run(model, {
        messages: [
          { role: "system", content: "Translate every JSON string value from English into Telugu. Return one JSON object only. Preserve every key exactly." },
          { role: "user", content: JSON.stringify(source) },
        ],
        temperature: 0,
        max_tokens: 512,
      }), 20_000);
      output.push({ model, ok: true, elapsed_ms: Date.now() - started, response: textFrom(result).slice(0, 2000) });
    } catch (error) {
      output.push({ model, ok: false, elapsed_ms: Date.now() - started, error: String(error) });
    }
  }
  return new Response(JSON.stringify({ status: "ok", candidates: output }), {
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

export default {
  async fetch(request: Request, env: ProbeEnv, ctx: ExecutionContext): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && pathname === "/v1/i18n/internal/model-probe") {
      if (!matchesConfiguredToken(bearer(request), env.QUEUE_CONSUMER_TOKEN)) {
        return new Response('{"status":"error","error":"unauthorized"}', { status: 401, headers: { "content-type": "application/json" } });
      }
      return runProbe(env);
    }
    const fetcher = productionHandler.fetch as unknown as (request: Request, env: ProbeEnv, ctx: ExecutionContext) => Promise<Response>;
    return fetcher(request, env, ctx);
  },
  async queue(batch: MessageBatch<ConnectorTaskEnvelope>, env: ProbeEnv, ctx: ExecutionContext): Promise<void> {
    const handler = productionHandler.queue as unknown as (batch: MessageBatch<ConnectorTaskEnvelope>, env: ProbeEnv, ctx: ExecutionContext) => Promise<void>;
    await handler(batch, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: ProbeEnv, ctx: ExecutionContext): Promise<void> {
    const handler = productionHandler.scheduled as unknown as (controller: ScheduledController, env: ProbeEnv, ctx: ExecutionContext) => Promise<void>;
    await handler(controller, env, ctx);
  },
} satisfies ExportedHandler<ProbeEnv, ConnectorTaskEnvelope>;
