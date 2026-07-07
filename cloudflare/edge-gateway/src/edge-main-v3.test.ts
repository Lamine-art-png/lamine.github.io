import { afterEach, describe, expect, it, vi } from "vitest";
import edgeMain from "./edge-main-v3";
import type { I18nFastpathEnv } from "./i18n-fastpath-handler";

class FakeAi {
  async run(_model: string, input: { messages?: Array<{ role: string; content: string }> }) {
    const raw = input.messages?.find((item) => item.role === "user")?.content || "{}";
    const source = JSON.parse(raw) as Record<string, string>;
    return { response: JSON.stringify(Object.fromEntries(Object.entries(source).map(([key, value]) => [key, `TR ${value}`]))) };
  }
}

class FailingAi {
  async run(): Promise<never> { throw new Error("simulated_ai_failure"); }
}

function env(ai: unknown = new FakeAi()): I18nFastpathEnv {
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

function requestFor(locale = "so") {
  return new Request("https://api.agroai-pilot.com/v1/i18n/catalog", {
    method: "POST",
    headers: { "content-type": "application/json", origin: "https://app.agroai-pilot.com" },
    body: JSON.stringify({ locale, source: { settings: "Settings", save: "Save" } }),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("edge-main-v3 i18n entrypoint", () => {
  it("preserves browser-readable headers on fastpath success", async () => {
    const response = await edgeMain.fetch(requestFor(), env());
    expect(response.status).toBe(200);
    expect(response.headers.get("access-control-allow-origin")).toBe("https://app.agroai-pilot.com");
    expect(response.headers.get("vary")).toBe("Origin");
  });

  it("preserves browser-readable headers on fastpath errors", async () => {
    const request = new Request("https://api.agroai-pilot.com/v1/i18n/catalog", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "https://app.agroai-pilot.com" },
      body: JSON.stringify({ locale: "el", source: { invalid_key: "nope" } }),
    });
    const response = await edgeMain.fetch(request, env());
    expect(response.status).toBe(409);
    expect(response.headers.get("access-control-allow-origin")).toBe("https://app.agroai-pilot.com");
  });

  it("uses the backend translator when Workers AI fails instead of returning a dead-end 503", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      status: "ok",
      locale: "so",
      catalog: { settings: "Dejinta", save: "Kaydi" },
    }), { status: 200, headers: { "content-type": "application/json" } })));

    const response = await edgeMain.fetch(requestFor(), env(new FailingAi()));
    const body = (await response.json()) as { status?: string; catalog?: Record<string, string> };
    expect(response.status).toBe(200);
    expect(response.headers.get("x-agroai-i18n-fallback")).toBe("upstream-backend");
    expect(body.status).toBe("ok");
    expect(body.catalog?.settings).toBe("Dejinta");
  });
});
