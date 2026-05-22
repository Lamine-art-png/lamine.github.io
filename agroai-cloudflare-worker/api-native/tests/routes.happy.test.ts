import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";

function createEnv() {
  const decisions = new Map<string, string>();
  const audits: Array<Record<string, unknown>> = [];
  const db = {
    prepare(sql: string) {
      const state = { binds: [] as unknown[] };
      return {
        bind(...args: unknown[]) {
          state.binds = args;
          return this;
        },
        async run() {
          if (sql.includes("INSERT INTO earthdaily_decisions")) decisions.set(String(state.binds[0]), String(state.binds[10]));
          if (sql.includes("INSERT INTO earthdaily_audit")) {
            audits.push({
              audit_id: state.binds[0],
              decision_id: state.binds[1],
              step: state.binds[2],
              status: state.binds[3],
              duration_ms: state.binds[4],
              request_id: state.binds[5],
              meta_json: state.binds[6],
              created_at: state.binds[7],
            });
          }
          return {};
        },
        async first<T>() {
          if (sql.includes("SELECT decision_json")) {
            const decision_json = decisions.get(String(state.binds[0]));
            return (decision_json ? { decision_json } : null) as T | null;
          }
          return null as T | null;
        },
        async all() {
          if (sql.includes("FROM earthdaily_audit")) {
            return { results: audits.filter((row) => row.decision_id === state.binds[0]) };
          }
          return { results: [] };
        },
      };
    },
  };
  return {
    DB: db,
    ADMIN_TOKEN: "admin",
    TALGIL_API_KEY: "unused",
    TALGIL_BASE_URL: "unused",
    TALGIL_SYNC: {},
    DEMO_MODE: "true",
    LIVE_EARTHDAILY_ENABLED: "false",
    AGROAI_ENV: "test",
    AGROAI_API_VERSION: "v1",
    ALLOWED_ORIGINS: "http://localhost:4173",
    EDS_TOKEN_CACHE: { get: async () => null, put: async () => undefined },
  } as never;
}

async function json(path: string, init?: RequestInit) {
  const res = await worker.fetch(new Request(`https://worker.test${path}`, init), createEnv());
  return { res, body: await res.json() as Record<string, unknown> };
}

describe("EarthDaily routes happy path", () => {
  it("returns 200 and envelope shape for all primary endpoints", async () => {
    const health = await json("/health");
    expect(health.res.status).toBe(200);
    expect(health.body.ok).toBe(true);
    expect(health.body.status).toBe("ok");

    for (const path of ["/api/v1/partners/earthdaily/status", "/api/v1/demo/earthdaily/sample-field", "/api/v1/demo/earthdaily/sample-response"]) {
      const out = await json(path);
      expect(out.res.status).toBe(200);
      expect(out.body.ok).toBe(true);
      expect(out.body.request_id).toBeTruthy();
    }

    const raw = buildDemoEarthDailyInput();
    const normalize = await json("/api/v1/partners/earthdaily/normalize", { method: "POST", body: JSON.stringify(raw) });
    expect(normalize.res.status).toBe(200);
    expect(normalize.body.ok).toBe(true);

    const decision = await json("/api/v1/partners/earthdaily/decision", { method: "POST", body: JSON.stringify(raw) });
    expect(decision.res.status).toBe(200);
    expect(decision.body.ok).toBe(true);

    const report = await json("/api/v1/partners/earthdaily/report", {
      method: "POST",
      body: JSON.stringify({ decision_output: (decision.body.data as { decision_id: string }) }),
    });
    expect(report.res.status).toBe(200);
    expect(report.body.ok).toBe(true);

    const env = createEnv();
    const e2eRes = await worker.fetch(new Request("https://worker.test/api/v1/partners/earthdaily/end-to-end", { method: "POST", body: "{}" }), env);
    const e2e = await e2eRes.json() as { ok: boolean; data: { decision_output: { decision_id: string } } };
    expect(e2eRes.status).toBe(200);
    expect(e2e.ok).toBe(true);
    const id = e2e.data.decision_output.decision_id;

    const readRes = await worker.fetch(new Request(`https://worker.test/api/v1/decisions/${encodeURIComponent(id)}`), env);
    const read = await readRes.json() as { ok: boolean };
    expect(readRes.status).toBe(200);
    expect(read.ok).toBe(true);

    const auditRes = await worker.fetch(new Request(`https://worker.test/api/v1/decisions/${encodeURIComponent(id)}/audit`), env);
    const audit = await auditRes.json() as { ok: boolean; data: { entries: unknown[] } };
    expect(auditRes.status).toBe(200);
    expect(audit.ok).toBe(true);
    expect(audit.data.entries.length).toBeGreaterThan(0);
  });
});

