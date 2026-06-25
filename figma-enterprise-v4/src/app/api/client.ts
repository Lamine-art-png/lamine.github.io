export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  "https://api.agroai-pilot.com";

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

  if (response.status === 204) {
    return null;
  }

  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  return text ? { message: text } : null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = options.token ?? localStorage.getItem(tokenKey);
  const headers = new Headers(options.headers);

  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
    });
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

export const apiClient = {
  get,
  post,
  request,
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
    uploadMetadata: (payload: unknown) => post("/v1/evidence", payload),
  },
  reports: {
    list: () => get("/v1/reports"),
    export: (payload?: unknown) => post("/v1/reports/export", payload),
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
