import { describe, expect, it } from "vitest";
import { configuredOrigins, originAllowed, validTask, validatedUpstreamOrigin } from "../src/index";

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

describe("connector task envelope", () => {
  it("accepts only bounded non-empty identifiers", () => {
    expect(validTask({ job_id: "job-1", tenant_id: "tenant-1", task_type: "connector_provider_sync" })).toBe(true);
    expect(validTask({ job_id: "", tenant_id: "tenant-1", task_type: "sync" })).toBe(false);
    expect(validTask({ job_id: "x".repeat(257), tenant_id: "tenant-1", task_type: "sync" })).toBe(false);
    expect(validTask(null)).toBe(false);
  });
});
