import { describe, expect, it } from "vitest";
import { configuredOrigins, originAllowed, requestId, upstreamRequest, validTask, validatedUpstreamOrigin } from "../src/index";

describe("edge origin policy", () => {
  it("allows exact production origins and approved Pages projects", () => {
    const env = { ALLOWED_ORIGINS: "https://extra.agroai-pilot.com" };
    expect(configuredOrigins(env).has("https://app.agroai-pilot.com")).toBe(true);
    expect(originAllowed("https://extra.agroai-pilot.com", env)).toBe(true);
    expect(originAllowed("https://agroai-portal.pages.dev", env)).toBe(true);
    expect(originAllowed("https://preview.agroai-command-center-v2-preview.pages.dev", env)).toBe(true);
  });

  it("rejects lookalike and arbitrary origins", () => {
    const env = { ALLOWED_ORIGINS: "" };
    expect(originAllowed("https://app.agroai-pilot.com.evil.test", env)).toBe(false);
    expect(originAllowed("https://random.pages.dev", env)).toBe(false);
    expect(originAllowed(null, env)).toBe(false);
  });
});

describe("upstream safety", () => {
  it("requires a clean HTTPS origin", () => {
    expect(validatedUpstreamOrigin("https://api-preview.agroai-pilot.com").origin).toBe("https://api-preview.agroai-pilot.com");
    expect(() => validatedUpstreamOrigin("http://backend.invalid")).toThrow(/HTTPS/);
    expect(() => validatedUpstreamOrigin("https://user:pass@backend.invalid")).toThrow(/clean origin/);
  });

  it("rejects recursive gateway routing", () => {
    expect(() => validatedUpstreamOrigin("https://api.agroai-pilot.com", new URL("https://api.agroai-pilot.com/v1/health"))).toThrow(/cannot point back/);
  });
});

describe("request identifiers", () => {
  it("preserves bounded safe identifiers and rejects unsafe values", () => {
    expect(requestId(new Request("https://api.agroai-pilot.com/v1/health", { headers: { "x-request-id": "req-safe_123" } }))).toBe("req-safe_123");
    const unsafe = requestId(new Request("https://api.agroai-pilot.com/v1/health", { headers: { "x-request-id": "bad value" } }));
    expect(unsafe).not.toBe("bad value");
    expect(unsafe.length).toBeLessThanOrEqual(128);
    const oversized = requestId(new Request("https://api.agroai-pilot.com/v1/health", { headers: { "x-request-id": "x".repeat(300) } }));
    expect(oversized).not.toBe("x".repeat(300));
  });
});

describe("authoritative client IP forwarding", () => {
  it("replaces spoofed forwarding headers with Cloudflare-authenticated context", async () => {
    const request = new Request("https://api.agroai-pilot.com/v1/platform/me", {
      headers: {
        "cf-connecting-ip": "2001:db8::42",
        "x-forwarded-for": "127.0.0.1",
        "x-agroai-edge-client-ip": "10.0.0.1",
        "x-agroai-edge-auth": "attacker",
      },
    });
    const upstream = upstreamRequest(
      request,
      new URL("https://api-preview.agroai-pilot.com"),
      "req-1",
      { EDGE_ORIGIN_AUTH_TOKEN: "edge-shared-secret" },
    );

    expect(upstream.headers.get("x-agroai-edge-client-ip")).toBe("2001:db8::42");
    expect(upstream.headers.get("x-agroai-edge-auth")).toBe("edge-shared-secret");
    expect(upstream.headers.get("x-forwarded-for")).toBeNull();
    expect(upstream.headers.get("cf-connecting-ip")).toBeNull();
  });

  it("omits client identity when the edge-to-origin secret is absent", () => {
    const upstream = upstreamRequest(
      new Request("https://api.agroai-pilot.com/v1/platform/me", {
        headers: {
          "cf-connecting-ip": "203.0.113.8",
          "x-forwarded-for": "198.51.100.99",
          "x-agroai-edge-client-ip": "198.51.100.99",
          "x-agroai-edge-auth": "attacker",
        },
      }),
      new URL("https://api-preview.agroai-pilot.com"),
      "req-2",
      {},
    );
    expect(upstream.headers.get("x-agroai-edge-client-ip")).toBeNull();
    expect(upstream.headers.get("x-agroai-edge-auth")).toBeNull();
    expect(upstream.headers.get("x-forwarded-for")).toBeNull();
    expect(upstream.headers.get("cf-connecting-ip")).toBeNull();
  });
});

describe("connector task envelope", () => {
  it("accepts only bounded known connector task contracts", () => {
    expect(validTask({ job_id: "job-1", tenant_id: "tenant-1", task_type: "connector_provider_sync" })).toBe(true);
    expect(validTask({ job_id: "job-2", tenant_id: "tenant-1", task_type: "connector_ingest_object" })).toBe(true);
    expect(validTask({ job_id: "outbox-1", tenant_id: "tenant-1", task_type: "platform_webhook_delivery" })).toBe(true);
    expect(validTask({ job_id: "", tenant_id: "tenant-1", task_type: "connector_provider_sync" })).toBe(false);
    expect(validTask({ job_id: "x".repeat(257), tenant_id: "tenant-1", task_type: "connector_provider_sync" })).toBe(false);
    expect(validTask({ job_id: "job-3", tenant_id: "tenant-1", task_type: "unknown_task" })).toBe(false);
    expect(validTask(null)).toBe(false);
  });
});
