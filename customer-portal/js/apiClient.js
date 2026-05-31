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
  complianceStatus: "/v1/compliance/status",
  complianceReadiness: "/v1/compliance/readiness",
  complianceWaterBudgets: "/v1/compliance/water-budgets",
  complianceReconciliation: "/v1/compliance/reconciliation",
  complianceMeters: "/v1/compliance/assets/meters",
  complianceExports: "/v1/compliance/exports",
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
        credentials: options.credentials || "include",
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

  createWorkbenchSession(payload = { mode: "uploaded" }) {
    return this.request(ENDPOINTS.workbenchSessions, { method: "POST", body: payload });
  }

  async uploadWorkbenchFile(sessionId, file) {
    if (!sessionId) {
      return { ok: false, status: 0, data: null, error: "Workbench session required for upload" };
    }
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(`${this.baseUrl}${ENDPOINTS.workbenchUpload(sessionId)}`, {
        method: "POST",
        body: form,
      });
      const text = await response.text();
      let payload = null;
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch (_error) {
          payload = { message: text };
        }
      }
      return {
        ok: response.ok,
        status: response.status,
        data: payload,
        error: response.ok ? null : payload?.detail || payload?.message || `HTTP ${response.status}`,
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: null,
        error: error?.message || "Upload request failed",
      };
    }
  }

  createSampleWorkbenchSession() {
    return this.request(ENDPOINTS.workbenchSamplePackage, { method: "POST" });
  }

  analyzeWorkbenchSession(sessionId, payload = {}) {
    return this.request(ENDPOINTS.workbenchAnalyze(sessionId), { method: "POST", body: payload });
  }

  analyzeLiveWorkbench(payload) {
    return this.request(ENDPOINTS.workbenchLiveAnalyze, { method: "POST", body: payload });
  }

  getWorkbenchSession(sessionId) {
    return this.request(ENDPOINTS.workbenchSession(sessionId));
  }

  getWorkbenchReport(sessionId) {
    return this.request(ENDPOINTS.workbenchReport(sessionId));
  }

  getWorkbenchSchema() {
    return this.request(ENDPOINTS.workbenchSchema);
  }

  getComplianceStatus() {
    return this.request(ENDPOINTS.complianceStatus, { headers: this.complianceHeaders() });
  }

  getComplianceReadiness(workflowType = "gears_groundwater_extractor_readiness") {
    return this.request(`${ENDPOINTS.complianceReadiness}?workflow_type=${encodeURIComponent(workflowType)}`, { headers: this.complianceHeaders() });
  }

  createComplianceExport(exportType = "json", workflowType = "gears_groundwater_extractor_readiness") {
    return this.request(ENDPOINTS.complianceExports, { method: "POST", headers: this.complianceHeaders(), body: { export_type: exportType, workflow_type: workflowType } });
  }

  complianceHeaders() {
    const headers = {};
    const demoToken = window.AGROAI_PORTAL_CONFIG?.nonProductionComplianceDemoToken;
    const orgId = window.AGROAI_PORTAL_CONFIG?.complianceOrganizationId || "org-ca-vineyard-001";
    if (demoToken) {
      headers["X-Compliance-Demo-Token"] = demoToken;
      headers["X-Organization-Id"] = orgId;
    }
    return headers;
  }
}
