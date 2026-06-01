import { apiClient } from "./client";
import type { ProviderStatus } from "./contracts";

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function bool(value: unknown): boolean {
  return value === true || value === "true" || value === "configured" || value === "live";
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function mergeProviderData(primary: Record<string, unknown> | null | undefined, fallback?: Record<string, unknown>) {
  return { ...(fallback ?? {}), ...(primary ?? {}) };
}

export function mapWiseConnStatus(result: { ok: boolean; data: Record<string, unknown> | null; error?: string }, env: Record<string, unknown> | undefined, lastChecked: string): ProviderStatus {
  if (!result.ok) {
    return {
      provider: "WiseConn",
      connectionState: "Unavailable",
      runtimeState: "request failed",
      farms: null,
      targets: null,
      zones: null,
      sensors: null,
      lastChecked,
      limitations: [result.error || "WiseConn status unavailable."],
    };
  }

  const data = mergeProviderData(result.data, env);
  const farms = num(data.farms ?? data.farm_count);
  const zones = num(data.zones ?? data.zone_count);
  const configured = bool(data.configured) || bool(data.authenticated) || bool(data.api_key_configured);
  const readableTargets = Boolean((farms && farms > 0) || (zones && zones > 0));
  const degraded = bool(data.degraded) || ["limited", "degraded", "error"].includes(text(data.status, "").toLowerCase());
  const connectionState: ProviderStatus["connectionState"] = !configured
    ? "Setup required"
    : readableTargets && !degraded
      ? "Live"
      : "Limited";

  return {
    provider: "WiseConn",
    connectionState,
    runtimeState: text(data.status || data.message, connectionState.toLowerCase()),
    farms,
    targets: farms,
    zones,
    sensors: num(data.sensors ?? data.sensor_count),
    lastChecked,
    limitations: [text(data.notes || data.message, connectionState === "Live" ? "Farms or zones readable." : "Read path is not fully available.")],
  };
}

export function mapTalgilStatus(result: { ok: boolean; data: Record<string, unknown> | null; error?: string }, env: Record<string, unknown> | undefined, lastChecked: string): ProviderStatus {
  if (!result.ok) {
    return {
      provider: "Talgil",
      connectionState: "Unavailable",
      runtimeState: "request failed",
      farms: null,
      targets: null,
      zones: null,
      sensors: null,
      lastChecked,
      limitations: [result.error || "Talgil status unavailable."],
    };
  }

  const data = mergeProviderData(result.data, env);
  const configured = bool(data.configured) || bool(data.authenticated) || bool(data.api_key_configured);
  const live = bool(data.live) || text(data.status, "").toLowerCase() === "live";
  const targets = num(data.targets ?? data.target_count);
  const targetCount = targets ?? 0;
  const degraded = bool(data.degraded) || ["limited", "degraded", "error"].includes(text(data.status, "").toLowerCase());
  const connectionState: ProviderStatus["connectionState"] = !configured
    ? "Setup required"
    : live && targetCount > 0 && !degraded
      ? "Live"
      : targetCount <= 0 && !degraded
        ? "Target selection required"
        : "Limited";

  return {
    provider: "Talgil",
    connectionState,
    runtimeState: text(data.status || data.message, connectionState.toLowerCase()),
    farms: num(data.farms ?? data.farm_count),
    targets,
    zones: num(data.zones ?? data.zone_count),
    sensors: num(data.sensors ?? data.sensor_count),
    lastChecked,
    limitations: [text(data.notes || data.message, connectionState === "Live" ? "Runtime targets readable." : "Runtime target selection or read path needs review.")],
  };
}

function environmentFor(envs: Record<string, unknown>[], provider: string): Record<string, unknown> | undefined {
  return envs.find((env) => String(env.label || env.source || "").toLowerCase() === provider.toLowerCase());
}

export async function loadRuntimeStatuses(): Promise<ProviderStatus[]> {
  const lastChecked = new Date().toISOString();
  const [envRes, wiseconnRes, talgilRes] = await Promise.all([
    apiClient.getControllerEnvironments(),
    apiClient.getWiseconnAuth(),
    apiClient.getTalgilStatus(),
  ]);

  const statuses: ProviderStatus[] = [];
  const envs = Array.isArray(envRes.data?.environments) ? (envRes.data.environments as Record<string, unknown>[]) : [];
  statuses.push(mapWiseConnStatus(wiseconnRes, environmentFor(envs, "WiseConn"), lastChecked));
  statuses.push(mapTalgilStatus(talgilRes, environmentFor(envs, "Talgil"), lastChecked));

  statuses.push({
    provider: "Earth observation layer",
    connectionState: "Setup required",
    runtimeState: "partner authorization required",
    farms: null,
    targets: null,
    zones: null,
    sensors: null,
    lastChecked,
    limitations: ["Representative layer only until a partner feed is authorized."],
  });

  return statuses;
}
