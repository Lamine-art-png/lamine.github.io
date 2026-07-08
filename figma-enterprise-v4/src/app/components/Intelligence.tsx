import { API_BASE_URL, apiClient } from "../api/client";
import { IntelligencePlanControls, REASONING_MODE_STORAGE_KEY } from "./intelligence/IntelligencePlanControls";
import { IntelligenceView } from "./intelligence/IntelligenceView";
import {
  useIntelligenceController,
  type IntelligenceDependencies,
} from "./intelligence/useIntelligenceController";

type AnyRecord = Record<string, any>;

const RESPONSE_LANGUAGE_STORAGE_KEY = "agroai_response_language_v1";

function shouldUseLegacyRoute(error: unknown) {
  const status = Number((error as AnyRecord)?.status || 0);
  return status === 404 || status === 405;
}

function selectedReasoningMode() {
  const value = window.localStorage.getItem(REASONING_MODE_STORAGE_KEY);
  return value === "quick" || value === "deep" ? value : "standard";
}

function withIndependentResponseLanguage(request: AnyRecord): AnyRecord {
  const stored = window.localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)?.trim();
  const reasoningMode = selectedReasoningMode();
  const task = request.task === "chat"
    ? reasoningMode === "quick"
      ? "chat_fast"
      : reasoningMode === "deep"
        ? "deep_analysis"
        : "chat"
    : request.task;
  return {
    ...request,
    task,
    reasoning_mode: reasoningMode,
    preferred_language: stored || "auto",
  };
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
    const languageAwareRequest = withIndependentResponseLanguage(request);

    // Production route: normal hybrid router plus independent edge and free-hosted
    // recovery lanes. This protects Ask AGRO-AI from a broken provider/base-url
    // pairing, an unfunded paid route, or a missing edge env on one Render service.
    try {
      return await apiClient.post(
        "/v1/runtime/intelligence-run",
        languageAwareRequest,
      ) as AnyRecord;
    } catch (resilientRouteError) {
      if (!shouldUseLegacyRoute(resilientRouteError)) throw resilientRouteError;

      // Rolling-deploy compatibility while the backend revision propagates.
      try {
        return await apiClient.post(
          "/v1/intelligence/brain/run",
          languageAwareRequest,
        ) as AnyRecord;
      } catch (canonicalRouteError) {
        if (!shouldUseLegacyRoute(canonicalRouteError)) throw canonicalRouteError;
        try {
          return await apiClient.post(
            "/v1/intelligence/brain/run-commercial",
            languageAwareRequest,
          ) as AnyRecord;
        } catch (commercialRouteError) {
          if (!shouldUseLegacyRoute(commercialRouteError)) throw commercialRouteError;
          try {
            return await apiClient.post(
              "/v1/intelligence/brain/run-safe",
              languageAwareRequest,
            ) as AnyRecord;
          } catch (safeRouteError) {
            if (!shouldUseLegacyRoute(safeRouteError)) throw safeRouteError;
            try {
              return await apiClient.intelligence.brainRun(languageAwareRequest) as AnyRecord;
            } catch (brainRouteError) {
              if (shouldUseLegacyRoute(brainRouteError)) {
                return await apiClient.intelligence.run(languageAwareRequest) as AnyRecord;
              }
              throw brainRouteError;
            }
          }
        }
      }
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
  return <>
    <IntelligencePlanControls />
    <IntelligenceView controller={controller} />
  </>;
}
