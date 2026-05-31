const DEFAULT_WORKFLOW = "gears_groundwater_extractor_readiness";

function complianceHeaders() {
  const headers = { Accept: "application/json" };
  const demoToken = import.meta?.env?.VITE_NON_PRODUCTION_COMPLIANCE_DEMO_TOKEN || "";
  const demoOrg = import.meta?.env?.VITE_NON_PRODUCTION_COMPLIANCE_ORG_ID || "org-ca-vineyard-001";
  if (demoToken) {
    headers["X-Compliance-Demo-Token"] = demoToken;
    headers["X-Organization-Id"] = demoOrg;
  }
  return headers;
}

async function request(path, options = {}) {
  const baseUrl = (import.meta?.env?.VITE_AGROAI_API_BASE || "").replace(/\/$/, "");
  const response = await fetch(`${baseUrl}${path}`, {
    method: options.method || "GET",
    credentials: "include",
    headers: {
      ...complianceHeaders(),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || `Compliance API returned HTTP ${response.status}`);
  }
  return payload;
}

export async function loadComplianceWorkspace(workflowType = DEFAULT_WORKFLOW) {
  const [status, readiness, waterBudgets, reconciliation, meters, auditLog] = await Promise.all([
    request("/v1/compliance/status"),
    request(`/v1/compliance/readiness?workflow_type=${encodeURIComponent(workflowType)}`),
    request("/v1/compliance/water-budgets"),
    request("/v1/compliance/reconciliation"),
    request("/v1/compliance/assets/meters"),
    request("/v1/compliance/audit-log"),
  ]);
  return { status, readiness, waterBudgets, reconciliation, meters, auditLog };
}

export async function createComplianceExport(exportType, workflowType = DEFAULT_WORKFLOW) {
  return request("/v1/compliance/exports", {
    method: "POST",
    body: { export_type: exportType, workflow_type: workflowType },
  });
}

export function downloadExportPackage(exportPackage) {
  if (!exportPackage?.content_base64) return false;
  const binary = atob(exportPackage.content_base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: exportPackage.mime_type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = exportPackage.file_name || `compliance-export-${exportPackage.id}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return true;
}
