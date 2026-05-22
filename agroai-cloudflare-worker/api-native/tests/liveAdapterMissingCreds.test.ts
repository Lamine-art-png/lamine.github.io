import { describe, expect, it } from "vitest";
import { handleEarthDailyStatus } from "../src/api/routes/earthdailyStatus";

describe("live adapter missing credentials", () => {
  it("reports live_ready=false without throwing", () => {
    const status = handleEarthDailyStatus({ LIVE_EARTHDAILY_ENABLED: "true", DEMO_MODE: "true" });
    expect(status.credentials_configured).toBe(false);
    expect(status.live_enabled).toBe(true);
    expect(status.live_ready).toBe(false);
    expect(status.reason).toContain("credentials");
  });
});

