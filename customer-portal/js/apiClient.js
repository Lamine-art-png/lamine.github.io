export const ENDPOINTS = {
  auth: "/v1/wiseconn/auth",
  farms: "/v1/wiseconn/farms",
  zonesByFarm: (farmId) => `/v1/wiseconn/farms/${encodeURIComponent(farmId)}/zones`,
  irrigationsByZone: (zoneId, days = 14) => `/v1/wiseconn/zones/${encodeURIComponent(zoneId)}/irrigations?days=${encodeURIComponent(days)}`,
  blockWaterState: (blockId) => `/v1/decisioning/blocks/${encodeURIComponent(blockId)}/water-state`,
  blockWaterStateHistory: (blockId, limit = 24) =>
    `/v1/decisioning/blocks/${encodeURIComponent(blockId)}/water-state/history?limit=${encodeURIComponent(limit)}`,
  blockDecisions: (blockId, limit = 20) => `/v1/execution/blocks/${encodeURIComponent(blockId)}/decisions?limit=${encodeURIComponent(limit)}`,
  blockVerifications: (blockId, limit = 20) =>
    `/v1/execution/blocks/${encodeURIComponent(blockId)}/verifications?limit=${encodeURIComponent(limit)}`,
  reportRoi: ({ from, to, blockId }) =>
    `/v1/reports/roi?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}${
      blockId ? `&blockId=${encodeURIComponent(blockId)}` : ""
    }`,
  liveWiseConnRecommendation: (zoneId) => `/v1/intelligence/recommend/live/wiseconn/${encodeURIComponent(zoneId)}`,
  talgilStatus: "/v1/integrations/talgil/status",
  talgilSensorsLatest: "/v1/integrations/talgil/sensors/latest",
  talgilAudit: "/v1/integrations/talgil/audit",
};

export class ApiClient {
  constructor(baseUrl = window.AGROAI_PORTAL_CONFIG?.apiBase || "https://api.agroai-pilot.com") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async request(path, options = {}) {
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: options.method || "GET",
        headers: {
          Accept: "application/json",
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...(options.headers || {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
      const contentType = response.headers.get("content-type") || "";
      let payload = null;

      if (contentType.includes("application/json")) {
        payload = await response.json();
      }

      if (!response.ok) {
        return {
          ok: false,
          status: response.status,
          error: payload?.detail || payload?.message || `HTTP ${response.status}`,
          data: payload,
        };
      }

      return {
        ok: true,
        status: response.status,
        data: payload,
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        error: error?.message || "Network request failed",
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

  getTalgilStatus() {
    return this.request(ENDPOINTS.talgilStatus);
  }

  getTalgilSensorsLatest() {
    return this.request(ENDPOINTS.talgilSensorsLatest);
  }

  getTalgilAudit() {
    return this.request(ENDPOINTS.talgilAudit);
  }

  recommendLiveWiseConn(zoneId, overrides = {}) {
    return this.request(ENDPOINTS.liveWiseConnRecommendation(zoneId), {
      method: "POST",
      body: overrides,
    });
  }
}
