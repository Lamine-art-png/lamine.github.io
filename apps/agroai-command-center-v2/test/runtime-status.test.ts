import { describe, expect, it } from "vitest";
import { mapTalgilStatus, mapWiseConnStatus } from "../src/api/runtimeStatus";

const checkedAt = "2026-06-01T12:00:00.000Z";

describe("provider-specific runtime status mapping", () => {
  it("maps readable WiseConn farms or zones to Live", () => {
    const status = mapWiseConnStatus({ ok: true, data: { authenticated: true, farms: 2, zones: 14 } }, undefined, checkedAt);
    expect(status.connectionState).toBe("Live");
    expect(status.farms).toBe(2);
    expect(status.zones).toBe(14);
  });

  it("maps configured WiseConn with degraded reads to Limited", () => {
    const status = mapWiseConnStatus({ ok: true, data: { authenticated: true, status: "degraded" } }, undefined, checkedAt);
    expect(status.connectionState).toBe("Limited");
    expect(status.farms).toBeNull();
  });

  it("maps unconfigured WiseConn to Setup required", () => {
    const status = mapWiseConnStatus({ ok: true, data: { authenticated: false, configured: false } }, undefined, checkedAt);
    expect(status.connectionState).toBe("Setup required");
  });

  it("maps WiseConn request failure to Unavailable", () => {
    const status = mapWiseConnStatus({ ok: false, data: null, error: "Network error" }, undefined, checkedAt);
    expect(status.connectionState).toBe("Unavailable");
  });

  it("maps live Talgil with selected targets to Live", () => {
    const status = mapTalgilStatus({ ok: true, data: { configured: true, live: true, targets: 3 } }, undefined, checkedAt);
    expect(status.connectionState).toBe("Live");
    expect(status.targets).toBe(3);
  });

  it("maps configured Talgil with no targets to Target selection required", () => {
    const status = mapTalgilStatus({ ok: true, data: { configured: true, live: false, targets: 0 } }, undefined, checkedAt);
    expect(status.connectionState).toBe("Target selection required");
  });

  it("maps degraded Talgil runtime reads to Limited", () => {
    const status = mapTalgilStatus({ ok: true, data: { configured: true, live: true, targets: 2, status: "degraded" } }, undefined, checkedAt);
    expect(status.connectionState).toBe("Limited");
  });

  it("maps unconfigured Talgil to Setup required", () => {
    const status = mapTalgilStatus({ ok: true, data: { configured: false, live: false } }, undefined, checkedAt);
    expect(status.connectionState).toBe("Setup required");
  });

  it("maps Talgil request failure to Unavailable", () => {
    const status = mapTalgilStatus({ ok: false, data: null, error: "HTTP 503" }, undefined, checkedAt);
    expect(status.connectionState).toBe("Unavailable");
  });
});
