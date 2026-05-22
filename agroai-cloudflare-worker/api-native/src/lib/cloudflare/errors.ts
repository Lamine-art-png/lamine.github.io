import type { ApiErrorEnvelope, ErrorShape } from "../../schemas/common";

export const MAX_JSON_BYTES = 256 * 1024;

export function errorEnvelope(requestId: string, error: ErrorShape): ApiErrorEnvelope {
  return {
    ok: false,
    request_id: requestId,
    error,
  };
}

export function statusFromError(error: unknown): number {
  const status = (error as { status?: unknown })?.status;
  return typeof status === "number" ? status : 500;
}

export function codeFromError(error: unknown): string {
  const code = (error as { code?: unknown })?.code;
  if (typeof code === "string") return code;
  return statusFromError(error) >= 500 ? "internal_error" : "bad_request";
}

export function safeErrorMessage(error: unknown): string {
  const status = statusFromError(error);
  if (status >= 500) return "The request could not be completed.";
  return error instanceof Error ? error.message : "Invalid request.";
}

export async function readJsonBody(request: Request): Promise<unknown> {
  const contentLength = Number(request.headers.get("Content-Length") ?? "0");
  if (contentLength > MAX_JSON_BYTES) {
    throw Object.assign(new Error("Payload exceeds 256KB."), { code: "payload_too_large", status: 413 });
  }

  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_JSON_BYTES) {
    throw Object.assign(new Error("Payload exceeds 256KB."), { code: "payload_too_large", status: 413 });
  }
  if (!text.trim()) return {};

  try {
    return JSON.parse(text) as unknown;
  } catch (_error) {
    throw Object.assign(new Error("Request body must be valid JSON."), { code: "invalid_json", status: 400 });
  }
}

