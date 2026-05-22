import type { Env } from "./env";

const DEFAULT_ALLOWED_ORIGINS = [
  "https://app.agroai-pilot.com",
  "https://agroai-portal.pages.dev",
  "http://localhost:4173",
  "http://127.0.0.1:4173",
];

export function allowedOrigins(env: Pick<Env, "ALLOWED_ORIGINS">): string[] {
  return (env.ALLOWED_ORIGINS ?? DEFAULT_ALLOWED_ORIGINS.join(","))
    .split(",")
    .map((origin) => origin.trim())
    .filter((origin) => origin.length > 0 && origin !== "*");
}

export function corsHeaders(request: Request, env: Pick<Env, "ALLOWED_ORIGINS">): Headers {
  const headers = new Headers();
  const origin = request.headers.get("Origin");
  if (origin && allowedOrigins(env).includes(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Credentials", "false");
  }
  headers.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  headers.set("Access-Control-Allow-Headers", "content-type,x-request-id");
  headers.set("Access-Control-Max-Age", "86400");
  headers.set("Vary", "Origin");
  return headers;
}

export function preflightResponse(request: Request, env: Pick<Env, "ALLOWED_ORIGINS">, requestId: string): Response {
  const headers = corsHeaders(request, env);
  headers.set("X-Request-Id", requestId);
  return new Response(null, { status: 204, headers });
}

export function attachCors(response: Response, request: Request, env: Pick<Env, "ALLOWED_ORIGINS">, requestId: string): Response {
  const headers = new Headers(response.headers);
  for (const [key, value] of corsHeaders(request, env).entries()) {
    headers.set(key, value);
  }
  headers.set("X-Request-Id", requestId);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

