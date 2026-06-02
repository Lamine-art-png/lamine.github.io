import type {
  ApiResult,
  EvidenceActionResponse,
  EvidenceChainResponse,
  WorkbenchAnalysisResult,
  WorkbenchArtifact,
  WorkbenchSchemaResponse,
} from "./contracts";

// Production API base. Not switched in this PR.
export const API_BASE =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  (import.meta.env?.VITE_AGROAI_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "https://api.agroai-pilot.com";

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: init?.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
      body: init?.body,
      // Degrade quickly to the truthful fallback if the backend is slow/unreachable.
      signal: init?.signal ?? AbortSignal.timeout(8000),
    });
    const ct = res.headers.get("content-type") ?? "";
    const data = ct.includes("application/json") ? ((await res.json()) as T) : null;
    if (!res.ok) {
      return { ok: false, status: res.status, data, error: `HTTP ${res.status}` };
    }
    return { ok: true, status: res.status, data };
  } catch (error) {
    return { ok: false, status: 0, data: null, error: error instanceof Error ? error.message : "Network error" };
  }
}

export const ENDPOINTS = {
  schema: "/v1/workbench/schema",
  openapi: "/openapi.json",
  sessions: "/v1/workbench/sessions",
  samplePackage: "/v1/workbench/sample-package",
  upload: (id: string) => `/v1/workbench/sessions/${encodeURIComponent(id)}/upload`,
  analyze: (id: string) => `/v1/workbench/sessions/${encodeURIComponent(id)}/analyze`,
  analyzeLive: "/v1/workbench/analyze-live",
  report: (id: string) => `/v1/workbench/sessions/${encodeURIComponent(id)}/report`,
  controllerEnvironments: "/v1/controllers/environments",
  wiseconnAuth: "/v1/wiseconn/auth",
  talgilStatus: "/v1/talgil/status",
  evidenceChain: (id: string) => `/v1/workbench/sessions/${encodeURIComponent(id)}/evidence-chain`,
  evidenceAction: (id: string, action: "schedule" | "applied" | "observe" | "verify") =>
    `/v1/workbench/sessions/${encodeURIComponent(id)}/actions/${action}`,
} as const;

export const apiClient = {
  getSchema: () => request<WorkbenchSchemaResponse>(ENDPOINTS.schema),
  getOpenApi: () => request<{ paths?: Record<string, unknown> }>(ENDPOINTS.openapi),
  createSession: (mode: "uploaded" | "live" = "uploaded") =>
    request<{ session_id?: string; session?: { session_id?: string } }>(ENDPOINTS.sessions, {
      method: "POST",
      body: JSON.stringify({ mode, workspace_name: "Alpha Vineyard · Water Command Center" }),
    }),
  createSamplePackage: (scenario?: string) =>
    request<{ session?: { session_id?: string }; session_id?: string; artifacts?: WorkbenchArtifact[] }>(
      ENDPOINTS.samplePackage,
      { method: "POST", body: JSON.stringify({ scenario: scenario ?? "validated_operating_block" }) },
    ),
  uploadFile: (sessionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<WorkbenchArtifact>(ENDPOINTS.upload(sessionId), { method: "POST", body: form });
  },
  analyzeSession: (sessionId: string) =>
    request<WorkbenchAnalysisResult>(ENDPOINTS.analyze(sessionId), {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, mode: "uploaded" }),
    }),
  analyzeLive: (source: string, entityId: string) =>
    request<WorkbenchAnalysisResult>(ENDPOINTS.analyzeLive, {
      method: "POST",
      body: JSON.stringify({ source, entity_id: entityId }),
    }),
  getControllerEnvironments: () => request<Record<string, unknown>>(ENDPOINTS.controllerEnvironments),
  getWiseconnAuth: () => request<Record<string, unknown>>(ENDPOINTS.wiseconnAuth),
  getTalgilStatus: () => request<Record<string, unknown>>(ENDPOINTS.talgilStatus),
  getEvidenceChain: (sessionId: string) => request<EvidenceChainResponse>(ENDPOINTS.evidenceChain(sessionId)),
  recordEvidenceAction: (sessionId: string, action: "schedule" | "applied" | "observe" | "verify", evidence_summary: string) =>
    request<EvidenceActionResponse>(ENDPOINTS.evidenceAction(sessionId, action), {
      method: "POST",
      body: JSON.stringify({ actor: "Operations user", evidence_summary }),
    }),
};

export type ApiClient = typeof apiClient;
