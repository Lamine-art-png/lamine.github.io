import type { BackendStatus } from "./contracts";
export async function probeBackend(): Promise<{ status: BackendStatus; detail: string; checkedAt: string }> {
  const checkedAt = new Date().toISOString();
  try {
    const baseUrl = (import.meta.env.VITE_AGROAI_API_BASE || "").replace(/\/$/, "");
    const response = await fetch(`${baseUrl}/health`, { credentials: "include" });
    if (response.ok) return { status: "live", detail: "Backend health probe succeeded.", checkedAt };
    return { status: "limited", detail: `Backend health probe returned HTTP ${response.status}.`, checkedAt };
  } catch {
    return { status: "unavailable", detail: "Backend health probe unavailable; representative mode remains active.", checkedAt };
  }
}
