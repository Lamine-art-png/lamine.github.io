export type RateLimitMetadata = {
  limit?: number;
  remaining?: number;
  reset?: number;
  retryAfter?: number;
};

export type ApiResponse<T> = {
  data: T;
  requestId?: string;
  rateLimit: RateLimitMetadata;
};

type RequestOptions = {
  body?: unknown;
  idempotencyKey?: string;
  query?: Record<string, string | number | undefined>;
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
    Object.assign(this, options);
  }
}

export class AgroAIPlatformClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(options: { apiKey?: string; baseUrl?: string; timeoutMs?: number } = {}) {
    if (typeof window !== "undefined") {
      throw new Error("AgroAIPlatformClient is server-only; never embed an API key in browser code");
    }
    this.apiKey = options.apiKey || runtimeEnvironment.AGROAI_API_KEY || "";
    this.baseUrl = (options.baseUrl || runtimeEnvironment.AGROAI_BASE_URL || "https://api.agroai-pilot.com").replace(/\/$/, "");
    this.timeoutMs = options.timeoutMs || 20_000;
    if (!this.apiKey) throw new Error("AGROAI_API_KEY is required");
  }

  me() {
    return this.request<Record<string, unknown>>("GET", "/v1/platform/me");
  }

  usage() {
    return this.request<Record<string, unknown>>("GET", "/v1/platform/usage");
  }

  listFields(options: { cursor?: string; limit?: number } = {}) {
    return this.request<{ items: Record<string, unknown>[]; next_cursor?: string }>("GET", "/v1/platform/fields", {
      query: { cursor: options.cursor, limit: options.limit || 50 },
    });
  }

  async *fields(options: { pageSize?: number } = {}) {
    let cursor: string | undefined;
    do {
      const page = await this.listFields({ cursor, limit: options.pageSize || 50 });
      for (const item of page.data.items || []) yield item;
      cursor = page.data.next_cursor;
    } while (cursor);
  }

  createField(payload: Record<string, unknown>, options: { idempotencyKey?: string } = {}) {
    return this.request<Record<string, unknown>>("POST", "/v1/platform/fields", {
      body: payload,
      idempotencyKey: options.idempotencyKey || crypto.randomUUID(),
    });
  }

  initiateUpload(payload: { filename: string; content_type: string; size_bytes: number; sha256: string }) {
    return this.request<Record<string, unknown>>("POST", "/v1/platform/sources/uploads", {
      body: payload,
      idempotencyKey: crypto.randomUUID(),
    });
  }

  async upload(uploadUrl: string, body: BodyInit, contentType: string) {
    const response = await fetch(uploadUrl, { method: "PUT", body, headers: { "Content-Type": contentType } });
    if (!response.ok) throw new AgroAIPlatformError(`Upload failed with status ${response.status}`, { status: response.status });
  }

  job(jobId: string) {
    return this.request<{ job: { status: string } }>("GET", `/v1/platform/jobs/${encodeURIComponent(jobId)}`);
  }

  async pollJob(jobId: string, options: { timeoutMs?: number; intervalMs?: number } = {}) {
    const deadline = Date.now() + (options.timeoutMs || 120_000);
    while (Date.now() < deadline) {
      const result = await this.job(jobId);
      if (["succeeded", "failed", "cancelled"].includes(result.data.job.status)) return result;
      await new Promise((resolve) => setTimeout(resolve, options.intervalMs || 1_000));
    }
    throw new Error(`job ${jobId} did not finish before the polling timeout`);
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
    const requestId = `req_${crypto.randomUUID()}`;
    const query = new URLSearchParams();
    Object.entries(options.query || {}).forEach(([key, value]) => {
      if (value !== undefined) query.set(key, String(value));
    });
    const url = `${this.baseUrl}${path}${query.size ? `?${query}` : ""}`;
    const attempts = ["GET", "HEAD"].includes(method.toUpperCase()) ? 3 : 1;
    let response: Response | undefined;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      try {
        response = await fetch(url, {
          method,
          signal: controller.signal,
          headers: {
            Authorization: `Bearer ${this.apiKey}`,
            Accept: "application/json",
            ...(options.body ? { "Content-Type": "application/json" } : {}),
            "X-Request-Id": requestId,
            ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
          },
          body: options.body ? JSON.stringify(options.body) : undefined,
        });
      } finally {
        clearTimeout(timer);
      }
      if (![429, 500, 502, 503, 504].includes(response.status) || attempt + 1 >= attempts) break;
      await new Promise((resolve) => setTimeout(resolve, Math.min(2_000, 250 * 2 ** attempt)));
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
    return {
      data: payload as T,
      requestId: response.headers.get("X-Request-Id") || requestId,
      rateLimit: rateLimit(response),
    };
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
