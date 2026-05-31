import { apiClient } from "./client";
import type { BackendStatus } from "./contracts";

export interface HealthResult {
  status: BackendStatus;
  detail: string;
  checkedAt: string;
}

// Derive backend state from a real health probe rather than hardcoding it.
//  - available:  schema endpoint responds with a usable contract
//  - limited:    backend reachable but schema/contract incomplete
//  - unavailable: no successful response
export async function probeBackend(): Promise<HealthResult> {
  const checkedAt = new Date().toISOString();
  const schema = await apiClient.getSchema();

  if (schema.ok && schema.data?.output_schema?.length) {
    return { status: "available", detail: "Workbench schema reachable", checkedAt };
  }

  if (schema.ok) {
    return { status: "limited", detail: "Backend reachable, schema contract incomplete", checkedAt };
  }

  // Schema failed — try OpenAPI as a secondary signal before declaring unavailable.
  const openapi = await apiClient.getOpenApi();
  if (openapi.ok && openapi.data?.paths) {
    return { status: "limited", detail: "API reachable, Workbench schema unavailable", checkedAt };
  }

  return { status: "unavailable", detail: schema.error ?? "No response from backend", checkedAt };
}
