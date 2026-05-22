export type EarthDailyMode = "demo" | "live";
export type EarthDailyProvider = "earthdaily";

export interface ErrorShape {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiEnvelope<T> {
  ok: true;
  request_id: string;
  provider: EarthDailyProvider;
  mode: EarthDailyMode;
  data: T;
}

export interface ApiErrorEnvelope {
  ok: false;
  request_id: string;
  error: ErrorShape;
}

export interface RequestContext {
  request_id: string;
  provider: EarthDailyProvider;
  mode: EarthDailyMode;
  started_at: number;
  origin?: string;
  ip?: string;
}

export interface ValidationIssue {
  path: string;
  message: string;
  code: string;
}

export interface ValidationResult<T> {
  ok: boolean;
  value?: T;
  issues: ValidationIssue[];
}

export function validationOk<T>(value: T): ValidationResult<T> {
  return { ok: true, value, issues: [] };
}

export function validationError<T = never>(issues: ValidationIssue[]): ValidationResult<T> {
  return { ok: false, issues };
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function hasInvalidNumber(value: unknown): boolean {
  if (typeof value === "number") return !Number.isFinite(value);
  if (Array.isArray(value)) return value.some(hasInvalidNumber);
  if (!isRecord(value)) return false;
  return Object.values(value).some(hasInvalidNumber);
}

export function requireRecord(
  parent: Record<string, unknown>,
  key: string,
  path: string,
  issues: ValidationIssue[],
): Record<string, unknown> | null {
  const value = parent[key];
  if (!isRecord(value)) {
    issues.push({ path, message: `${path} is required`, code: "missing_required" });
    return null;
  }
  return value;
}

export function requireArray(
  parent: Record<string, unknown>,
  key: string,
  path: string,
  issues: ValidationIssue[],
): unknown[] | null {
  const value = parent[key];
  if (!Array.isArray(value)) {
    issues.push({ path, message: `${path} must be an array`, code: "missing_required" });
    return null;
  }
  return value;
}

export function requireString(
  parent: Record<string, unknown>,
  key: string,
  path: string,
  issues: ValidationIssue[],
): string | null {
  const value = parent[key];
  if (typeof value !== "string" || value.length === 0) {
    issues.push({ path, message: `${path} must be a non-empty string`, code: "missing_required" });
    return null;
  }
  return value;
}

export function requireNumber(
  parent: Record<string, unknown>,
  key: string,
  path: string,
  issues: ValidationIssue[],
): number | null {
  const value = parent[key];
  if (!isFiniteNumber(value)) {
    issues.push({ path, message: `${path} must be a finite number`, code: "invalid_number" });
    return null;
  }
  return value;
}

export function optionalString(
  parent: Record<string, unknown>,
  key: string,
  path: string,
  issues: ValidationIssue[],
): void {
  const value = parent[key];
  if (value !== undefined && typeof value !== "string") {
    issues.push({ path, message: `${path} must be a string when provided`, code: "invalid_type" });
  }
}

