export const ENDPOINTS = {
  auth: "/v1/wiseconn/auth",
  farms: "/v1/wiseconn/farms",
  zonesByFarm: (farmId) => `/v1/wiseconn/farms/${farmId}/zones`,
  irrigationsByZone: (zoneId, days = 14) => `/v1/wiseconn/zones/${zoneId}/irrigations?days=${days}`,
  blockWaterState: (blockId) => `/v1/decisioning/blocks/${blockId}/water-state`,
  blockWaterStateHistory: (blockId, limit = 24) =>
    `/v1/decisioning/blocks/${blockId}/water-state/history?limit=${limit}`,
  blockDecisions: (blockId, limit = 20) => `/v1/execution/blocks/${blockId}/decisions?limit=${limit}`,
  blockVerifications: (blockId, limit = 20) =>
    `/v1/execution/blocks/${blockId}/verifications?limit=${limit}`,
  reportRoi: ({ from, to, blockId }) =>
    `/v1/reports/roi?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}${
      blockId ? `&blockId=${encodeURIComponent(blockId)}` : ""
    }`,
};

export class ApiClient {
  constructor(baseUrl = window.AGROAI_PORTAL_CONFIG?.apiBase || "https://api.agroai-pilot.com") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async request(path) {
    try {
      const response = await fetch(`${this.baseUrl}${path}`);
      const contentType = response.headers.get("content-type") || "";
      let payload = null;

      if (contentType.includes("application/json")) {
        payload = await response.json();
      }

      if (!response.ok) {
        return {
          ok: false,
          status: response.status,
          error: payload?.detail || `HTTP ${response.status}`,
          data: payload,
        };
      }

      return {
        ok: true,
        status: response.status,
        error: null,
        data: payload,
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        error: error instanceof Error ? error.message : "Network request failed",
        data: null,
      };
    }
  }

  getAuth() {
    return this.request(ENDPOINTS.auth);
  }

  getFarms() {
    return this.request(ENDPOINTS.farms);
  }

  getZones(farmId) {
    return this.request(ENDPOINTS.zonesByFarm(farmId));
  }

  getIrrigations(zoneId, days = 14) {
    return this.request(ENDPOINTS.irrigationsByZone(zoneId, days));
  }

  getWaterState(blockId) {
    return this.request(ENDPOINTS.blockWaterState(blockId));
  }

  getWaterStateHistory(blockId, limit = 24) {
    return this.request(ENDPOINTS.blockWaterStateHistory(blockId, limit));
  }

  getDecisionRuns(blockId, limit = 20) {
    return this.request(ENDPOINTS.blockDecisions(blockId, limit));
  }

  getVerifications(blockId, limit = 20) {
    return this.request(ENDPOINTS.blockVerifications(blockId, limit));
  }

  getRoiReport(params) {
    return this.request(ENDPOINTS.reportRoi(params));
  }
}
