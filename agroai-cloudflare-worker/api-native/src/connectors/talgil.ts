/**
 * Talgil REST API client.
 *
 * Endpoints per rest.api.external 1.47:
 *   GET /mytargets                              → list controllers
 *   GET /targets/{id}/                          → full controller image (includes sensors)
 *   GET /targets/{id}/sensors/log?from=&until=  → historical sensor log
 *   GET /targets/{id}/eventlog?from=&until=     → event log
 *   GET /targets/{id}/wc/valves?from=&until=&rate= → water consumption
 *
 * Key partner guidance (Kosta):
 *   - Do NOT call /targets/{id}/sensors separately; sensors are in full image.
 *   - Do NOT call /mytargets on every sync; call once during connect.
 *   - Do NOT request logs every minute; historical is a batch process.
 *   - Minimum intervals: live 1s, log 15s, eventlog 15s, wc 60s.
 *   - Recommended live cadence: 15–20 minutes.
 *
 * Simulator date range (dev environment):
 *   2026-02-22 00:00:00 UTC  →  1771718400000 ms
 *   2026-03-10 23:59:59 UTC  →  1773187199000 ms
 */

// ── Types ───────────────────────────────────────────────

export interface TalgilTarget {
  ID: number;
  Name: string;
  Online: number;
  [key: string]: unknown;
}

export interface TalgilFullImage {
  ID: number;
  Name: string;
  Online: number;
  Sensors?: TalgilSensorEntry[];
  [key: string]: unknown;
}

export interface TalgilSensorEntry {
  UID?: string;
  Name?: string;
  Type?: string;
  Units?: string;
  Value?: number;
  [key: string]: unknown;
}

export interface TalgilSensorLogEntry {
  UID?: string;
  Time?: number;
  Value?: number;
  [key: string]: unknown;
}

export interface TalgilEventLogEntry {
  Time?: number;
  Type?: string;
  Source?: string;
  [key: string]: unknown;
}

export interface TalgilWcEntry {
  ValveUID?: string;
  Start?: number;
  End?: number;
  Rate?: number;
  Amount?: number;
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

// ── HTTP helper ─────────────────────────────────────────

async function talgilFetch<T>(
  baseUrl: string,
  path: string,
  apiKey: string,
): Promise<TalgilApiResult<T>> {
  const url = `${baseUrl}${path}`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: {
        "TLG-API-Key": apiKey,
        Accept: "application/json",
      },
    });

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      return {
        ok: false,
        status: res.status,
        data: null,
        url,
        error: `HTTP ${res.status}: ${body.slice(0, 200)}`,
      };
    }

    const data = (await res.json()) as T;
    return { ok: true, status: res.status, data, url };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      data: null,
      url,
      error: `Network error: ${(err as Error).message}`,
    };
  }
}

// ── Public API functions ────────────────────────────────

/**
 * GET /mytargets
 * Called ONCE during connect to discover the controller ID.
 * NOT called during regular sync cycles.
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
 * Contains sensors, valves, status, and metadata.
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
 * GET /targets/{id}/sensors/log?from={ms}&until={ms}
 * Historical sensor log — BATCH PROCESS ONLY.
 * Must respect 15-second minimum interval between calls.
 * Must stay within simulator date range for dev environment.
 */
export function talgilGetSensorLog(
  baseUrl: string,
  apiKey: string,
  controllerId: number,
  fromMs: number,
  untilMs: number,
): Promise<TalgilApiResult<TalgilSensorLogEntry[]>> {
  return talgilFetch<TalgilSensorLogEntry[]>(
    baseUrl,
    `/targets/${controllerId}/sensors/log?from=${fromMs}&until=${untilMs}`,
    apiKey,
  );
}

/**
 * GET /targets/{id}/eventlog?from={ms}&until={ms}
 * Event log — BATCH PROCESS ONLY.
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
  );
}

/**
 * GET /targets/{id}/wc/valves?from={ms}&until={ms}&rate=daily
 * Water consumption — BATCH PROCESS ONLY.
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
): Promise<TalgilApiResult<TalgilWcEntry[]>> {
  return talgilFetch<TalgilWcEntry[]>(
    baseUrl,
    `/targets/${controllerId}/wc/valves?from=${fromMs}&until=${untilMs}&rate=${rate}`,
    apiKey,
  );
}
