import type { Env } from "./env";

export interface RateLimitResult {
  allowed: boolean;
  code?: string;
  message?: string;
}

export async function checkRateLimit(_request: Request, _env: Env): Promise<RateLimitResult> {
  return { allowed: true };
}

