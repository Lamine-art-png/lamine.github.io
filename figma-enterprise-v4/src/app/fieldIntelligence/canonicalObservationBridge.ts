import { apiClient } from "../api/client";

type AnyRecord = Record<string, any>;

declare global {
  interface Window {
    __agroAiCanonicalObservationBridge?: boolean;
  }
}

const TASK_READY_EVENT = "agroai:field-intelligence-task-ready";
const TASK_ERROR_EVENT = "agroai:field-intelligence-task-error";

function normalize(value: unknown): string {
  return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function usefulText(value: unknown): string {
  if (typeof value === "string") {
    const clean = value.replace(/\s+/g, " ").trim();
    return normalize(clean) === "[object object]" ? "" : clean;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as AnyRecord;
  for (const key of ["summary", "text", "description", "message", "label", "content"]) {
    const candidate = usefulText(record[key]);
    if (candidate) return candidate;
  }
  return "";
}

function normalizeObservation(observation: AnyRecord): AnyRecord {
  if (!observation || typeof observation !== "object") return observation;
  const fallback = usefulText(observation.corrected_transcript)
    || usefulText(observation.transcript)
    || usefulText(observation.recommended_action)
    || "Field observation awaiting analysis.";
  const summary = usefulText(observation.summary) || fallback;
  return summary === observation.summary ? observation : { ...observation, summary };
}

function normalizeObservationResponse(response: AnyRecord): AnyRecord {
  if (Array.isArray(response)) return response.map((row) => normalizeObservation(row)) as unknown as AnyRecord;
  if (!response || typeof response !== "object") return response;
  if (Array.isArray(response.observations)) {
    return { ...response, observations: response.observations.map((row: AnyRecord) => normalizeObservation(row)) };
  }
  if (Array.isArray(response.items)) {
    return { ...response, items: response.items.map((row: AnyRecord) => normalizeObservation(row)) };
  }
  if (response.observation && typeof response.observation === "object") {
    return { ...response, observation: normalizeObservation(response.observation) };
  }
  return response.id ? normalizeObservation(response) : response;
}

function rowsFromResponse(response: AnyRecord): AnyRecord[] {
  if (Array.isArray(response?.observations)) return response.observations;
  if (Array.isArray(response?.items)) return response.items;
  if (Array.isArray(response)) return response;
  return [];
}

function installObservationNormalization() {
  const fieldIntelligence = (apiClient as any).fieldIntelligence;
  for (const methodName of ["observations", "observation"] as const) {
    const current = fieldIntelligence?.[methodName];
    if (typeof current !== "function" || current.__agroAiObservationNormalized) continue;
    const original = current.bind(fieldIntelligence);
    const wrapped = async (...args: any[]) => normalizeObservationResponse(await original(...args));
    wrapped.__agroAiObservationNormalized = true;
    fieldIntelligence[methodName] = wrapped;
  }
}

function scoreObservation(observation: AnyRecord, drawerText: string): number {
  const haystack = normalize(drawerText);
  let score = 0;
  const candidates: Array<[unknown, number, number]> = [
    [observation.field_name, 5, 48],
    [observation.block_name, 4, 48],
    [observation.corrected_transcript, 10, 140],
    [observation.transcript, 10, 140],
    [usefulText(observation.summary), 8, 100],
  ];
  for (const [value, weight, maxLength] of candidates) {
    const candidate = normalize(value);
    if (!candidate || candidate === "unassigned field" || candidate === "[object object]") continue;
    const fragment = candidate.slice(0, maxLength);
    if (fragment.length >= 5 && haystack.includes(fragment)) score += weight;
  }
  return score;
}

async function resolveObservationId(drawer: Element): Promise<string> {
  const drawerText = String((drawer as HTMLElement).innerText || drawer.textContent || "");
  const response: AnyRecord = await (apiClient as any).fieldIntelligence.observations("limit=100");
  const rows = rowsFromResponse(response);
  const best = rows
    .map((observation) => ({ observation, score: scoreObservation(observation, drawerText) }))
    .sort((a, b) => b.score - a.score)[0];
  return best && best.score >= 4 ? String(best.observation?.id || "") : "";
}

function taskFromResponse(response: AnyRecord): AnyRecord | null {
  const task = response?.task || (response?.id ? response : null);
  return task?.id ? task : null;
}

function removeExistingTaskNotice() {
  document.querySelectorAll("[data-fi-canonical-task-notice]").forEach((node) => node.remove());
}

function showTaskNotice(detail: AnyRecord, isError = false) {
  removeExistingTaskNotice();
  const notice = document.createElement("section");
  notice.dataset.fiCanonicalTaskNotice = "true";
  notice.setAttribute("role", isError ? "alert" : "status");
  Object.assign(notice.style, {
    position: "fixed",
    left: "max(14px, env(safe-area-inset-left))",
    right: "max(14px, env(safe-area-inset-right))",
    bottom: "max(18px, env(safe-area-inset-bottom))",
    zIndex: "10050",
    maxWidth: "440px",
    padding: "16px",
    borderRadius: "16px",
    border: `1px solid ${isError ? "#E6B7AD" : "#BFD8C9"}`,
    background: isError ? "#FFF4F1" : "#FFFDF8",
    color: "#10231B",
    boxShadow: "0 24px 70px rgba(16,35,27,0.24)",
    fontFamily: "inherit",
  });

  const title = document.createElement("div");
  title.style.fontSize = "13px";
  title.style.fontWeight = "800";
  title.style.color = isError ? "#9F2D20" : "#1B5E3F";
  title.textContent = isError ? "Task could not be created" : "Task created and linked";
  notice.append(title);

  const description = document.createElement("div");
  description.style.marginTop = "5px";
  description.style.fontSize = "12px";
  description.style.lineHeight = "1.5";
  description.style.color = "#536158";
  description.textContent = isError
    ? String(detail?.message || "Retry from the field observation.")
    : String(detail?.task?.title || "The field observation is now accountable work in Tasks.");
  notice.append(description);

  if (!isError && detail?.task?.id) {
    const link = document.createElement("a");
    const taskId = encodeURIComponent(String(detail.task.id));
    const observationId = encodeURIComponent(String(detail.observationId || ""));
    link.href = `/tasks?task_id=${taskId}${observationId ? `&observation_id=${observationId}` : ""}`;
    link.textContent = "Open task";
    Object.assign(link.style, {
      display: "inline-flex",
      marginTop: "10px",
      minHeight: "38px",
      alignItems: "center",
      justifyContent: "center",
      borderRadius: "9px",
      padding: "0 12px",
      background: "#0D2B1E",
      color: "white",
      fontSize: "12px",
      fontWeight: "700",
      textDecoration: "none",
    });
    notice.append(link);
  }

  document.body.append(notice);
  if (!isError) window.setTimeout(() => notice.remove(), 15000);
}

function installTaskBridge() {
  const fieldIntelligence = (apiClient as any).fieldIntelligence;
  const current = fieldIntelligence?.createTask;
  if (typeof current !== "function") return;

  window.addEventListener(TASK_READY_EVENT, (event) => showTaskNotice((event as CustomEvent).detail));
  window.addEventListener(TASK_ERROR_EVENT, (event) => showTaskNotice((event as CustomEvent).detail, true));

  if (current.__agroAiCanonicalTaskBridge || current.__agroAiOperatingLoop) return;
  const original = current.bind(fieldIntelligence);
  const wrapped = async (observationId: string, payload: AnyRecord = {}) => {
    try {
      const response = await original(observationId, payload);
      const task = taskFromResponse(response);
      if (!task) throw new Error("The server did not return the created task.");
      window.dispatchEvent(new CustomEvent(TASK_READY_EVENT, { detail: { observationId, task, response } }));
      return response;
    } catch (error) {
      window.dispatchEvent(new CustomEvent(TASK_ERROR_EVENT, {
        detail: { observationId, message: error instanceof Error ? error.message : String(error || "Task creation failed") },
      }));
      throw error;
    }
  };
  wrapped.__agroAiCanonicalTaskBridge = true;
  fieldIntelligence.createTask = wrapped;
}

function installAskBridge() {
  document.addEventListener("click", (event) => {
    if (window.location.pathname !== "/field-intelligence") return;
    const target = event.target instanceof Element ? event.target : null;
    const anchor = target?.closest<HTMLAnchorElement>('a[href="/intelligence"]');
    const drawer = anchor?.closest("[role='dialog']");
    if (!anchor || !drawer) return;

    event.preventDefault();
    event.stopPropagation();
    anchor.setAttribute("aria-busy", "true");

    void resolveObservationId(drawer)
      .then((observationId) => {
        if (!observationId) throw new Error("The selected field observation could not be resolved.");
        const url = `/intelligence?field_observation_id=${encodeURIComponent(observationId)}&source=field-intelligence`;
        window.location.assign(url);
      })
      .catch((error) => {
        anchor.removeAttribute("aria-busy");
        const message = error instanceof Error ? error.message : "The selected field observation could not be resolved.";
        showTaskNotice({ message }, true);
      });
  }, true);
}

export function installCanonicalObservationBridge() {
  if (window.__agroAiCanonicalObservationBridge) return;
  window.__agroAiCanonicalObservationBridge = true;
  installObservationNormalization();
  installTaskBridge();
  installAskBridge();
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  try {
    installCanonicalObservationBridge();
  } catch (error) {
    console.error("AGRO-AI canonical Field Intelligence observation bridge failed", error);
  }
}
