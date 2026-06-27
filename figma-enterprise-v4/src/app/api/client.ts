const isBrowser = typeof window !== "undefined";
const isLocalFrontend =
  isBrowser &&
  ["localhost", "127.0.0.1", "0.0.0.0"].includes(window.location.hostname);

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  (isLocalFrontend ? "http://localhost:8000" : "https://api.agroai-pilot.com");

const tokenKey = "agroai_access_token";

export type ApiError = Error & {
  status?: number;
  details?: unknown;
  code?: string;
};

type RequestOptions = RequestInit & {
  token?: string | null;
};

async function parseResponse(response: Response) {
  const contentType = response.headers.get("content-type") || "";

  if (response.status === 204) return null;
  if (contentType.includes("application/json")) return response.json();

  const text = await response.text();
  return text ? { message: text } : null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = options.token ?? localStorage.getItem(tokenKey);
  const headers = new Headers(options.headers);
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;

  if (!headers.has("Content-Type") && options.body && !isFormData) {
    headers.set("Content-Type", "application/json");
  }

  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch (cause) {
    const error = new Error("Backend unavailable. Retry.") as ApiError;
    error.code = "network_unavailable";
    error.details = cause;
    throw error;
  }

  const data = await parseResponse(response);

  if (!response.ok) {
    const message =
      data && typeof data === "object" && "detail" in data
        ? String(data.detail)
        : data && typeof data === "object" && "message" in data
          ? String(data.message)
          : `Request failed with status ${response.status}`;

    const error = new Error(message) as ApiError;
    error.status = response.status;
    error.details = data;

    if (response.status === 401) {
      window.dispatchEvent(new Event("agroai:unauthorized"));
    }

    throw error;
  }

  return data as T;
}

async function download(path: string): Promise<Blob> {
  const token = localStorage.getItem(tokenKey);
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { headers });
  if (!response.ok) throw new Error(`Download failed with status ${response.status}`);
  return response.blob();
}

function get<T>(path: string, token?: string | null) {
  return request<T>(path, { token });
}

function post<T>(path: string, payload?: unknown, token?: string | null) {
  return request<T>(path, {
    method: "POST",
    body: payload ? JSON.stringify(payload) : undefined,
    token,
  });
}

function patch<T>(path: string, payload?: unknown, token?: string | null) {
  return request<T>(path, {
    method: "PATCH",
    body: payload ? JSON.stringify(payload) : undefined,
    token,
  });
}

function remove<T>(path: string, token?: string | null) {
  return request<T>(path, { method: "DELETE", token });
}

function upload<T>(path: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<T>(path, { method: "POST", body: form });
}

export type RegisterPayload = {
  name: string;
  email: string;
  password: string;
  organization_name: string;
  workspace_name: string;
  crop?: string;
  region?: string;
};

export type LoginPayload = {
  email: string;
  password: string;
};

export type CreateWorkspacePayload = {
  name: string;
  crop?: string;
  region?: string;
};

export type CreateOrgPayload = {
  name: string;
};

export type AiRequestPayload = {
  task?: string;
  message?: string;
  workspace_id?: string;
  block_id?: string;
  inputs?: Record<string, unknown>;
};

export type ConnectorProvider =
  | "wiseconn"
  | "talgil"
  | "weather"
  | "openet"
  | "manual_csv"
  | "gmail"
  | "outlook"
  | "google_drive"
  | "dropbox"
  | "box"
  | "slack"
  | "salesforce"
  | "google_earth_engine"
  | "custom_api";

export type ConnectorStartPayload = {
  provider: ConnectorProvider;
  method?: string;
  workspace_id?: string;
  metadata?: Record<string, unknown>;
};

export type ConnectorConnectPayload = {
  provider: ConnectorProvider;
  workspace_id?: string;
  mode?: string;
  display_name?: string;
  config?: Record<string, unknown>;
  scopes?: string[];
  read_context_enabled?: boolean;
  send_reports_enabled?: boolean;
};

export type IntelligenceActionPayload = {
  action:
    | "field_diagnosis"
    | "irrigation_plan"
    | "assurance_packet"
    | "evidence_gap_analysis"
    | "integration_diagnosis"
    | "report_draft";
  payload?: Record<string, unknown>;
};

export type IntelligenceAskPayload = {
  question: string;
  workspace_id?: string;
  block_id?: string;
  customer_mode?: string;
  output_format?: string;
};

export const apiClient = {
  get,
  post,
  patch,
  remove,
  request,
  download,

  auth: {
    register: (payload: RegisterPayload) => post("/v1/auth/register", payload),
    login: (payload: LoginPayload) => post("/v1/auth/login", payload),
    logout: () => post("/v1/auth/logout"),
    me: () => get("/v1/auth/me"),
  },

  billing: {
    status: () => get("/v1/billing/status"),
    createCheckoutSession: () => post("/v1/billing/create-checkout-session"),
    createPortalSession: () => post("/v1/billing/create-portal-session"),
  },

  orgs: {
    list: () => get("/v1/orgs"),
    create: (payload: CreateOrgPayload) => post("/v1/orgs", payload),
  },

  workspaces: {
    list: () => get("/v1/workspaces"),
    create: (payload: CreateWorkspacePayload) => post("/v1/workspaces", payload),
  },

  assurance: {
    readiness: () => get("/v1/assurance/readiness"),
    passport: () => get("/v1/assurance/passport"),
  },

  evidence: {
    list: () => get("/v1/evidence"),
    summary: () => get("/v1/evidence/summary"),
    upload: (file: File, provider = "manual_csv", workspaceId?: string) => {
      const query = new URLSearchParams({ provider });
      if (workspaceId) query.set("workspace_id", workspaceId);
      return upload(`/v1/evidence/upload?${query.toString()}`, file);
    },
    uploadMetadata: (payload: unknown) => post("/v1/evidence", payload),
  },

  reports: {
    list: () => get("/v1/reports"),
    generate: (payload?: unknown) => post("/v1/reports/generate", payload),
    export: (payload?: unknown) => post("/v1/reports/export", payload),
  },

  artifacts: {
    list: () => get("/v1/artifacts"),
    get: (artifactId: string) => get(`/v1/artifacts/${encodeURIComponent(artifactId)}`),
    download: (artifactId: string) => download(`/v1/artifacts/${encodeURIComponent(artifactId)}/download`),
  },

  agents: {
    list: () => get("/v1/agents/runs"),
    run: (payload?: unknown) => post("/v1/agents/run", payload),
    status: (runId: string) => get(`/v1/agents/runs/${encodeURIComponent(runId)}`),
  },

  ai: {
    chat: (payload: AiRequestPayload) => post("/v1/ai/chat", payload),
    irrigationRecommendation: (payload: AiRequestPayload) => post("/v1/ai/irrigation-recommendation", payload),
    assuranceReview: (payload: AiRequestPayload) => post("/v1/ai/assurance-review", payload),
    reportDraft: (payload: AiRequestPayload) => post("/v1/ai/report-draft", payload),
    integrationDiagnosis: (payload: AiRequestPayload) => post("/v1/ai/integration-diagnosis", payload),
  },

  intelligence: {
    brief: () => get("/v1/intelligence/brief"),
    ask: (payload: IntelligenceAskPayload) => post("/v1/intelligence/ask", payload),
    action: (payload: IntelligenceActionPayload) => post("/v1/intelligence/action", payload),
  },

  connectorHub: {
    catalog: () => get("/v1/connectors/catalog"),
    connections: () => get("/v1/connectors/connections"),
    create: (payload: unknown) => post("/v1/connectors/connections", payload),
    connect: (payload: ConnectorConnectPayload) => post("/v1/connectors/connect", payload),
    start: (payload: ConnectorStartPayload) => post("/v1/connectors/start", payload),
    oauthStart: (payload: unknown) => post("/v1/connectors/oauth/start", payload),
    get: (connectionId: string) => get(`/v1/connectors/connections/${encodeURIComponent(connectionId)}`),
    update: (connectionId: string, payload: unknown) => patch(`/v1/connectors/connections/${encodeURIComponent(connectionId)}`, payload),
    test: (connectionId: string) => post(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/test`),
    upload: (connectionId: string, file: File) => upload(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/upload`, file),
    data: (connectionId: string) => get(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/data`),
    dataSources: () => get("/v1/connectors/data-sources"),
    jobs: () => get("/v1/connectors/jobs"),
    mappingSuggestions: (connectionId: string) => get(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/mapping/suggestions`),
    saveMapping: (connectionId: string, mapping: Record<string, string>) =>
      post(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/mapping`, { mapping }),
    sync: (connectionId: string) => post(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/sync`),
    delete: (connectionId: string) => remove(`/v1/connectors/connections/${encodeURIComponent(connectionId)}`),
  },

  integrations: {
    list: () => get("/v1/integrations"),
    status: () => get("/v1/integrations/status"),
    wiseconn: () => get("/v1/wiseconn/status"),
    talgil: () => get("/v1/talgil/status"),
  },

  decisioning: {
    status: () => get("/v1/decisioning/status"),
  },

  workbench: {
    status: () => get("/v1/workbench/status"),
  },

  register: (payload: RegisterPayload) => apiClient.auth.register(payload),
  login: (payload: LoginPayload) => apiClient.auth.login(payload),
  logout: () => apiClient.auth.logout(),
  me: () => apiClient.auth.me(),
  getOrgs: () => apiClient.orgs.list(),
  getWorkspaces: () => apiClient.workspaces.list(),
  getBillingStatus: () => apiClient.billing.status(),
};
