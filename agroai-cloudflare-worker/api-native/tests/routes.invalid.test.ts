import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";

const env = {
  DB: undefined,
  ADMIN_TOKEN: "admin",
  TALGIL_API_KEY: "unused",
  TALGIL_BASE_URL: "unused",
  TALGIL_SYNC: {},
  DEMO_MODE: "true",
  LIVE_EARTHDAILY_ENABLED: "false",
  EDS_TOKEN_CACHE: { get: async () => null, put: async () => undefined },
} as never;

describe("EarthDaily routes invalid requests", () => {
  it("returns 400 on bad JSON", async () => {
    const res = await worker.fetch(new Request("https://worker.test/api/v1/partners/earthdaily/normalize", { method: "POST", body: "{" }), env);
    const body = await res.json() as { ok: boolean; error: { code: string } };
    expect(res.status).toBe(400);
    expect(body.ok).toBe(false);
    expect(body.error.code).toBe("invalid_json");
  });

  it("returns 400 on unknown provider", async () => {
    const raw = { ...buildDemoEarthDailyInput(), provider: "bad-provider" };
    const res = await worker.fetch(new Request("https://worker.test/api/v1/partners/earthdaily/normalize", { method: "POST", body: JSON.stringify(raw) }), env);
    const body = await res.json() as { ok: boolean; error: { code: string } };
    expect(res.status).toBe(400);
    expect(body.ok).toBe(false);
    expect(body.error.code).toBe("unsupported_provider");
  });

  it("returns 413 on payloads over 256KB", async () => {
    const payload = JSON.stringify({ blob: "x".repeat(300_000) });
    const res = await worker.fetch(new Request("https://worker.test/api/v1/partners/earthdaily/normalize", { method: "POST", body: payload }), env);
    const body = await res.json() as { ok: boolean; error: { code: string } };
    expect(res.status).toBe(413);
    expect(body.ok).toBe(false);
    expect(body.error.code).toBe("payload_too_large");
  });
});

