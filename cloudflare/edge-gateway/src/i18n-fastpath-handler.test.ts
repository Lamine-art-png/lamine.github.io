import { describe, expect, it } from "vitest";

import { handleI18nFastpath, type I18nFastpathEnv } from "./i18n-fastpath-handler";

class FakeAi {
  calls = 0;

  async run(_model: string, input: { messages?: Array<{ role: string; content: string }> }) {
    this.calls += 1;
    const sourceText = input.messages?.find((item) => item.role === "user")?.content || "{}";
    const source = JSON.parse(sourceText) as Record<string, string>;
    return {
      response: JSON.stringify(Object.fromEntries(
        Object.entries(source).map(([key, value]) => [key, `TR ${value}`]),
      )),
    };
  }
}

function env(ai: FakeAi): I18nFastpathEnv {
  return {
    AI: ai,
    UPSTREAM_API_ORIGIN: "https://upstream.example.com",
    EDGE_ENVIRONMENT: "test",
    ALLOWED_ORIGINS: "https://app.agroai-pilot.com",
    QUEUE_PUBLISH_TOKEN: "publish",
    QUEUE_CONSUMER_TOKEN: "consumer",
    CONNECTOR_TASKS: { send: async () => undefined },
  } as unknown as I18nFastpathEnv;
}

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("local-validation i18n fastpath", () => {
  it("validates canonical catalog source locally before Workers AI without backend round trips", async () => {
    const ai = new FakeAi();
    const calls: Array<{ method: string; path: string; auth: string; body: unknown }> = [];
    const baseFetch = async <Host, Cf>(request: Request<Host, Cf>): Promise<Response> => {
      const url = new URL(request.url);
      const body = request.method === "POST" ? await request.clone().json() : null;
      calls.push({
        method: request.method,
        path: url.pathname,
        auth: request.headers.get("authorization") || "",
        body,
      });
      throw new Error(`unexpected backend call ${request.method} ${url.pathname}`);
    };

    const request = new Request("https://app.agroai-pilot.com/v1/i18n/catalog", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer user-token" },
      body: JSON.stringify({ locale: "de", source: { settings: "Settings", save: "Save" } }),
    });
    const response = await handleI18nFastpath(request, env(ai), baseFetch);
    const body = await response.json() as { source?: string; locale?: string; catalog?: Record<string, string> };

    expect(response.status).toBe(200);
    expect(body.locale).toBe("de");
    expect(body.source).toBe("cloudflare_workers_ai");
    expect(body.catalog?.settings).toBe("TR Settings");
    expect(ai.calls).toBe(1);
    expect(calls).toHaveLength(0);
  });

  it("runs authorized internal canary directly after local registry validation without backend generation", async () => {
    const ai = new FakeAi();
    const calls: string[] = [];
    const baseFetch = async <Host, Cf>(request: Request<Host, Cf>): Promise<Response> => {
      calls.push(`${request.method} ${new URL(request.url).pathname}`);
      throw new Error("backend generation must not run for authorized canary");
    };

    const request = new Request("https://app.agroai-pilot.com/v1/i18n/internal/canary", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer consumer" },
      body: JSON.stringify({ locale: "ja" }),
    });
    const response = await handleI18nFastpath(request, env(ai), baseFetch);
    const body = await response.json() as { status?: string; locale?: string; changed_count?: number; providers?: string[] };

    expect(response.status).toBe(200);
    expect(body.status).toBe("ok");
    expect(body.locale).toBe("ja");
    expect(body.changed_count).toBeGreaterThanOrEqual(2);
    expect(body.providers).toEqual(["cloudflare_workers_ai"]);
    expect(calls).toEqual([]);
    expect(ai.calls).toBe(1);
  });

  it("never bypasses backend authorization for an unauthorized internal canary", async () => {
    const ai = new FakeAi();
    let postCalls = 0;
    const baseFetch = async <Host, Cf>(request: Request<Host, Cf>): Promise<Response> => {
      const url = new URL(request.url);
      if (request.method === "GET") {
        return json({ status: "ok", languages: [{ code: "ja", name: "Japanese" }] });
      }
      postCalls += 1;
      expect(url.pathname).toBe("/v1/i18n/internal/canary");
      return json({ detail: { code: "invalid_internal_canary_token" } }, 401);
    };

    const request = new Request("https://app.agroai-pilot.com/v1/i18n/internal/canary", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer wrong" },
      body: JSON.stringify({ locale: "ja" }),
    });
    const response = await handleI18nFastpath(request, env(ai), baseFetch);

    expect(response.status).toBe(401);
    expect(postCalls).toBe(1);
    expect(ai.calls).toBe(0);
  });
});
