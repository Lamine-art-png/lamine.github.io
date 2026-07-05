import { API_BASE_URL, apiClient } from "../api/client";
import { IntelligenceView } from "./intelligence/IntelligenceView";
import {
  useIntelligenceController,
  type IntelligenceDependencies,
} from "./intelligence/useIntelligenceController";

type AnyRecord = Record<string, any>;

function shouldUseLegacyRoute(error: unknown) {
  const status = Number((error as AnyRecord)?.status || 0);
  return status === 404 || status === 405;
}

async function createReportPdf(payload: AnyRecord): Promise<Blob> {
  const token = window.localStorage.getItem("agroai_access_token");
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}/v1/intelligence/chat/report-pdf`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(
      (await response.text().catch(() => "")) ||
        `Report export failed with status ${response.status}`,
    );
  }
  return response.blob();
}

async function emailReportPdf(payload: AnyRecord): Promise<AnyRecord> {
  const token = window.localStorage.getItem("agroai_access_token");
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}/v1/intelligence/chat/report-email`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.status === "not_sent") {
    throw new Error(
      String(
        data?.delivery?.reason ||
          data?.detail ||
          `Report email failed with status ${response.status}`,
      ),
    );
  }
  return data;
}

const intelligenceDependencies: IntelligenceDependencies = {
  createReportPdf,
  emailReportPdf,
  async listConversations(workspaceId?: string) {
    const suffix = workspaceId
      ? `?workspace_id=${encodeURIComponent(workspaceId)}`
      : "";
    return apiClient.get(`/v1/intelligence/brain/conversations${suffix}`) as Promise<AnyRecord>;
  },
  async createConversation(payload: AnyRecord) {
    return apiClient.post("/v1/intelligence/brain/conversations", payload) as Promise<AnyRecord>;
  },
  async getConversation(conversationId: string) {
    return apiClient.get(
      `/v1/intelligence/brain/conversations/${encodeURIComponent(conversationId)}`,
    ) as Promise<AnyRecord>;
  },
  async deleteConversation(conversationId: string) {
    return apiClient.remove(
      `/v1/intelligence/brain/conversations/${encodeURIComponent(conversationId)}`,
    );
  },
  async persistExchange(conversationId: string, payload: AnyRecord) {
    return apiClient.post(
      `/v1/intelligence/brain/conversations/${encodeURIComponent(conversationId)}/messages`,
      payload,
    ) as Promise<AnyRecord>;
  },
  async runIntelligence(request: AnyRecord) {
    try {
      return await apiClient.intelligence.brainRun(request) as AnyRecord;
    } catch (error) {
      if (shouldUseLegacyRoute(error)) {
        return await apiClient.intelligence.run(request) as AnyRecord;
      }
      throw error;
    }
  },
  async uploadEvidence(file: File, workspaceId?: string) {
    return apiClient.evidence.upload(file, undefined, workspaceId) as Promise<AnyRecord>;
  },
  async planActions(payload: AnyRecord) {
    try {
      const response = await apiClient.post("/v1/agents/actions/plan", payload) as AnyRecord;
      return Array.isArray(response.actions) ? response.actions : [];
    } catch {
      return [];
    }
  },
  async executeAction(payload: AnyRecord) {
    return apiClient.post("/v1/agents/actions/execute", payload) as Promise<AnyRecord>;
  },
};

export function Intelligence() {
  const controller = useIntelligenceController(intelligenceDependencies);
  return <IntelligenceView controller={controller} />;
}
