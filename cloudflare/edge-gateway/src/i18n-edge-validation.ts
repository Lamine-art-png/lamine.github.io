import { matchesConfiguredToken } from "./queue-policy";

export type TranslationPayload = { locale?: unknown; source?: unknown };
export type LocaleEntry = { code?: unknown; name?: unknown };
export type ValidatedLocale = { code: string; name: string };

export const canarySource: Record<string, string> = {
  language: "Language",
  settings: "Settings",
  save: "Save",
  support: "Support",
};

export function bearerToken(request: Request): string {
  const value = request.headers.get("authorization") || "";
  return value.toLowerCase().startsWith("bearer ") ? value.slice(7).trim() : "";
}

export function canaryAuthorized(request: Request, expected: string): boolean {
  return matchesConfiguredToken(bearerToken(request), expected);
}

export function canonicalLocale(value: unknown, entries: LocaleEntry[]): ValidatedLocale | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().replace("_", "-").toLowerCase();
  for (const entry of entries) {
    if (typeof entry.code !== "string" || entry.code.toLowerCase() !== normalized) continue;
    return { code: entry.code, name: typeof entry.name === "string" ? entry.name : entry.code };
  }
  return null;
}

export function registryRequest(request: Request): Request {
  const url = new URL(request.url);
  url.pathname = "/v1/i18n/languages";
  url.search = "";
  const headers = new Headers(request.headers);
  headers.delete("content-length");
  headers.delete("content-type");
  return new Request(url.toString(), { method: "GET", headers, redirect: "manual" });
}

export function englishValidationRequest(request: Request, source: unknown, hasSource: boolean): Request {
  const headers = new Headers(request.headers);
  headers.delete("content-length");
  headers.set("content-type", "application/json");
  const payload: Record<string, unknown> = { locale: "en" };
  if (hasSource) payload.source = source;
  return new Request(request.url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    redirect: "manual",
  });
}

export function sourceObject(value: unknown): Record<string, string> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  if (!Object.keys(source).length || !Object.values(source).every((item) => typeof item === "string")) return null;
  return source as Record<string, string>;
}
