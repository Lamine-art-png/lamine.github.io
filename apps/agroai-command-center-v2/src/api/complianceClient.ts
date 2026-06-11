import { API_BASE } from "./client";

export interface ComplianceStatus {
  enabled: boolean;
  organization?: { id?: string; name?: string };
  rule_pack?: {
    pack_id: string;
    jurisdiction: string;
    status: string;
    version: string;
    workflow_type: string;
    external_validation: boolean;
  };
  readiness?: {
    readiness_status: string;
    readiness_percentage: number;
    blocking_defects: string[];
    warnings: { code: string; [key: string]: unknown }[];
    disclaimer: string;
  };
}

const demoMode = import.meta.env.VITE_COMPLIANCE_DEMO_MODE === "true";
const demoToken = import.meta.env.VITE_COMPLIANCE_DEMO_TOKEN || "";

export const complianceEnabled = import.meta.env.VITE_COMPLIANCE_ENABLED === "true";

export async function loadComplianceStatus(): Promise<ComplianceStatus> {
  if (!complianceEnabled) {
    throw new Error("Compliance is disabled for this workspace.");
  }
  if (!demoMode) {
    throw new Error("Compliance requires a secure browser session or short-lived token flow before production use.");
  }
  if (!demoToken) {
    throw new Error("Non-production compliance demo mode requires VITE_COMPLIANCE_DEMO_TOKEN.");
  }

  const response = await fetch(`${API_BASE}/v1/compliance/status`, {
    headers: {
      Accept: "application/json",
      "X-Compliance-Demo-Token": demoToken,
    },
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) {
    throw new Error(`Compliance API returned HTTP ${response.status}`);
  }
  return (await response.json()) as ComplianceStatus;
}
