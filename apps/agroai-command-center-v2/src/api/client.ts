import type { WorkbenchAnalysisResult } from "./contracts";

type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string; data?: never };
async function request<T>(path: string, options: RequestInit = {}): Promise<ApiResult<T>> {
  try {
    const baseUrl = (import.meta.env.VITE_AGROAI_API_BASE || "").replace(/\/$/, "");
    const response = await fetch(`${baseUrl}${path}`, { credentials: "include", ...options });
    const data = await response.json().catch(() => null);
    if (!response.ok) return { ok: false, error: data?.detail || `HTTP ${response.status}` };
    return { ok: true, data } as ApiResult<T>;
  } catch (error: any) {
    return { ok: false, error: error?.message || "Request failed" };
  }
}
export const apiClient = {
  analyzeLive(source: string, entityId: string) {
    return request<WorkbenchAnalysisResult>("/v1/workbench/analyze-live", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source, entity_id: entityId }) });
  },
  createSession(mode: string) {
    return request<any>("/v1/workbench/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, workspace_name: "Water Command Center" }) });
  },
  uploadFile(sessionId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<any>(`/v1/workbench/sessions/${encodeURIComponent(sessionId)}/upload`, { method: "POST", body });
  },
  analyzeSession(sessionId: string) {
    return request<WorkbenchAnalysisResult>(`/v1/workbench/sessions/${encodeURIComponent(sessionId)}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "uploaded" }) });
  },
};
