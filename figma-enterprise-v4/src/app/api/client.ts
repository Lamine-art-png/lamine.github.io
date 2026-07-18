export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  "https://api.agroai-pilot.com";

export const API_BASE_URL_SOURCE =
  import.meta.env.VITE_API_BASE_URL ? "VITE_API_BASE_URL" : import.meta.env.VITE_API_URL ? "VITE_API_URL" : "default";

const FORMSPREE_SUPPORT_URL = import.meta.env.VITE_FORMSPREE_SUPPORT_URL || import.meta.env.VITE_FORMSPREE_ENDPOINT || "";
const tokenKey = "agroai_access_token";
const commercialBoundaryEvent = "agroai:commercial-boundary";
const uploadStateEvent = "agroai:upload-state";

export type ApiError = Error & { status?: number; details?: unknown; code?: string };
type RequestOptions = RequestInit & { token?: string | null };

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function commercialDetail(data: unknown, status: number, path: string) {
  const payload = objectValue(data);
  const nested = objectValue(payload.detail);
  const source = Object.keys(nested).length ? nested : payload;
  return {
    status,
    code: typeof source.code === "string" ? source.code : undefined,
    feature: typeof source.feature === "string" ? source.feature : undefined,
    feature_state: typeof source.feature_state === "string" ? source.feature_state : undefined,
    metric: typeof source.metric === "string" ? source.metric : undefined,
    used: typeof source.used === "number" ? source.used : undefined,
    reserved: typeof source.reserved === "number" ? source.reserved : undefined,
    limit: typeof source.limit === "number" ? source.limit : undefined,
    remaining: typeof source.remaining === "number" ? source.remaining : undefined,
    recommended_plan: typeof source.recommended_plan === "string" ? source.recommended_plan : undefined,
    message: typeof source.message === "string" ? source.message : undefined,
    source: path,
  };
}

function dispatchCommercialBoundary(data: unknown, status: number, path: string) {
  const detail = commercialDetail(data, status, path);
  const commercialCode = ["upgrade_required", "subscription_inactive", "quota_exceeded"].includes(String(detail.code || ""));
  if (status === 402 || status === 429 || commercialCode) {
    window.dispatchEvent(new CustomEvent(commercialBoundaryEvent, { detail }));
  }
}

function dispatchUploadState(detail: Record<string, unknown>) {
  window.dispatchEvent(new CustomEvent(uploadStateEvent, { detail }));
}

async function parseResponse(response: Response) {
  const contentType = response.headers.get("content-type") || "";
  if (response.status === 204) return null;
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text ? { message: text } : null;
}

function apiErrorFromResponse(data: unknown, response: Response, path: string): ApiError {
  const payload = objectValue(data);
  const detail = objectValue(payload.detail);
  const message = Object.keys(detail).length && "message" in detail
    ? String(detail.message)
    : "detail" in payload
      ? String(payload.detail)
      : "message" in payload
        ? String(payload.message)
        : `Request failed with status ${response.status}`;
  const error = new Error(message) as ApiError;
  error.status = response.status;
  error.details = data;
  if (typeof detail.code === "string") error.code = detail.code;
  else if (typeof payload.code === "string") error.code = payload.code;
  dispatchCommercialBoundary(data, response.status, path);
  return error;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = options.token ?? localStorage.getItem(tokenKey);
  const headers = new Headers(options.headers);
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!headers.has("Content-Type") && options.body && !isFormData) headers.set("Content-Type", "application/json");
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
    if (response.status === 401) window.dispatchEvent(new Event("agroai:unauthorized"));
    throw apiErrorFromResponse(data, response, path);
  }
  return data as T;
}

async function download(path: string): Promise<Blob> {
  const token = localStorage.getItem(tokenKey);
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { headers });
  if (!response.ok) {
    const data = await parseResponse(response);
    throw apiErrorFromResponse(data, response, path);
  }
  return response.blob();
}

async function downloadPost(path: string, payload?: unknown): Promise<Blob> {
  const token = localStorage.getItem(tokenKey);
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "POST", headers, body: payload ? JSON.stringify(payload) : undefined });
  if (!response.ok) {
    const data = await parseResponse(response);
    throw apiErrorFromResponse(data, response, path);
  }
  return response.blob();
}

function get<T>(path: string, token?: string | null) { return request<T>(path, { token }); }
function post<T>(path: string, payload?: unknown, token?: string | null) { return request<T>(path, { method: "POST", body: payload ? JSON.stringify(payload) : undefined, token }); }
function patch<T>(path: string, payload?: unknown, token?: string | null) { return request<T>(path, { method: "PATCH", body: payload ? JSON.stringify(payload) : undefined, token }); }
function remove<T>(path: string, token?: string | null) { return request<T>(path, { method: "DELETE", token }); }
function upload<T>(path: string, file: File) { const form = new FormData(); form.append("file", file); return request<T>(path, { method: "POST", body: form }); }

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}

async function uploadEvidence(file: File, provider?: string, workspaceId?: string) {
  const resolvedProvider = provider || providerForUpload(file);
  const query = new URLSearchParams({ provider: resolvedProvider });
  if (workspaceId) query.set("workspace_id", workspaceId);
  dispatchUploadState({ phase: "uploading", filename: file.name, provider: resolvedProvider, message: `Uploading ${file.name}...` });

  try {
    const initial = await upload<Record<string, unknown>>(`/v1/evidence/upload?${query.toString()}`, file);
    const jobId = typeof initial.job_id === "string" ? initial.job_id : "";
    if (!jobId) {
      dispatchUploadState({ phase: "complete", filename: file.name, provider: resolvedProvider, message: `${file.name} is imported and available to AGRO-AI.` });
      return initial;
    }

    dispatchUploadState({
      phase: "stored",
      filename: file.name,
      provider: resolvedProvider,
      job_id: jobId,
      message: `${file.name} is securely stored. AGRO-AI is processing it now.`,
    });

    for (let attempt = 0; attempt < 16; attempt += 1) {
      await wait(attempt < 4 ? 500 : 1000);
      const receipt = await get<Record<string, unknown>>(`/v1/connectors/jobs/${encodeURIComponent(jobId)}`);
      const job = objectValue(receipt.job);
      const status = String(job.status || "");
      if (status === "succeeded") {
        const normalized = {
          ...initial,
          ...job,
          status,
          durable_stored: true,
          processing_complete: true,
          job_id: jobId,
          warnings: Number(job.warning_count || 0) > 0 ? [`${job.warning_count} ingestion warning(s). Review the imported source.`] : [],
        };
        dispatchUploadState({ phase: "complete", filename: file.name, provider: resolvedProvider, job_id: jobId, message: `${file.name} is stored, processed, and ready.` });
        return normalized;
      }
      if (["failed", "cancelled"].includes(status)) {
        throw new Error(String(job.error || `File processing ${status}.`));
      }
    }

    const pending = {
      ...initial,
      durable_stored: true,
      processing_pending: true,
      job_id: jobId,
      rows_parsed: 0,
      evidence_records_created: 0,
      warnings: ["The file is securely stored and still processing. It will appear in Sources when ingestion completes."],
    };
    dispatchUploadState({ phase: "stored", filename: file.name, provider: resolvedProvider, job_id: jobId, message: `${file.name} is securely stored and still processing.` });
    return pending;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upload failed.";
    dispatchUploadState({ phase: "failed", filename: file.name, provider: resolvedProvider, message });
    throw error;
  }
}

async function submitFormspree(payload: SupportTicketPayload) {
  if (!FORMSPREE_SUPPORT_URL) throw new Error("Support form endpoint is not configured.");
  const response = await fetch(FORMSPREE_SUPPORT_URL, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify({ ...payload, product: "AGRO-AI Enterprise Portal", submitted_at: new Date().toISOString() }) });
  if (!response.ok) throw new Error(`Support form failed with status ${response.status}`);
  const data = await response.json().catch(() => ({}));
  return { status: "received", message: "Thanks - your request was received.", request_id: data.id || `formspree-${Date.now()}`, notification_status: "formspree_received" };
}

async function submitSupportTicket(payload: SupportTicketPayload) {
  try { return await post("/v1/support/ticket", payload); }
  catch (primary) {
    try { return await post("/v1/support/ticket-public", payload); }
    catch {
      try { return await submitFormspree(payload); }
      catch { throw primary; }
    }
  }
}

export type RegisterPayload = {
  name: string;
  email: string;
  password: string;
  organization_name: string;
  organization_type: string;
  professional_role: string;
  phone_number: string;
  website_url?: string;
  professional_profile_url?: string;
  country: string;
  operating_region: string;
  acres_or_sites: string;
  primary_crops: string;
  intended_use: string;
  planned_data_sources: string;
  workspace_name: string;
  crop?: string;
  region?: string;
};
export type LoginPayload = { email: string; password: string };
export type CreateWorkspacePayload = { name: string; crop?: string; region?: string };
export type CreateOrgPayload = { name: string };
export type AiRequestPayload = { task?: string; message?: string; workspace_id?: string; block_id?: string; inputs?: Record<string, unknown>; preferred_language?: string };
export type ConnectorProvider = "wiseconn" | "talgil" | "universal_controller" | "weather" | "openet" | "manual_csv" | "chat_upload" | "gmail" | "outlook" | "google_drive" | "dropbox" | "box" | "slack" | "salesforce" | "google_earth_engine" | "custom_api";
export type ConnectorStartPayload = { provider: ConnectorProvider; method?: string; workspace_id?: string; metadata?: Record<string, unknown> };
export type ConnectorConnectPayload = { provider: ConnectorProvider; workspace_id?: string; mode?: string; display_name?: string; config?: Record<string, unknown>; scopes?: string[]; read_context_enabled?: boolean; send_reports_enabled?: boolean };
export type IntelligenceActionPayload = { action: "field_diagnosis" | "irrigation_plan" | "assurance_packet" | "evidence_gap_analysis" | "integration_diagnosis" | "report_draft"; payload?: Record<string, unknown> };
export type IntelligenceAskPayload = { question: string; workspace_id?: string; block_id?: string; customer_mode?: string; output_format?: string; preferred_language?: string };
export type IntelligenceRunPayload = { task: "chat" | "field_diagnosis" | "exception_triage" | "decision_workbench" | "report_factory" | "connector_diagnosis" | "readiness_analysis"; question: string; workspace_id?: string; field_id?: string; audience?: string; history?: { role: string; content: string }[]; uploaded_evidence?: Record<string, unknown>[]; preferred_language?: string };
export type WorkbenchRunPayload = { workspace_id?: string; field_id?: string; mode?: "daily" | "field" | "compliance" | "irrigation" };
export type ReportFactoryPayload = { report_type: "water_use_summary" | "compliance_packet" | "exception_report" | "executive_brief" | "grower_recommendation"; workspace_id?: string; field_id?: string; audience?: "operator" | "owner" | "agency" | "lender" | "investor" | "grower"; preferred_language?: string };
export type FieldOpsTaskPayload = { title: string; field?: string; block?: string; assigned_to?: string; priority?: "high" | "medium" | "low"; why: string; instructions?: string[]; evidence_required?: string[]; source_exception_id?: string; source_decision_id?: string; created_from?: "exception" | "decision" | "missing_evidence" | "manual" | "field_update"; workspace_id?: string };
export type FieldOpsTaskStatusPayload = { status: "open" | "in_progress" | "blocked" | "done" | "needs_review"; workspace_id?: string };
export type FieldUpdatePayload = { field_id?: string; field_name?: string; block?: string; crop?: string; update_text: string; event_type: "observation" | "meter_reading" | "irrigation_event" | "issue" | "photo_note" | "operator_note" | "compliance_note"; occurred_at?: string; water_gallons?: number; flow_gpm?: number; duration_minutes?: number; attachments?: Record<string, unknown>[]; workspace_id?: string };
export type FieldMessagePayload = { message: string; sender_role: "operator" | "manager" | "agency" | "advisor"; channel: "portal" | "email" | "sms" | "whatsapp" | "slack" | "teams"; field_hint?: string; workspace_id?: string };
export type AutopilotReportPayload = { audience: "operator" | "manager" | "owner" | "agency" | "lender" | "grower"; scope: "today" | "weekly" | "field" | "compliance" | "exceptions"; field_id?: string; workspace_id?: string; preferred_language?: string };
function providerForUpload(file: File) { const name = file.name.toLowerCase(); if (name.endsWith(".csv")) return "manual_csv"; return "chat_upload"; }
export type ProductCheckoutPayload = { plan_id: "free" | "professional" | "team" | "network" | "enterprise"; billing_period: "monthly" | "annual" };
export type BillingCheckoutSessionPayload = { organization_id: string; offer?: string; plan?: string };
export type BillingPortalPayload = { organization_id: string };
export type EmailVerificationRequestPayload = { email?: string };
export type EmailVerificationConfirmPayload = { token: string };
export type TeamInvitationPayload = { email: string; role: "owner" | "admin" | "manager" | "operator" | "viewer" };
export type SupportTicketPayload = { category: "support" | "integration" | "issue" | "onboarding" | "sales"; subject: string; message: string; priority?: "low" | "medium" | "high" | "urgent"; name?: string; email?: string; company?: string; role?: string; workspace_id?: string; source_page?: string };
export type OnboardingPayload = { current_step?: string; selected_plan?: string; organization_type?: string; acres_or_sites?: string; primary_goal?: string; completed_steps?: string[]; workspace_id?: string };
export type ConversationPayload = { title?: string; workspace_id?: string; message?: string };
export type ConversationMessagePayload = { content: string; audience?: string; output?: string; preferred_language?: string };
export type AdminRequestUpdatePayload = { status?: "received" | "triaged" | "in_progress" | "waiting_on_customer" | "closed"; priority?: "low" | "medium" | "high" | "urgent" };
export type PlatformAdminCustomerFilters = { search?: string; verification?: "all" | "verified" | "unverified"; active?: "all" | "active" | "inactive"; plan?: string; sort?: "newest" | "oldest" | "recent_login"; limit?: number; offset?: number };

function platformAdminCustomerQuery(filters: PlatformAdminCustomerFilters = {}) {
  const query = new URLSearchParams();
  if (filters.search) query.set("search", filters.search);
  if (filters.verification && filters.verification !== "all") query.set("verification", filters.verification);
  if (filters.active && filters.active !== "all") query.set("active", filters.active);
  if (filters.plan) query.set("plan", filters.plan);
  if (filters.sort) query.set("sort", filters.sort);
  if (typeof filters.limit === "number") query.set("limit", String(filters.limit));
  if (typeof filters.offset === "number") query.set("offset", String(filters.offset));
  return query.toString();
}

export const apiClient = {
  get, post, patch, remove, request, download,
  auth: { register: (payload: RegisterPayload) => post("/v1/auth/register", payload), login: (payload: LoginPayload) => post("/v1/auth/login", payload), logout: () => post("/v1/auth/logout"), me: () => get("/v1/auth/me"), requestEmailVerification: (payload?: EmailVerificationRequestPayload) => post("/v1/auth/email-verification/request", payload), confirmEmailVerification: (payload: EmailVerificationConfirmPayload) => post("/v1/auth/email-verification/confirm", payload) },
  billing: {
    status: () => get("/v1/billing/status"),
    commercialSummary: () => get("/v1/billing/commercial-summary"),
    createCheckoutSession: (payload: BillingCheckoutSessionPayload) => post("/v1/billing/create-checkout-session", payload),
    createPortalSession: (payload: BillingPortalPayload) => post("/v1/billing/create-portal-session", payload),
    summary: () => get("/v1/billing/summary"),
    checkout: (payload: ProductCheckoutPayload) => post("/v1/billing/checkout-authoritative", payload),
  },
  product: { plans: () => get("/v1/product/plans"), shell: () => get("/v1/app/shell") },
  account: { me: () => get("/v1/account/me"), profile: () => get("/v1/account/profile"), updateProfile: (payload: unknown) => patch("/v1/account/profile", payload), security: () => get("/v1/account/security"), requestEmailVerification: () => post("/v1/account/email-verification/request"), startTwoFactor: () => post("/v1/account/two-factor/start") },
  onboarding: { state: () => get("/v1/onboarding/state"), start: (payload?: OnboardingPayload) => post("/v1/onboarding/start", payload), update: (payload: OnboardingPayload) => patch("/v1/onboarding/state", payload), complete: () => post("/v1/onboarding/complete"), request: (payload: SupportTicketPayload) => post("/v1/onboarding/request", payload), requestHelp: (payload: unknown) => post("/v1/onboarding/request-help", payload) },
  support: { options: () => get("/v1/support/options"), ticket: submitSupportTicket },
  sales: { contact: (payload: unknown) => post("/v1/sales/contact", payload), networkInquiry: (payload: unknown) => post("/v1/sales/network-inquiry", payload) },
  conversations: { list: () => get("/v1/conversations"), create: (payload: ConversationPayload) => post("/v1/conversations", payload), get: (conversationId: string) => get(`/v1/conversations/${encodeURIComponent(conversationId)}`), message: (conversationId: string, payload: ConversationMessagePayload) => post(`/v1/conversations/${encodeURIComponent(conversationId)}/messages`, payload), delete: (conversationId: string) => remove(`/v1/conversations/${encodeURIComponent(conversationId)}`) },
  adminRequests: { list: (type?: string) => get(`/v1/admin/requests${type ? `?type=${encodeURIComponent(type)}` : ""}`), update: (requestId: string, payload: AdminRequestUpdatePayload) => patch(`/v1/admin/requests/${encodeURIComponent(requestId)}`, payload), system: () => get("/v1/admin/system") },
  platformAdmin: {
    customers: (filters: PlatformAdminCustomerFilters = {}) => {
      const query = platformAdminCustomerQuery(filters);
      return get(`/v1/platform-admin/customers${query ? `?${query}` : ""}`);
    },
    exportCustomers: (filters: PlatformAdminCustomerFilters = {}) => {
      const query = platformAdminCustomerQuery(filters);
      return download(`/v1/platform-admin/customers.csv${query ? `?${query}` : ""}`);
    },
  },
  team: { members: () => get("/v1/team/members"), invitations: () => get("/v1/team/invitations"), invite: (payload: TeamInvitationPayload) => post("/v1/team/invitations", payload), revoke: (invitationId: string) => remove(`/v1/team/invitations/${encodeURIComponent(invitationId)}`) },
  orgs: { list: () => get("/v1/orgs"), create: (payload: CreateOrgPayload) => post("/v1/orgs", payload) },
  workspaces: { list: () => get("/v1/workspaces"), create: (payload: CreateWorkspacePayload) => post("/v1/workspaces", payload) },
  assurance: { readiness: () => get("/v1/assurance/readiness"), passport: () => get("/v1/assurance/passport") },
  evidence: { list: () => get("/v1/evidence"), summary: () => get("/v1/evidence/summary"), upload: uploadEvidence, uploadMetadata: (payload: unknown) => post("/v1/evidence", payload) },
  reports: { list: () => get("/v1/reports"), generate: (payload?: unknown) => post("/v1/reports/generate", payload), export: (payload?: unknown) => post("/v1/reports/export", payload) },
  artifacts: { list: () => get("/v1/artifacts"), get: (artifactId: string) => get(`/v1/artifacts/${encodeURIComponent(artifactId)}`), download: (artifactId: string) => download(`/v1/artifacts/${encodeURIComponent(artifactId)}/download`) },
  agents: { list: () => get("/v1/agents/runs"), run: (payload?: unknown) => post("/v1/agents/run", payload), status: (runId: string) => get(`/v1/agents/runs/${encodeURIComponent(runId)}`) },
  ai: { status: () => get("/v1/ai/status"), chat: (payload: AiRequestPayload) => post("/v1/ai/chat", payload), irrigationRecommendation: (payload: AiRequestPayload) => post("/v1/ai/irrigation-recommendation", payload), assuranceReview: (payload: AiRequestPayload) => post("/v1/ai/assurance-review", payload), reportDraft: (payload: AiRequestPayload) => post("/v1/ai/report-draft", payload), integrationDiagnosis: (payload: AiRequestPayload) => post("/v1/ai/integration-diagnosis", payload) },
  intelligence: { brief: () => get("/v1/intelligence/brief"), brainRun: (payload: IntelligenceRunPayload) => post("/v1/intelligence/brain/run", payload), run: (payload: IntelligenceRunPayload) => post("/v1/intelligence/run", payload), ask: (payload: IntelligenceAskPayload) => post("/v1/intelligence/run", { task: "chat", question: payload.question, workspace_id: payload.workspace_id, preferred_language: payload.preferred_language }), action: (payload: IntelligenceActionPayload) => post("/v1/intelligence/action", payload) },
  readiness: { summary: (workspaceId?: string) => get(`/v1/readiness/summary${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`) },
  fields: { intelligence: (workspaceId?: string) => get(`/v1/fields/intelligence${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`) },
  exceptions: { list: (workspaceId?: string) => get(`/v1/exceptions${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`) },
  decisions: { workbench: (workspaceId?: string, fieldId?: string) => { const query = new URLSearchParams(); if (workspaceId) query.set("workspace_id", workspaceId); if (fieldId) query.set("field_id", fieldId); const suffix = query.toString() ? `?${query.toString()}` : ""; return get(`/v1/decisions/workbench${suffix}`); }, runWorkbench: (payload: WorkbenchRunPayload) => post("/v1/decisions/workbench/run", payload) },
  reportFactory: { generate: (payload: ReportFactoryPayload) => post("/v1/reports/factory", payload), pdf: (payload: ReportFactoryPayload) => downloadPost("/v1/reports/factory/pdf", payload) },
  fieldOps: { commandCenter: (workspaceId?: string) => get(`/v1/field-ops/command-center${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`), tasks: (workspaceId?: string) => get(`/v1/field-ops/tasks${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`), createTask: (payload: FieldOpsTaskPayload) => post("/v1/field-ops/tasks/create", payload), updateTaskStatus: (taskId: string, payload: FieldOpsTaskStatusPayload) => post(`/v1/field-ops/tasks/${encodeURIComponent(taskId)}/status`, payload), fieldUpdate: (payload: FieldUpdatePayload) => post("/v1/field-ops/field-update", payload), fieldMessage: (payload: FieldMessagePayload) => post("/v1/field-ops/field-message", payload), autopilotReport: (payload: AutopilotReportPayload) => post("/v1/field-ops/autopilot-report", payload), auditTrail: (workspaceId?: string) => get(`/v1/field-ops/audit-trail${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`) },
  connectorHub: { catalog: () => get("/v1/connectors/catalog"), connections: () => get("/v1/connectors/connections"), create: (payload: unknown) => post("/v1/connectors/connections", payload), connect: (payload: ConnectorConnectPayload) => post("/v1/connectors/connect", payload), start: (payload: ConnectorStartPayload) => post("/v1/connectors/start", payload), oauthStart: (payload: unknown) => post("/v1/connectors/oauth/start", payload), get: (connectionId: string) => get(`/v1/connectors/connections/${encodeURIComponent(connectionId)}`), update: (connectionId: string, payload: unknown) => patch(`/v1/connectors/connections/${encodeURIComponent(connectionId)}`, payload), test: (connectionId: string) => post(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/test`), upload: (connectionId: string, file: File) => upload(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/upload`, file), data: (connectionId: string) => get(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/data`), dataSources: () => get("/v1/connectors/data-sources"), jobs: () => get("/v1/connectors/jobs"), jobStatus: (jobId: string) => get(`/v1/connectors/jobs/${encodeURIComponent(jobId)}`), mappingSuggestions: (connectionId: string) => get(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/mapping/suggestions`), saveMapping: (connectionId: string, mapping: Record<string, string>) => post(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/mapping`, { mapping }), sync: (connectionId: string) => post(`/v1/connectors/connections/${encodeURIComponent(connectionId)}/sync`), delete: (connectionId: string) => remove(`/v1/connectors/connections/${encodeURIComponent(connectionId)}`) },
  controllers: { environments: () => get("/v1/controllers/environments"), dataContract: () => get("/v1/controllers/universal/data-contract"), executionReadiness: (workspaceId?: string) => get(`/v1/controllers/execution-readiness${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`), customerConnect: (payload: unknown) => post("/v1/controllers/customer-connect", payload), prepareExecution: (payload: unknown) => post("/v1/controllers/execution/prepare", payload) },
  integrations: { list: () => get("/v1/integrations"), status: () => get("/v1/integrations/status"), wiseconn: () => get("/v1/wiseconn/status"), talgil: () => get("/v1/talgil/status") },
  decisioning: { status: () => get("/v1/decisioning/status") },
  workbench: { status: () => get("/v1/workbench/status") },
  register: (payload: RegisterPayload) => apiClient.auth.register(payload), login: (payload: LoginPayload) => apiClient.auth.login(payload), logout: () => apiClient.auth.logout(), me: () => apiClient.auth.me(), getOrgs: () => apiClient.orgs.list(), getWorkspaces: () => apiClient.workspaces.list(), getBillingStatus: () => apiClient.billing.status(),
};
