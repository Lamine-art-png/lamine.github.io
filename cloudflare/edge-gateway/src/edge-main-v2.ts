import baseHandler, { type ConnectorTaskEnvelope } from "./index";
import { handleI18nFastpath, type I18nFastpathEnv } from "./i18n-fastpath-handler";

const translationPaths = new Set(["/v1/i18n/catalog", "/v1/i18n/internal/canary"]);

async function baseFetch(request: Request, env: I18nFastpathEnv): Promise<Response> {
  const fetcher = baseHandler.fetch as unknown as (request: Request, env: I18nFastpathEnv) => Promise<Response>;
  return fetcher(request, env);
}

export default {
  async fetch(request: Request, env: I18nFastpathEnv): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && translationPaths.has(pathname)) {
      return handleI18nFastpath(request, env, baseFetch);
    }
    return baseFetch(request, env);
  },
  async queue(batch: MessageBatch<ConnectorTaskEnvelope>, env: I18nFastpathEnv): Promise<void> {
    await baseHandler.queue(batch, env);
  },
  async scheduled(controller: ScheduledController, env: I18nFastpathEnv, ctx: ExecutionContext): Promise<void> {
    await baseHandler.scheduled(controller, env, ctx);
  },
};
