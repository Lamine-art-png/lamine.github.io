import { useEffect, useRef, useState } from "react";
import { API_BASE_URL, apiClient } from "../api/client";
import { IntelligencePlanControls, REASONING_MODE_STORAGE_KEY } from "./intelligence/IntelligencePlanControls";
import { IntelligenceView } from "./intelligence/IntelligenceView";
import {
  useIntelligenceController,
  type IntelligenceDependencies,
} from "./intelligence/useIntelligenceController";

type AnyRecord = Record<string, any>;

function contextualFieldObservationId(): string {
  if (typeof window === "undefined" || window.location.pathname !== "/intelligence") return "";
  return new URLSearchParams(window.location.search || "").get("field_observation_id") || "";
}

function linkedFieldObservationEvidence(observation: AnyRecord): AnyRecord {
  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};
  return {
    filename: `Field Intelligence observation ${String(observation.id || "").slice(0, 8)}`,
    source_type: "field_observation",
    import_status: "linked",
    observation_id: observation.id,
    parsed_preview: JSON.stringify({
      observation_id: observation.id,
      field_name: observation.field_name,
      block_name: observation.block_name,
      crop: observation.crop,
      event_type: observation.event_type,
      severity: observation.severity,
      occurred_at: observation.occurred_at,
      summary: observation.summary,
      transcript: observation.corrected_transcript || observation.transcript,
      recommended_action: observation.recommended_action || vision.recommended_follow_up,
      visible_facts: Array.isArray(vision.visible_facts) ? vision.visible_facts.slice(0, 10) : [],
      hypotheses: Array.isArray(vision.hypotheses) ? vision.hypotheses.slice(0, 10) : [],
      uncertainties: Array.isArray(vision.uncertainties) ? vision.uncertainties.slice(0, 10) : [],
      media_moments: Array.isArray(vision.media_moments) ? vision.media_moments.slice(0, 10) : [],
      correlation: observation.correlation || observation.correlation_json,
      confidence: observation.confidence,
      evidence_ids: observation.evidence_ids || observation.evidence_ids_json || [],
      asset_count: Array.isArray(observation.assets) ? observation.assets.length : 0,
    }).slice(0, 12000),
  };
}

async function withFieldObservationContext(request: AnyRecord): Promise<AnyRecord> {
  const observationId = contextualFieldObservationId();
  if (!observationId) return request;
  const response = await apiClient.fieldIntelligence.observation(observationId) as AnyRecord;
  const observation = response?.observation || response;
  if (!observation?.id) return request;
  const existing = Array.isArray(request?.uploaded_evidence) ? request.uploaded_evidence : [];
  return {
    ...(request || {}),
    field_id: request?.field_id || observation.field_id,
    field_observation_id: observationId,
    uploaded_evidence: [
      linkedFieldObservationEvidence(observation),
      ...existing.filter((item: AnyRecord) => String(item?.observation_id || "") !== observationId),
    ],
  };
}

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
    const contextualRequest = await withFieldObservationContext(request);
    const languageAwareRequest = withIndependentResponseLanguage(contextualRequest);

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

type IntelligenceController = ReturnType<typeof useIntelligenceController>;

function contextualPrompt(observation: AnyRecord): string {
  const summary = String(
    observation.summary ||
    observation.corrected_transcript ||
    observation.transcript ||
    "Review the linked field observation.",
  ).trim();
  return [
    "Analyze this linked Field Intelligence observation as one operational case.",
    "Use its transcript, media analysis, visible facts, hypotheses, evidence, and uncertainty. Separate confirmed facts from hypotheses, explain what matters, state what must be verified, and recommend the best next accountable action. Do not invent measurements or diagnoses.",
    summary,
  ].join("\n\n");
}

function FieldObservationContext({ controller }: { controller: IntelligenceController }) {
  const observationId = contextualFieldObservationId();
  const [observation, setObservation] = useState<AnyRecord | null>(null);
  const [loadError, setLoadError] = useState("");
  const sentObservationRef = useRef("");

  useEffect(() => {
    let cancelled = false;
    setObservation(null);
    setLoadError("");
    if (!observationId) return () => { cancelled = true; };

    void apiClient.fieldIntelligence.observation(observationId)
      .then((response: any) => {
        if (cancelled) return;
        const row = response?.observation || response;
        if (!row?.id) throw new Error("The linked field observation could not be loaded.");
        setObservation(row);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : "The linked field observation could not be loaded.");
        }
      });

    return () => { cancelled = true; };
  }, [observationId]);

  useEffect(() => {
    if (!observation?.id || sentObservationRef.current === String(observation.id)) return;
    sentObservationRef.current = String(observation.id);
    void controller.send(contextualPrompt(observation));
  }, [controller.send, observation]);

  if (!observationId) return null;
  return <section className="border-b border-[#BFD8C9] bg-[#EDF7F1] px-4 py-3 sm:px-8">
    <div className="mx-auto flex max-w-[1100px] flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#2D6A4F]">Field Intelligence · linked observation</div>
        <div className="mt-1 text-[14px] font-semibold text-[#10231B]">{observation?.field_name || observation?.block_name || "Field observation"}</div>
        <div className="mt-1 line-clamp-2 text-[12px] leading-5 text-[#536158]">
          {loadError || observation?.summary || observation?.corrected_transcript || observation?.transcript || "Loading the exact field observation…"}
        </div>
      </div>
      <a href={`/field-intelligence?observation_id=${encodeURIComponent(observationId)}`} className="inline-flex min-h-[38px] items-center rounded-lg border border-[#8FC3A6] bg-white px-3 text-[12px] font-semibold text-[#1B5E3F]">Open observation</a>
    </div>
  </section>;
}

export function Intelligence() {
  const controller = useIntelligenceController(intelligenceDependencies);
  return <>
    <IntelligencePlanControls />
    <FieldObservationContext controller={controller} />
    <IntelligenceView controller={controller} />
  </>;
}
