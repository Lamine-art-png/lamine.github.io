import { apiClient } from "./client";
import type { ProviderStatus } from "./contracts";

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function statusFromEnvironment(env: Record<string, unknown>, lastChecked: string): ProviderStatus {
  const live = Boolean(env.live);
  const configured = Boolean(env.configured);
  const farms = num(env.farms);
  const zones = num(env.zones);
  let connectionState: ProviderStatus["connectionState"] = "Unavailable";
  if (live) connectionState = "Live";
  else if (configured && (farms || zones)) connectionState = "Target selection required";
  else if (configured) connectionState = "Configured";
  else connectionState = "Setup required";

  return {
    provider: String(env.label || env.source || "Provider"),
    connectionState,
    runtimeState: String(env.status || (live ? "live" : configured ? "configured" : "unavailable")),
    farms,
    targets: farms,
    zones,
    sensors: null,
    lastChecked,
    limitations: [String(env.notes || "Runtime status unavailable.")],
  };
}

function byProvider(statuses: ProviderStatus[], name: string): ProviderStatus | undefined {
  return statuses.find((s) => s.provider.toLowerCase() === name.toLowerCase());
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
  statuses.push(...envs.map((env) => statusFromEnvironment(env, lastChecked)));

  if (!byProvider(statuses, "WiseConn")) {
    statuses.push({
      provider: "WiseConn",
      connectionState: wiseconnRes.ok && wiseconnRes.data?.authenticated ? "Live" : wiseconnRes.ok ? "Configured" : "Unavailable",
      runtimeState: wiseconnRes.ok ? String(wiseconnRes.data?.message || "checked") : "unavailable",
      farms: null,
      targets: null,
      zones: null,
      sensors: null,
      lastChecked,
      limitations: wiseconnRes.ok ? [String(wiseconnRes.data?.message || "No farm or zone count returned.")] : [wiseconnRes.error || "WiseConn status unavailable."],
    });
  }

  const talgil = byProvider(statuses, "Talgil");
  if (talgil && talgilRes.ok && talgilRes.data) {
    talgil.connectionState = talgilRes.data.live
      ? "Live"
      : talgilRes.data.configured
        ? Number(talgilRes.data.targets || 0) > 0
          ? "Target selection required"
          : "Configured"
        : "Setup required";
    talgil.runtimeState = String(talgilRes.data.status || talgil.runtimeState);
    talgil.targets = num(talgilRes.data.targets);
    talgil.sensors = num(talgilRes.data.sensors);
    talgil.limitations = [String(talgilRes.data.notes || "Talgil runtime checked.")];
  } else if (!talgil) {
    statuses.push({
      provider: "Talgil",
      connectionState: talgilRes.ok && talgilRes.data?.live ? "Live" : talgilRes.ok && talgilRes.data?.configured ? "Configured" : "Unavailable",
      runtimeState: talgilRes.ok ? String(talgilRes.data?.status || "checked") : "unavailable",
      farms: null,
      targets: num(talgilRes.data?.targets),
      zones: null,
      sensors: num(talgilRes.data?.sensors),
      lastChecked,
      limitations: talgilRes.ok ? [String(talgilRes.data?.notes || "No target selected.")] : [talgilRes.error || "Talgil status unavailable."],
    });
  }

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
