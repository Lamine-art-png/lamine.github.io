export const ENDPOINTS = {
  controllerEnvironments: "/v1/controllers/environments",
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
  workbenchSessions: "/v1/workbench/sessions",
  workbenchSamplePackage: "/v1/workbench/sample-package",
  workbenchSession: (id) => `/v1/workbench/sessions/${encodeURIComponent(id)}` ,
  workbenchUpload: (id) => `/v1/workbench/sessions/${encodeURIComponent(id)}/upload`,
  workbenchAnalyze: (id) => `/v1/workbench/sessions/${encodeURIComponent(id)}/analyze`,
  workbenchLiveAnalyze: "/v1/workbench/analyze-live",
  workbenchReport: (id) => `/v1/workbench/sessions/${encodeURIComponent(id)}/report`,
  workbenchSchema: "/v1/workbench/schema",
  earthdailyStatus: "/api/v1/partners/earthdaily/status",
  earthdailyEndToEnd: "/api/v1/partners/earthdaily/end-to-end",
  earthdailySampleField: "/api/v1/demo/earthdaily/sample-field",
  earthdailySampleResponse: "/api/v1/demo/earthdaily/sample-response",
  earthdailyDecision: (id) => `/api/v1/decisions/${encodeURIComponent(id)}`,
  earthdailyAudit: (id) => `/api/v1/decisions/${encodeURIComponent(id)}/audit`,
};

export class ApiClient {
  constructor(baseUrl = window.AGROAI_PORTAL_CONFIG?.apiBase || "https://api.agroai-pilot.com") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.edgeBaseUrl = (window.AGROAI_PORTAL_CONFIG?.edgeApiBase || this.baseUrl).replace(/\/$/, "");
  }

  async request(path, options = {}, baseUrl = this.baseUrl) {
    try {
      const response = await fetch(`${baseUrl}${path}`, {
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

  getControllerEnvironments() {
    return this.request(ENDPOINTS.controllerEnvironments);
  }

  getFarms() {
    return this.request(ENDPOINTS.farms);
  }

  getTalgilAuth() {
    return this.request(ENDPOINTS.talgilAuth);
  }

  getTalgilFarms() {
    return this.request(ENDPOINTS.talgilFarms);
  }

  getTalgilZones(farmId) {
    return this.request(ENDPOINTS.talgilZonesByFarm(farmId));
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

  requestEdge(path, options = {}) {
    return this.request(path, options, this.edgeBaseUrl);
  }

  getEarthDailyStatus() {
    return this.requestEdge(ENDPOINTS.earthdailyStatus);
  }

  runEarthDailyEndToEnd() {
    return this.requestEdge(ENDPOINTS.earthdailyEndToEnd, { method: "POST", body: {} });
  }

  getEarthDailySampleField() {
    return this.requestEdge(ENDPOINTS.earthdailySampleField);
  }

  getEarthDailySampleResponse() {
    return this.requestEdge(ENDPOINTS.earthdailySampleResponse);
  }

  getEarthDailyDecision(id) {
    return this.requestEdge(ENDPOINTS.earthdailyDecision(id));
  }

  getEarthDailyAudit(id) {
    return this.requestEdge(ENDPOINTS.earthdailyAudit(id));
  }
}


ApiClient.prototype.createWorkbenchSession = function(payload={mode:"uploaded"}) { return this.request(ENDPOINTS.workbenchSessions,{method:"POST", body: payload}); };
ApiClient.prototype.uploadWorkbenchFile = async function(sessionId, file) { const form = new FormData(); form.append("file", file); const res = await fetch(`${this.baseUrl}${ENDPOINTS.workbenchUpload(sessionId)}`, { method:"POST", body: form }); const data = await res.json(); return { ok: res.ok, status: res.status, data, error: res.ok ? null : (data?.detail || "Upload failed")}; };
ApiClient.prototype.createSampleWorkbenchSession = function(){ return this.request(ENDPOINTS.workbenchSamplePackage, {method:"POST"}); };
ApiClient.prototype.analyzeWorkbenchSession = function(sessionId, payload){ return this.request(ENDPOINTS.workbenchAnalyze(sessionId), {method:"POST", body: payload}); };
ApiClient.prototype.analyzeLiveWorkbench = function(payload){ return this.request(ENDPOINTS.workbenchLiveAnalyze, {method:"POST", body: payload}); };
ApiClient.prototype.getWorkbenchSession = function(sessionId){ return this.request(ENDPOINTS.workbenchSession(sessionId)); };
ApiClient.prototype.getWorkbenchReport = function(sessionId){ return this.request(ENDPOINTS.workbenchReport(sessionId)); };
ApiClient.prototype.getWorkbenchSchema = function(){ return this.request(ENDPOINTS.workbenchSchema); };
