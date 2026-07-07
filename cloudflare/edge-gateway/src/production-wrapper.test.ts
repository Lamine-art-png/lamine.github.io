import { describe, expect, it } from "vitest";

import wrapper from "./production-wrapper";

class FakeAi {
  calls = 0;

  async run(_model: string, input: { messages?: Array<{ role: string; content: string }> }) {
    this.calls += 1;
    const user = input.messages?.find((item) => item.role === "user")?.content || "{}";
    const source = JSON.parse(user) as Record<string, string>;
    const translated = Object.fromEntries(Object.entries(source).map(([key, value]) => [key, `TR ${value}`]));
    return { response: JSON.stringify(translated) };
  }
}

function env(ai: FakeAi) {
  return {
    AI: ai,
    UPSTREAM_API_ORIGIN: "https://upstream.example.com",
    EDGE_ENVIRONMENT: "test",
    ALLOWED_ORIGINS: "https://app.agroai-pilot.com",
    QUEUE_PUBLISH_TOKEN: "publish",
    QUEUE_CONSUMER_TOKEN: "consumer",
    CONNECTOR_TASKS: { send: async () => undefined },
  } as never;
}

describe("production i18n wrapper", () => {
  it("falls back to Workers AI only after canonical backend generation failure", async () => {
    const ai = new FakeAi();
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify({
      detail: { code: "ui_catalog_generation_unavailable", locale: "de" },
    }), { status: 503, headers: { "content-type": "application/json" } });

    try {
      const request = new Request("https://app.agroai-pilot.com/v1/i18n/catalog", {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer user" },
        body: JSON.stringify({ locale: "de", source: { settings: "Settings", save: "Save" } }),
      });
      const response = await wrapper.fetch(request, env(ai), {} as ExecutionContext);
      const body = await response.json() as Record<string, unknown>;
      expect(response.status).toBe(200);
      expect(body.source).toBe("cloudflare_workers_ai");
      expect((body.catalog as Record<string, string>).settings).toBe("TR Settings");
      expect(ai.calls).toBe(1);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("does not bypass non-generation backend failures", async () => {
    const ai = new FakeAi();
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });

    try {
      const request = new Request("https://app.agroai-pilot.com/v1/i18n/catalog", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ locale: "de", source: { settings: "Settings" } }),
      });
      const response = await wrapper.fetch(request, env(ai), {} as ExecutionContext);
      expect(response.status).toBe(401);
      expect(ai.calls).toBe(0);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
