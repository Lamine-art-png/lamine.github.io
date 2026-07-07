import { apiClient } from "./client";

export type UnifiedAgProvider = "wiseconn" | "talgil" | "openet";
export type UnifiedLifecycleState =
  | "available"
  | "authorizing"
  | "connected"
  | "discovering"
  | "syncing"
  | "synced"
  | "action_required"
  | "reconnect_required"
  | "rate_limited"
  | "degraded"
  | "failed";

export type UnifiedResource = {
  id: string;
  name: string;
  type: "farm" | "controller" | "field" | string;
  metadata?: Record<string, unknown>;
};

export const unifiedConnectors = {
  connect: (payload: { provider: UnifiedAgProvider; workspace_id?: string; api_key: string; api_url?: string }) =>
    apiClient.post("/v1/connectors/unified/connect", payload),
  discovery: (connectionId: string) =>
    apiClient.get(`/v1/connectors/unified/${encodeURIComponent(connectionId)}/discovery`),
  select: (
    connectionId: string,
    payload: {
      resource_ids?: string[];
      scope_mode?: "provider_resources" | "agroai_fields" | "openet_field_ids" | "geometry";
      field_ids?: string[];
      geometry?: number[];
    },
  ) => apiClient.post(`/v1/connectors/unified/${encodeURIComponent(connectionId)}/selection`, payload),
  sync: (connectionId: string) =>
    apiClient.post(`/v1/connectors/unified/${encodeURIComponent(connectionId)}/sync`),
  status: (connectionId: string) =>
    apiClient.get(`/v1/connectors/unified/${encodeURIComponent(connectionId)}/status`),
  disconnect: (connectionId: string) =>
    apiClient.post(`/v1/connectors/unified/${encodeURIComponent(connectionId)}/disconnect`),
  uploadOpenETBoundary: (connectionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiClient.request(`/v1/connectors/unified/${encodeURIComponent(connectionId)}/openet-boundary`, {
      method: "POST",
      body: form,
    });
  },
};
