const DEFAULT_WORKFLOW = "gears_groundwater_extractor_readiness";

export interface ComplianceExportMetadata {
  id: string;
  file_name: string;
  mime_type: string;
  checksum_sha256?: string;
  content_bytes?: number;
  download_available?: boolean;
}

function complianceHeaders(): HeadersInit {
  const headers: Record<string, string> = { Accept: "application/json" };
  const env = import.meta.env as Record<string, string | undefined>;
  const demoToken = env.VITE_NON_PRODUCTION_COMPLIANCE_DEMO_TOKEN || "";
  const demoOrg = env.VITE_NON_PRODUCTION_COMPLIANCE_ORG_ID || "org-ca-vineyard-001";
  if (demoToken) {
    headers["X-Compliance-Demo-Token"] = demoToken;
    headers["X-Organization-Id"] = demoOrg;
  }
  return headers;
}

async function request<T>(path: string, options: RequestInit & { body?: string } = {}): Promise<T> {
  const env = import.meta.env as Record<string, string | undefined>;
  const baseUrl = (env.VITE_AGROAI_API_BASE || "").replace(/\/$/, "");
  const response = await fetch(`${baseUrl}${path}`, {
    method: options.method || "GET",
    credentials: "include",
    headers: {
      ...complianceHeaders(),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    body: options.body,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.detail || payload?.message || `Compliance API returned HTTP ${response.status}`);
  return payload as T;
}

export async function loadComplianceWorkspace(workflowType = DEFAULT_WORKFLOW) {
  const [status, readiness, waterBudgets, reconciliation, meters, auditLog] = await Promise.all([
    request<Record<string, unknown>>("/v1/compliance/status"),
    request<Record<string, unknown>>(`/v1/compliance/readiness?workflow_type=${encodeURIComponent(workflowType)}`),
    request<unknown[]>("/v1/compliance/water-budgets"),
    request<unknown[]>("/v1/compliance/reconciliation"),
    request<unknown[]>("/v1/compliance/assets/meters"),
    request<unknown[]>("/v1/compliance/audit-log"),
  ]);
  return { status, readiness, waterBudgets, reconciliation, meters, auditLog };
}

export async function createComplianceExport(exportType: string, workflowType = DEFAULT_WORKFLOW): Promise<ComplianceExportMetadata> {
  return request<ComplianceExportMetadata>("/v1/compliance/exports", {
    method: "POST",
    body: JSON.stringify({ export_type: exportType, workflow_type: workflowType }),
  });
}

export async function downloadComplianceExport(exportId: string): Promise<{ blob: Blob; fileName: string }> {
  const env = import.meta.env as Record<string, string | undefined>;
  const baseUrl = (env.VITE_AGROAI_API_BASE || "").replace(/\/$/, "");
  const response = await fetch(`${baseUrl}/v1/compliance/exports/${encodeURIComponent(exportId)}/download`, {
    method: "GET",
    credentials: "include",
    headers: complianceHeaders(),
  });
  if (!response.ok) throw new Error(`Compliance export download failed with HTTP ${response.status}`);
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename=([^;]+)/i);
  return { blob: await response.blob(), fileName: match?.[1]?.replaceAll('"', "") || `compliance-export-${exportId}` };
}

export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
