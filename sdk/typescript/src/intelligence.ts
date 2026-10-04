/**
 * AGRO-AI Intelligence SDK (server-side).
 *
 *   import { AgroAI } from "@agro-ai/platform";
 *   const client = new AgroAI({ apiKey: process.env.AGROAI_API_KEY });
 *   const result = await client.intelligence.run({
 *     question: "Why are the lower leaves yellowing?",
 *     task: "field_diagnosis",
 *     context: { crop: { name: "tomato", growth_stage: "fruit set" } },
 *     responseFormat: "diagnosis",
 *   });
 */

export type Task =
  | "answer"
  | "field_diagnosis"
  | "irrigation_plan"
  | "crop_risk"
  | "evidence_analysis"
  | "decision"
  | "report"
  | "integration_diagnosis"
  | "readiness_analysis";

export type BuiltinSchema =
  | "diagnosis"
  | "recommendations"
  | "risk_assessment"
  | "irrigation_schedule"
  | "financial_projection"
  | "compliance_findings"
  | "task_list"
  | "evidence_summary";

export type ResponseFormat =
  | BuiltinSchema
  | { type: "text" }
  | { type: "agroai_schema"; name: BuiltinSchema }
  | { type: "json_schema"; schema: Record<string, unknown>; name?: string; description?: string };

/** Shared agricultural context. Every section is optional; use `extensions` for anything not modelled. */
export type AgriculturalContext = {
  operation?: Record<string, unknown>;
  field?: Record<string, unknown>;
  crop?: { name?: string; variety?: string; season?: string; growth_stage?: string; planted_at?: string; [key: string]: unknown };
  location?: { latitude?: number; longitude?: number; region?: string; country?: string; geometry?: Record<string, unknown>; [key: string]: unknown };
  time_window?: { start?: string; end?: string; as_of?: string };
  observations?: Array<{ id?: string; type: string; value?: unknown; unit?: string; observed_at?: string; source?: string; confidence?: number; [key: string]: unknown }>;
  weather?: { source?: string; series: Array<Record<string, unknown>> };
  issues?: Array<Record<string, unknown>>;
  treatments?: Array<Record<string, unknown>>;
  equipment?: Array<Record<string, unknown>>;
  tasks?: Array<Record<string, unknown>>;
  harvest?: Record<string, unknown>;
  financial?: Record<string, unknown>;
  market?: Record<string, unknown>;
  sources?: Array<{ id: string; type?: string; label?: string; uri?: string; observed_at?: string }>;
  extensions?: Record<string, unknown>;
};

export type ToolCall = { name: string; arguments?: Record<string, unknown> };

export type RunParams = {
  question: string;
  task?: Task;
  input?: Record<string, unknown>;
  context?: AgriculturalContext;
  attachments?: Array<string | { file_id: string; label?: string }>;
  responseFormat?: ResponseFormat;
  tools?: ToolCall[];
  knowledge?: string[] | { collections: string[]; query?: string; max_results?: number };
  sessionId?: string;
  metadata?: Record<string, string>;
  fieldId?: string;
  workspaceId?: string;
  language?: string;
  idempotencyKey?: string;
};

export type IntelligenceResult = {
  id: string;
  object: "agroai.intelligence";
  model: "agroai-intelligence-1";
  status: "completed" | "degraded";
  task: Task;
  decision: unknown;
  output: Record<string, unknown>;
  confidence: string;
  risk_flags: unknown[];
  missing_data: unknown[];
  evidence: Array<Record<string, unknown>>;
  structured_output: Record<string, unknown> | null;
  structured_output_status: "not_requested" | "valid" | "invalid" | "unavailable" | "skipped";
  degraded_reasons?: string[];
  provenance?: Record<string, unknown>;
  session?: { id: string; turn_count: number | null } | null;
  usage?: Record<string, number>;
  billing: { price_cents: number; charged_cents: number; balance_cents: number; components?: Array<Record<string, unknown>> };
  request_id?: string;
  [key: string]: unknown;
};

export type Job = {
  id: string;
  object: "agroai.intelligence.job";
  status: "queued" | "running" | "completed" | "degraded" | "failed" | "canceled" | "timeout";
  result: IntelligenceResult | null;
  error: { code: string } | null;
  [key: string]: unknown;
};

export type StreamEvent = { event: string; data: any };

export class AgroAIError extends Error {
  status?: number;
  code?: string;
  requestId?: string;
  body?: unknown;
  constructor(message: string, options: { status?: number; code?: string; requestId?: string; body?: unknown } = {}) {
    super(message);
    this.name = "AgroAIError";
    Object.assign(this, options);
  }
}
export class APIConnectionError extends AgroAIError { override name = "APIConnectionError"; }
export class APITimeoutError extends APIConnectionError { override name = "APITimeoutError"; }
export class AuthenticationError extends AgroAIError { override name = "AuthenticationError"; }
export class InsufficientBalanceError extends AgroAIError { override name = "InsufficientBalanceError"; }
export class PermissionDeniedError extends AgroAIError { override name = "PermissionDeniedError"; }
export class NotFoundError extends AgroAIError { override name = "NotFoundError"; }
export class ConflictError extends AgroAIError { override name = "ConflictError"; }
export class UnprocessableEntityError extends AgroAIError { override name = "UnprocessableEntityError"; }
export class RateLimitError extends AgroAIError { override name = "RateLimitError"; }
export class InternalServerError extends AgroAIError { override name = "InternalServerError"; }

const ERRORS: Record<number, typeof AgroAIError> = {
  401: AuthenticationError,
  402: InsufficientBalanceError,
  403: PermissionDeniedError,
  404: NotFoundError,
  409: ConflictError,
  413: UnprocessableEntityError,
  415: UnprocessableEntityError,
  422: UnprocessableEntityError,
  429: RateLimitError,
};

function errorFor(status: number, payload: any, requestId?: string): AgroAIError {
  const detail = payload?.detail;
  if (Array.isArray(detail)) {
    return new UnprocessableEntityError(detail.map((item: any) => item?.msg).filter(Boolean).join("; ") || "Invalid request", {
      status, code: "request_validation_failed", requestId, body: detail,
    });
  }
  const info = detail && typeof detail === "object" ? detail : payload ?? {};
  const Cls = ERRORS[status] ?? (status >= 500 ? InternalServerError : AgroAIError);
  return new Cls(String(info.message ?? info.code ?? `AGRO-AI request failed with ${status}`), {
    status, code: info.code, requestId: info.request_id ?? requestId, body: info,
  });
}

const RETRY_STATUS = new Set([408, 429, 500, 502, 503, 504]);
const TERMINAL = new Set(["completed", "degraded", "failed", "canceled", "timeout"]);
const env = (globalThis as typeof globalThis & { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const newKey = () => `sdk-${crypto.randomUUID()}`;

function responseFormat(value: ResponseFormat | undefined): unknown {
  if (value === undefined) return undefined;
  return typeof value === "string" ? { type: "agroai_schema", name: value } : value;
}

export function buildRunBody(params: RunParams): Record<string, unknown> {
  const body: Record<string, unknown> = { task: params.task ?? "answer", question: params.question };
  const optional: Record<string, unknown> = {
    input: params.input,
    context: params.context,
    attachments: params.attachments?.map((item) => (typeof item === "string" ? { file_id: item } : item)),
    response_format: responseFormat(params.responseFormat),
    tools: params.tools,
    knowledge: Array.isArray(params.knowledge) ? { collections: params.knowledge } : params.knowledge,
    session_id: params.sessionId,
    metadata: params.metadata,
    field_id: params.fieldId,
    workspace_id: params.workspaceId,
    language: params.language,
  };
  for (const [key, value] of Object.entries(optional)) if (value !== undefined) body[key] = value;
  return body;
}

type RequestOptions = { body?: unknown; form?: FormData; query?: Record<string, string | number | undefined>; idempotencyKey?: string; accept?: string };

export class AgroAI {
  readonly intelligence: Intelligence;
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiKey?: string; baseUrl?: string; timeoutMs?: number; maxRetries?: number; fetch?: typeof fetch } = {}) {
    if (typeof window !== "undefined") {
      throw new Error("AgroAI is server-only; never embed an API key in browser code");
    }
    this.apiKey = options.apiKey || env.AGROAI_API_KEY || "";
    if (!this.apiKey) throw new AgroAIError("An AGRO-AI API key is required (apiKey or AGROAI_API_KEY)");
    this.baseUrl = (options.baseUrl || env.AGROAI_BASE_URL || "https://api.agroai-pilot.com").replace(/\/$/, "");
    this.timeoutMs = options.timeoutMs ?? 120_000;
    this.maxRetries = Math.max(0, options.maxRetries ?? 2);
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.intelligence = new Intelligence(this);
  }

  private url(path: string, query?: RequestOptions["query"]): string {
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [key, value] of Object.entries(query ?? {})) if (value !== undefined) url.searchParams.set(key, String(value));
    return url.toString();
  }

  private headers(options: RequestOptions): Record<string, string> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      Accept: options.accept ?? "application/json",
      "X-Request-Id": `sdk_${crypto.randomUUID().replace(/-/g, "")}`,
    };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
    return headers;
  }

  private async send(method: string, path: string, options: RequestOptions): Promise<Response> {
    // Writes retry only with an Idempotency-Key: the server deduplicates, so a
    // retried paid request is never charged twice.
    const retryable = method === "GET" || method === "DELETE" || Boolean(options.idempotencyKey);
    const attempts = 1 + (retryable ? this.maxRetries : 0);
    for (let attempt = 0; ; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let response: Response;
      try {
        response = await this.fetchImpl(this.url(path, options.query), {
          method,
          headers: this.headers(options),
          body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
          signal: controller.signal,
        });
      } catch (error) {
        clearTimeout(timer);
        if (attempt + 1 < attempts) { await sleep(this.backoff(attempt)); continue; }
        if ((error as { name?: string })?.name === "AbortError") throw new APITimeoutError("Request to AGRO-AI timed out");
        throw new APIConnectionError(`Could not reach AGRO-AI: ${String(error)}`);
      }
      clearTimeout(timer);
      if (attempt + 1 < attempts && (RETRY_STATUS.has(response.status) || (response.status === 409 && (await this.inProgress(response))))) {
        const retryAfter = Number(response.headers.get("Retry-After"));
        await sleep(Number.isFinite(retryAfter) && retryAfter > 0 ? Math.min(retryAfter, 30) * 1000 : this.backoff(attempt));
        continue;
      }
      return response;
    }
  }

  private async inProgress(response: Response): Promise<boolean> {
    try {
      const payload = await response.clone().json();
      return payload?.detail?.code === "intelligence_run_in_progress";
    } catch {
      return false;
    }
  }

  private backoff(attempt: number): number {
    return Math.min(8_000, 500 * 2 ** attempt) * (0.75 + Math.random() / 2);
  }

  /** @internal */
  async request<T = any>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const response = await this.send(method, path, options);
    const requestId = response.headers.get("X-Request-Id") ?? undefined;
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    let payload: any = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new AgroAIError(`Invalid JSON from AGRO-AI (${response.status})`, { status: response.status, requestId });
    }
    if (!response.ok) throw errorFor(response.status, payload, requestId);
    return payload as T;
  }

  /** @internal */
  async *stream(path: string, body: unknown, idempotencyKey: string): AsyncGenerator<StreamEvent> {
    const response = await this.send("POST", path, { body, idempotencyKey, accept: "text/event-stream" });
    if (!response.ok) {
      const text = await response.text();
      let payload: any = {};
      try { payload = JSON.parse(text); } catch { /* keep empty */ }
      throw errorFor(response.status, payload, response.headers.get("X-Request-Id") ?? undefined);
    }
    if (!response.body) return;
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    let event = "message";
    let data: string[] = [];
    for (;;) {
      const { value, done } = await reader.read();
      if (value) buffer += value;
      let newline: number;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, "");
        buffer = buffer.slice(newline + 1);
        if (line === "") {
          if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
          event = "message";
          data = [];
        } else if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (done) break;
    }
    if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
  }
}

class Intelligence {
  readonly jobs: Jobs;
  readonly sessions: Sessions;
  readonly files: Files;
  readonly knowledge: Knowledge;
  readonly tools: Tools;
  readonly runs: Runs;
  constructor(private readonly client: AgroAI) {
    this.jobs = new Jobs(client);
    this.sessions = new Sessions(client);
    this.files = new Files(client);
    this.knowledge = new Knowledge(client);
    this.tools = new Tools(client);
    this.runs = new Runs(client);
  }
  run(params: RunParams): Promise<IntelligenceResult> {
    return this.client.request("POST", "/v1/intelligence", { body: buildRunBody(params), idempotencyKey: params.idempotencyKey ?? newKey() });
  }
  stream(params: RunParams): AsyncGenerator<StreamEvent> {
    return this.client.stream("/v1/intelligence", { ...buildRunBody(params), stream: true }, params.idempotencyKey ?? newKey());
  }
  pricing() { return this.client.request("GET", "/v1/intelligence/pricing"); }
  capabilities() { return this.client.request("GET", "/v1/intelligence/capabilities"); }
  usage(days = 30) { return this.client.request("GET", "/v1/intelligence/usage", { query: { days } }); }
}

class Jobs {
  constructor(private readonly client: AgroAI) {}
  create(params: RunParams): Promise<Job> {
    return this.client.request("POST", "/v1/intelligence/jobs", { body: buildRunBody(params), idempotencyKey: params.idempotencyKey ?? newKey() });
  }
  retrieve(id: string): Promise<Job> { return this.client.request("GET", `/v1/intelligence/jobs/${encodeURIComponent(id)}`); }
  list(options: { status?: Job["status"]; limit?: number } = {}) { return this.client.request("GET", "/v1/intelligence/jobs", { query: options }); }
  cancel(id: string): Promise<Job> { return this.client.request("POST", `/v1/intelligence/jobs/${encodeURIComponent(id)}/cancel`); }
  async wait(id: string, options: { timeoutMs?: number; pollIntervalMs?: number } = {}): Promise<Job> {
    const deadline = Date.now() + (options.timeoutMs ?? 600_000);
    for (;;) {
      const job = await this.retrieve(id);
      if (TERMINAL.has(job.status)) return job;
      if (Date.now() >= deadline) throw new APITimeoutError(`Job ${id} did not finish in time (status=${job.status})`);
      await sleep(options.pollIntervalMs ?? 2_000);
    }
  }
}

class Sessions {
  constructor(private readonly client: AgroAI) {}
  create(params: { title?: string; context?: AgriculturalContext; metadata?: Record<string, string>; retention_days?: number } = {}) {
    return this.client.request("POST", "/v1/intelligence/sessions", { body: params });
  }
  retrieve(id: string) { return this.client.request("GET", `/v1/intelligence/sessions/${encodeURIComponent(id)}`); }
  update(id: string, changes: { title?: string; context?: AgriculturalContext; metadata?: Record<string, string> }) {
    return this.client.request("PATCH", `/v1/intelligence/sessions/${encodeURIComponent(id)}`, { body: changes });
  }
  list(limit = 20) { return this.client.request("GET", "/v1/intelligence/sessions", { query: { limit } }); }
  turns(id: string, limit = 50) { return this.client.request("GET", `/v1/intelligence/sessions/${encodeURIComponent(id)}/turns`, { query: { limit } }); }
  delete(id: string) { return this.client.request("DELETE", `/v1/intelligence/sessions/${encodeURIComponent(id)}`); }
}

class Files {
  constructor(private readonly client: AgroAI) {}
  upload(content: Blob | Uint8Array | ArrayBuffer, options: { filename: string; contentType: string; purpose?: "attachment" | "knowledge" }) {
    const form = new FormData();
    // Always re-wrap with the requested type: FormData takes the part's MIME
    // type from the Blob, and an existing Blob's own type may be empty.
    const blob = new Blob([content as BlobPart], { type: options.contentType });
    form.set("file", blob, options.filename);
    form.set("purpose", options.purpose ?? "attachment");
    return this.client.request("POST", "/v1/intelligence/files", { form });
  }
  retrieve(id: string) { return this.client.request("GET", `/v1/intelligence/files/${encodeURIComponent(id)}`); }
  list(limit = 50) { return this.client.request("GET", "/v1/intelligence/files", { query: { limit } }); }
  delete(id: string) { return this.client.request("DELETE", `/v1/intelligence/files/${encodeURIComponent(id)}`); }
}

class Knowledge {
  constructor(private readonly client: AgroAI) {}
  add(document: { collection: string; title: string; text?: string; file_id?: string; external_id?: string; source?: Record<string, unknown>; observed_at?: string; metadata?: Record<string, string> }) {
    return this.client.request("POST", "/v1/intelligence/knowledge/documents", { body: document });
  }
  search(query: string, options: { collections: string[]; maxResults?: number }) {
    return this.client.request("POST", "/v1/intelligence/knowledge/search", { body: { query, collections: options.collections, max_results: options.maxResults ?? 6 } });
  }
  list(options: { collection?: string; limit?: number } = {}) { return this.client.request("GET", "/v1/intelligence/knowledge/documents", { query: options }); }
  collections() { return this.client.request("GET", "/v1/intelligence/knowledge/collections"); }
  retrieve(id: string) { return this.client.request("GET", `/v1/intelligence/knowledge/documents/${encodeURIComponent(id)}`); }
  delete(id: string) { return this.client.request("DELETE", `/v1/intelligence/knowledge/documents/${encodeURIComponent(id)}`); }
}

class Tools {
  constructor(private readonly client: AgroAI) {}
  list() { return this.client.request("GET", "/v1/intelligence/tools"); }
  execute(name: string, args: Record<string, unknown>) {
    return this.client.request("POST", "/v1/intelligence/tools/execute", { body: { name, arguments: args } });
  }
}

class Runs {
  constructor(private readonly client: AgroAI) {}
  retrieve(id: string) { return this.client.request("GET", `/v1/intelligence/runs/${encodeURIComponent(id)}`); }
  /** One page of runs, newest first. Pass the previous page's `next_before` as `before`. */
  list(options: { limit?: number; execution?: "sync" | "async"; before?: string } = {}) { return this.client.request("GET", "/v1/intelligence/runs", { query: options }); }
}
