import type {
  ApiResult,
  AuthSession,
  BillingStatus,
  MeResponse,
  SaaSWorkspace,
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

const TOKEN_KEY = "agroai.access_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: init?.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
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
  auth: {
    register: "/v1/auth/register",
    login: "/v1/auth/login",
    logout: "/v1/auth/logout",
    me: "/v1/auth/me",
  },
  orgs: "/v1/orgs",
  orgSwitch: (id: string) => `/v1/orgs/${encodeURIComponent(id)}/switch`,
  workspaces: "/v1/workspaces",
  assuranceOverview: (id: string) => `/v1/workspaces/${encodeURIComponent(id)}/assurance/overview`,
  workspaceEvidence: (id: string) => `/v1/workspaces/${encodeURIComponent(id)}/evidence`,
  agentRun: (id: string) => `/v1/workspaces/${encodeURIComponent(id)}/agents/run`,
  agentRuns: (id: string) => `/v1/workspaces/${encodeURIComponent(id)}/agents/runs`,
  workspaceReports: (id: string) => `/v1/workspaces/${encodeURIComponent(id)}/reports`,
  billingStatus: (organizationId?: string) =>
    `/v1/billing/status${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ""}`,
  checkout: "/v1/billing/create-checkout-session",
  billingPortal: "/v1/billing/create-portal-session",
} as const;

export const apiClient = {
  getSchema: () => request<WorkbenchSchemaResponse>(ENDPOINTS.schema),
  getOpenApi: () => request<{ paths?: Record<string, unknown> }>(ENDPOINTS.openapi),
  createSession: (mode: "uploaded" | "live" = "uploaded") =>
    request<{ session_id?: string; session?: { session_id?: string } }>(ENDPOINTS.sessions, {
      method: "POST",
      body: JSON.stringify({ mode, workspace_name: "Alpha Vineyard · Water Command Center" }),
    }),
  createSamplePackage: () =>
    request<{ session?: { session_id?: string }; session_id?: string; artifacts?: WorkbenchArtifact[] }>(
      ENDPOINTS.samplePackage,
      { method: "POST" },
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
  register: (payload: {
    email: string;
    password: string;
    name?: string;
    organization_name: string;
    workspace_name?: string;
    crop?: string;
    region?: string;
  }) => request<AuthSession>(ENDPOINTS.auth.register, { method: "POST", body: JSON.stringify(payload) }),
  login: (email: string, password: string) =>
    request<AuthSession>(ENDPOINTS.auth.login, { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<{ ok: boolean }>(ENDPOINTS.auth.logout, { method: "POST" }),
  getMe: () => request<MeResponse>(ENDPOINTS.auth.me),
  createOrganization: (name: string) => request<{ organization: unknown }>(ENDPOINTS.orgs, { method: "POST", body: JSON.stringify({ name }) }),
  getOrganizations: () => request<{ organizations: unknown[] }>(ENDPOINTS.orgs),
  switchOrganization: (organizationId: string) => request<{ current_organization: unknown }>(ENDPOINTS.orgSwitch(organizationId), { method: "POST" }),
  getWorkspaces: () => request<{ workspaces: SaaSWorkspace[] }>(ENDPOINTS.workspaces),
  createWorkspace: (payload: { organization_id?: string; name: string; crop?: string; region?: string; mode?: "evaluation" | "live" }) =>
    request<{ workspace: SaaSWorkspace }>(ENDPOINTS.workspaces, { method: "POST", body: JSON.stringify(payload) }),
  getBillingStatus: (organizationId?: string) => request<BillingStatus>(ENDPOINTS.billingStatus(organizationId)),
  createCheckoutSession: (organization_id: string, plan: "pilot" | "pro") =>
    request<{ checkout_url: string }>(ENDPOINTS.checkout, { method: "POST", body: JSON.stringify({ organization_id, plan }) }),
  createBillingPortalSession: (organization_id: string) =>
    request<{ portal_url: string }>(ENDPOINTS.billingPortal, { method: "POST", body: JSON.stringify({ organization_id }) }),
  getAssuranceOverview: (workspaceId: string) => request<Record<string, unknown>>(ENDPOINTS.assuranceOverview(workspaceId)),
  getEvidence: (workspaceId: string) => request<Record<string, unknown>>(ENDPOINTS.workspaceEvidence(workspaceId)),
  runAgent: (workspaceId: string) => request<Record<string, unknown>>(ENDPOINTS.agentRun(workspaceId), { method: "POST" }),
  getAgentRuns: (workspaceId: string) => request<Record<string, unknown>>(ENDPOINTS.agentRuns(workspaceId)),
  getReports: (workspaceId: string) => request<Record<string, unknown>>(ENDPOINTS.workspaceReports(workspaceId)),
};

export type ApiClient = typeof apiClient;
