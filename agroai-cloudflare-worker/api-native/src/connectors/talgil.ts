/**
 * Talgil REST API client — aligned with rest.api.external v1.47
 *
 * Endpoints:
 *   GET /mytargets                                       → list controllers
 *   GET /targets/{id}/                                   → full controller image
 *   GET /targets/{id}/?filter=...                        → filtered controller image
 *   GET /targets/{id}/sensors/{sid}/log?from=&until=&otype= → per-sensor historical log
 *   GET /targets/{id}/eventlog?from=&until=              → event log
 *   GET /targets/{id}/wc/valves?from=&until=&rate=       → valve water consumption
 *
 * Key partner guidance (Kosta):
 *   - Do NOT call /targets/{id}/sensors separately; sensors are in full image.
 *   - Do NOT call /mytargets on every sync; call once during connect.
 *   - Do NOT request logs every minute; historical is a batch process.
 *   - Use filtered full image to reduce traffic.
 *   - Minimum intervals: live 1s, log 15s, eventlog 15s, wc 60s, fert 60s.
 *   - Recommended live cadence: 15–20 minutes.
 *
 * Simulator date range (dev environment):
 *   2026-02-22 00:00:00 UTC  →  1740182400000 ms
 *   2026-03-10 23:59:59 UTC  →  1741651199000 ms
 */

// ── Types ───────────────────────────────────────────────

export interface TalgilTarget {
  serial?: number;
  ID?: number;
  id?: number;
  name?: string;
  Name?: string;
  affiliate?: string;
  project?: string;
  online?: number;
  Online?: number;
  [key: string]: unknown;
}

export interface TalgilFullImage {
  ID?: number;
  id?: number;
  Name?: string;
  name?: string;
  Online?: number;
  online?: number;
  info?: Record<string, unknown>;
  state?: TalgilControllerState;
  sensors?: TalgilSensorEntry[];
  Sensors?: TalgilSensorEntry[];
  lines?: unknown[];
  groups?: unknown[];
  programs?: unknown[];
  waterMeters?: unknown[];
  valves?: unknown[];
  filterSites?: unknown[];
  fertSites?: unknown[];
  freeWaterMeters?: unknown[];
  weather?: unknown;
  [key: string]: unknown;
}

export interface TalgilControllerState {
  online?: number;
  time?: number;
  configTime?: number;
  resetTime?: number;
  alarms?: number;
  irrigationState?: number;
  flushingState?: number;
  communicationState?: number;
  hardwareState?: number;
  acState?: number;
  modemState?: number;
  rssi?: number;
  flow?: number;
  freezeReason?: number;
  today?: number;
  [key: string]: unknown;
}

export interface TalgilSensorEntry {
  uid?: string;
  UID?: string;
  name?: string;
  Name?: string;
  state?: number;
  online?: number;
  card?: number;
  rtu?: number;
  plugin?: number;
  mbu?: number;
  input?: number;
  type?: string | number;
  Type?: string;
  units?: string;
  Units?: string;
  base?: number;
  minLimit?: number;
  maxLimit?: number;
  lowThreshold?: number;
  highThreshold?: number;
  readingDelay?: number;
  readingRate?: number;
  dataSource?: number;
  value?: number;
  Value?: number;
  updateTime?: number;
  calculationType?: number;
  unitsDescriptor?: string;
  davis?: unknown;
  baseSensor?: unknown;
  [key: string]: unknown;
}

export interface TalgilSensorLogEntry {
  uid?: string;
  UID?: string;
  time?: number;
  Time?: number;
  value?: number;
  Value?: number;
  otype?: number;
  [key: string]: unknown;
}

export interface TalgilEventLogEntry {
  time?: number;
  Time?: number;
  context?: string;
  subcontext?: string;
  message?: string;
  // Legacy field names (in case API uses them)
  Type?: string;
  Source?: string;
  [key: string]: unknown;
}

/** Water consumption response: object keyed by valve uid → array of buckets */
export interface TalgilWcResponse {
  [valveUid: string]: TalgilWcBucket[];
}

export interface TalgilWcBucket {
  from?: number;
  until?: number;
  value?: number;
  valuePerArea?: number;
  [key: string]: unknown;
}

export interface TalgilApiResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  url: string;
  error?: string;
}

// ── Simulator boundaries ────────────────────────────────

export const SIMULATOR_FROM_MS = 1771718400000; // 2026-02-22T00:00:00Z
export const SIMULATOR_UNTIL_MS = 1773187199000; // 2026-03-10T23:59:59Z

// ── Rate-aware maximum DB query ranges (behavior guidelines v8) ───

export const MAX_RANGE_BY_RATE: Record<string, number> = {
  hourly:  7   * 86_400_000,   // 7 days
  daily:   31  * 86_400_000,   // 31 days
  weekly:  184 * 86_400_000,   // 184 days
  monthly: 366 * 86_400_000,   // 366 days
  yearly:  731 * 86_400_000,   // 731 days
  none:    92  * 86_400_000,   // 92 days
};

// ── Minimum intervals between requests (ms) ─────────────

export const MIN_INTERVAL = {
  live_get:       1_000,
  live_post:      1_000,
  live_post_mod:  2_000,
  live_post_batch: 15_000,
  db_log:         15_000,
  db_event_log:   15_000,
  db_program_log: 15_000,
  db_wc:          60_000,
  db_fert:        60_000,
} as const;

// ── Default filter for operational sync ──────────────────
// Uses the API's filtering support to request only needed containers + fields.
// Pattern: GET /targets/{id}/?filter=container1|container2|field1|field2

export const SYNC_FILTER = "sensors|uid|name|type|units|value|updateTime|state|online";
export const FULL_FILTER = "info|state|sensors|lines|waterMeters|valves|programs|uid|name|type|units|value|updateTime|online|area|flow|acc|accTime";

// ── Rate limiter ────────────────────────────────────────
// Enforces minimum spacing between consecutive API calls to Talgil.
// The API returns "not allowed" if requests come too quickly.

let lastRequestTime = 0;

/**
 * Wait until at least `minGapMs` has elapsed since the last request.
 * Default gap: 2 seconds (live GET minimum is 1s, with safety margin).
 */
async function enforceRateLimit(minGapMs: number = 2000): Promise<void> {
  const now = Date.now();
  const elapsed = now - lastRequestTime;
  if (elapsed < minGapMs) {
    await new Promise((r) => setTimeout(r, minGapMs - elapsed));
  }
  lastRequestTime = Date.now();
}

// ── HTTP helper ─────────────────────────────────────────

async function talgilFetch<T>(
  baseUrl: string,
  path: string,
  apiKey: string,
  maxRetries: number = 2,
  minGapMs: number = 2000,
): Promise<TalgilApiResult<T>> {
  const url = `${baseUrl}${path}`;

  // Enforce minimum spacing between requests
  await enforceRateLimit(minGapMs);

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(url, {
        method: "GET",
        headers: {
          "TLG-API-Key": apiKey,
          Accept: "application/json",
        },
      });

      // Only retry on 429 (rate limited) — respect Retry-After header
      if (res.status === 429 && attempt < maxRetries) {
        const retryAfter = res.headers.get("Retry-After");
        // Default wait: use the minGapMs (which already includes the rate limit)
        const waitMs = retryAfter
          ? Math.max(parseInt(retryAfter, 10) * 1000, minGapMs)
          : minGapMs;
        await new Promise((r) => setTimeout(r, waitMs));
        lastRequestTime = Date.now();
        continue;
      }

      // All other HTTP errors: return immediately, do NOT retry.
      // Retrying 400/403/404/500 would just generate "not allowed" warnings.
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        return {
          ok: false,
          status: res.status,
          data: null,
          url,
          error: `HTTP ${res.status}: ${body.slice(0, 500)}`,
        };
      }

      const data = (await res.json()) as T;
      return { ok: true, status: res.status, data, url };
    } catch (err) {
      // Network errors (no HTTP response): retry with rate-limit-safe delay
      if (attempt < maxRetries) {
        await new Promise((r) => setTimeout(r, minGapMs));
        lastRequestTime = Date.now();
        continue;
      }
      return {
        ok: false,
        status: 0,
        data: null,
        url,
        error: `Network error: ${(err as Error).message}`,
      };
    }
  }

  return { ok: false, status: 0, data: null, url, error: "Max retries exhausted" };
}

// ── Public API functions ────────────────────────────────

/**
 * GET /mytargets
 * Called ONCE during connect to discover controller IDs.
 * Returns list of controllers linked to the API key account.
 * Response includes: serial, name, affiliate, project, online.
 */
export function talgilListTargets(
  baseUrl: string,
  apiKey: string,
): Promise<TalgilApiResult<TalgilTarget[]>> {
  return talgilFetch<TalgilTarget[]>(baseUrl, "/mytargets", apiKey);
}

/**
 * GET /targets/{id}/
 * Full controller image — the PRIMARY sync endpoint.
 * Contains sensors, valves, lines, programs, status, and metadata.
 * Called every 20 minutes during operational sync.
 */
export function talgilGetFullImage(
  baseUrl: string,
  apiKey: string,
  controllerId: number,
): Promise<TalgilApiResult<TalgilFullImage>> {
  return talgilFetch<TalgilFullImage>(
    baseUrl,
    `/targets/${controllerId}/`,
    apiKey,
  );
}

/**
 * GET /targets/{id}/?filter=...
 * Filtered controller image — reduces traffic by requesting only needed
 * containers and fields. Per API v1.47, almost every GET supports filtering.
 *
 * Example: /targets/6115/?filter=sensors|uid|name|type|units|value|updateTime
 */
export function talgilGetFilteredImage(
  baseUrl: string,
  apiKey: string,
  controllerId: number,
  filter: string,
): Promise<TalgilApiResult<TalgilFullImage>> {
  return talgilFetch<TalgilFullImage>(
    baseUrl,
    `/targets/${controllerId}/?filter=${encodeURIComponent(filter)}`,
    apiKey,
  );
}

/**
 * GET /targets/{id}/sensors/{numericId}/log?from={ms}&until={ms}&otype={n}
 * Per-sensor historical log — BATCH PROCESS ONLY.
 * Must respect 15-second minimum interval between calls.
 * Must stay within simulator date range for dev environment.
 *
 * IMPORTANT:
 * - The API expects the numeric sensor index (e.g. 33), NOT the full UID (31:33).
 * - The otype parameter is REQUIRED. For analog sensors (UID prefix 31), otype=2.
 */

// Map UID prefix to otype value for the sensor log API
const UID_PREFIX_TO_OTYPE: Record<string, number> = {
  "31": 2, // analog sensors
};

export function talgilGetSensorLog(
  baseUrl: string,
  apiKey: string,
  controllerId: number,
  sensorUid: string,
  fromMs: number,
  untilMs: number,
): Promise<TalgilApiResult<TalgilSensorLogEntry[]>> {
  // Extract numeric index from UID "31:33" → "33", and otype from prefix "31" → 2
  const parts = sensorUid.split(":");
  const numericId = parts.length > 1 ? parts[1] : parts[0];
  const otype = UID_PREFIX_TO_OTYPE[parts[0]] ?? 2;
  return talgilFetch<TalgilSensorLogEntry[]>(
    baseUrl,
    `/targets/${controllerId}/sensors/${numericId}/log?from=${fromMs}&until=${untilMs}&otype=${otype}`,
    apiKey,
    3,
    MIN_INTERVAL.db_log + 1000, // 16s between log requests
  );
}

/**
 * GET /targets/{id}/eventlog?from={ms}&until={ms}
 * Event log — returns array of {time, context, subcontext, message}.
 * Message is in caller's language.
 * Kept for at least 3 months.
 * Must respect 15-second minimum interval between calls.
 * DISABLED by default until dev account permissions confirmed.
 */
export function talgilGetEventLog(
  baseUrl: string,
  apiKey: string,
  controllerId: number,
  fromMs: number,
  untilMs: number,
): Promise<TalgilApiResult<TalgilEventLogEntry[]>> {
  return talgilFetch<TalgilEventLogEntry[]>(
    baseUrl,
    `/targets/${controllerId}/eventlog?from=${fromMs}&until=${untilMs}`,
    apiKey,
    3,
    MIN_INTERVAL.db_event_log + 1000, // 16s between event log requests
  );
}

/**
 * GET /targets/{id}/wc/valves?from={ms}&until={ms}&rate=daily
 * Water consumption — returns object keyed by valve uid.
 * Optional vids param for specific valves (comma-separated, format: line.valve or IDD 11:1).
 * Optional volume=true/false.
 * Must respect 60-second minimum interval between calls.
 * DISABLED by default until dev account permissions confirmed.
 */
export function talgilGetWaterConsumption(
  baseUrl: string,
  apiKey: string,
  controllerId: number,
  fromMs: number,
  untilMs: number,
  rate: string = "daily",
  vids?: string,
): Promise<TalgilApiResult<TalgilWcResponse>> {
  let path = `/targets/${controllerId}/wc/valves?from=${fromMs}&until=${untilMs}&rate=${rate}`;
  if (vids) path += `&vids=${encodeURIComponent(vids)}`;
  return talgilFetch<TalgilWcResponse>(baseUrl, path, apiKey, 3, MIN_INTERVAL.db_wc + 1000); // 61s between wc requests
}

// ── Helpers ─────────────────────────────────────────────

/**
 * Normalize sensor entry field names.
 * The API may return PascalCase or camelCase depending on context.
 */
export function normalizeSensorUid(entry: TalgilSensorEntry): string | undefined {
  return entry.uid ?? entry.UID;
}

export function normalizeSensorName(entry: TalgilSensorEntry): string | undefined {
  return entry.name ?? entry.Name;
}

export function normalizeSensorValue(entry: TalgilSensorEntry): number | undefined {
  return entry.value ?? entry.Value;
}

/**
 * Extract sensors array from full image, handling case variations.
 */
export function extractSensors(image: TalgilFullImage): TalgilSensorEntry[] {
  return image.sensors ?? image.Sensors ?? [];
}

/**
 * Extract controller ID from full image.
 */
export function extractControllerId(image: TalgilFullImage): number {
  return image.ID ?? image.id ?? 0;
}

/**
 * Extract controller name from target or image.
 */
export function extractControllerName(obj: TalgilTarget | TalgilFullImage): string {
  return (obj.name ?? obj.Name ?? "Unknown") as string;
}

/**
 * Extract online status from target or image.
 */
export function extractOnlineStatus(obj: TalgilTarget | TalgilFullImage): number {
  return (obj.online ?? obj.Online ?? 0) as number;
}

/**
 * Clamp a date range to the simulator boundaries.
 * Returns null if the clamped range is empty.
 */
export function clampToSimulatorRange(
  fromMs: number,
  untilMs: number,
): { from: number; until: number } | null {
  const clampedFrom = Math.max(fromMs, SIMULATOR_FROM_MS);
  const clampedUntil = Math.min(untilMs, SIMULATOR_UNTIL_MS);
  if (clampedFrom >= clampedUntil) return null;
  return { from: clampedFrom, until: clampedUntil };
}

/**
 * Chunk a date range into smaller windows respecting rate-based max range.
 */
export function chunkDateRange(
  fromMs: number,
  untilMs: number,
  rate: string = "none",
): Array<{ from: number; until: number }> {
  const maxRange = MAX_RANGE_BY_RATE[rate] ?? MAX_RANGE_BY_RATE.none;
  const chunks: Array<{ from: number; until: number }> = [];
  let cursor = fromMs;
  while (cursor < untilMs) {
    const chunkEnd = Math.min(cursor + maxRange, untilMs);
    chunks.push({ from: cursor, until: chunkEnd });
    cursor = chunkEnd;
  }
  return chunks;
}

/**
 * Differentiate error types for better diagnostics.
 */
export function diagnoseError(status: number): string {
  switch (status) {
    case 0:   return "Network error: request may not have reached Talgil server.";
    case 400: return "Bad request: malformed URL or parameters.";
    case 401: return "Unauthorized: API key may be invalid or expired.";
    case 403: return "Forbidden: account may lack permission for this endpoint/controller. Confirm with Kosta.";
    case 404: return "Not found: endpoint or controller ID may be incorrect.";
    case 405: return "Method not allowed: check HTTP method (GET vs POST).";
    case 415: return "Unsupported media type: check Content-Type header.";
    case 500: return "Talgil server error: retry later or contact support.";
    default:  return `Unexpected HTTP ${status}. Check URL construction and permissions.`;
  }
}
