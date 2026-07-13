export type RateLimitMetadata = {
  limit?: number;
  remaining?: number;
  reset?: number;
  retryAfter?: number;
};

const runtimeEnvironment = (globalThis as typeof globalThis & {
  process?: { env?: Record<string, string | undefined> };
}).process?.env ?? {};

export class AgroAIPlatformError extends Error {
  status?: number;
  code?: string;
  requestId?: string;
  constructor(message: string, options: { status?: number; code?: string; requestId?: string } = {}) {
    super(message);
    this.name = "AgroAIPlatformError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
  }
}

export class AgroAIPlatformClient {
  private apiKey: string;
  private baseUrl: string;
  private timeoutMs: number;

  constructor(options: { apiKey?: string; baseUrl?: string; timeoutMs?: number } = {}) {
    this.apiKey = options.apiKey || runtimeEnvironment.AGROAI_API_KEY || "";
    this.baseUrl = (options.baseUrl || runtimeEnvironment.AGROAI_BASE_URL || "https://api.agroai-pilot.com").replace(/\/$/, "");
    this.timeoutMs = options.timeoutMs || 20_000;
    if (!this.apiKey) throw new Error("AGROAI_API_KEY is required");
  }

  async me() {
    return this.request("GET", "/v1/platform/me");
  }

  async providers() {
    return this.request("GET", "/v1/platform/providers");
  }

  async planAction(actionType: string, options: { resourceId?: string; parameters?: Record<string, unknown>; idempotencyKey?: string } = {}) {
    return this.request("POST", "/v1/platform/actions/plan", {
      body: { action_type: actionType, resource_id: options.resourceId, parameters: options.parameters || {} },
      idempotencyKey: options.idempotencyKey || crypto.randomUUID(),
      retryIdempotentReads: false,
    });
  }

  private async request(method: string, path: string, options: { body?: unknown; idempotencyKey?: string; retryIdempotentReads?: boolean } = {}) {
    const attempts = method === "GET" && options.retryIdempotentReads !== false ? 2 : 1;
    let response: Response | undefined;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      try {
        response = await fetch(`${this.baseUrl}${path}`, {
          method,
          signal: controller.signal,
          headers: {
            Authorization: `Bearer ${this.apiKey}`,
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-Request-Id": `req_${crypto.randomUUID()}`,
            ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
          },
          body: options.body ? JSON.stringify(options.body) : undefined,
        });
      } finally {
        clearTimeout(timer);
      }
      if (response.status < 500 || attempt + 1 >= attempts) break;
    }
    if (!response) throw new AgroAIPlatformError("No response received");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === "object" && payload.detail ? payload.detail : payload;
      throw new AgroAIPlatformError(detail.message || "AGRO-AI Platform API request failed", {
        status: response.status,
        code: detail.code,
        requestId: detail.request_id,
      });
    }
    return { data: payload, rateLimit: rateLimit(response) };
  }
}

function rateLimit(response: Response): RateLimitMetadata {
  return {
    limit: numberHeader(response, "RateLimit-Limit"),
    remaining: numberHeader(response, "RateLimit-Remaining"),
    reset: numberHeader(response, "RateLimit-Reset"),
    retryAfter: numberHeader(response, "Retry-After"),
  };
}

function numberHeader(response: Response, name: string): number | undefined {
  const value = response.headers.get(name);
  return value && /^\d+$/.test(value) ? Number(value) : undefined;
}
