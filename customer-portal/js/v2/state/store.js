import { demoSeedData } from "../data/demoTenant.js";

export const STATUS_FLOW = ["recommended", "scheduled", "applied", "observed", "verified"];

export function createStore() {
  const seed = demoSeedData();
  return {
    session: null,
    authUi: { mode: "login", message: "" },
    filters: { farm: "all", zone: "all", provider: "all", status: "all", range: "7d" },
    app: {
      route: "command_center",
      organizationId: seed.organizations[0].id,
      farmId: seed.farms[0].id,
      zoneId: seed.zones[0].id,
      selectedRecommendationId: seed.recommendations[0].id,
      notifications: [{ id: "n1", text: "3 verifications pending confirmation.", level: "warn" }],
      loading: false,
      error: "",
      success: "",
      integrationsSetup: {
        step: 1,
        provider: "wiseconn",
        state: "disconnected",
      },
      ...seed,
    },
  };
}
