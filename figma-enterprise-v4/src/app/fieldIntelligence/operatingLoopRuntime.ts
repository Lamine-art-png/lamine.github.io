import { apiClient } from "../api/client";
import { t } from "../i18n";

type AnyRecord = Record<string, any>;

declare global {
  interface Window {
    __agroAiFieldIntelligenceOperatingLoop?: boolean;
  }
}

const OBSERVATION_PARAM = "field_observation_id";
const ACTIVE_OBSERVATION_PARAM = "observation_id";
const TASK_READY_EVENT = "agroai:field-intelligence-task-ready";
const TASK_ERROR_EVENT = "agroai:field-intelligence-task-error";
const LOCATION_EVENT = "agroai:location-change";
const INTELLIGENCE_EXECUTION_PATHS = new Set([
  "/v1/runtime/intelligence-run",
  "/v1/intelligence/brain/run",
  "/v1/intelligence/brain/run-commercial",
  "/v1/intelligence/brain/run-safe",
  "/v1/intelligence/run",
  "/v1/ai/chat",
]);

const observations = new Map<string, AnyRecord>();
const tasks = new Map<string, AnyRecord>();
const contextSent = new Set<string>();
const directObservationOpened = new Set<string>();
let activeObservationId = "";
let enhancementQueued = false;

function normalize(value: unknown): string {
  return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function text(value: unknown, fallback = ""): string {
  const output = String(value || "").replace(/\s+/g, " ").trim();
  return output || fallback;
}

function currentObservationId(): string {
  const params = new URLSearchParams(window.location.search || "");
  return params.get(OBSERVATION_PARAM)
    || params.get(ACTIVE_OBSERVATION_PARAM)
    || activeObservationId
    || "";
}

function rememberObservation(observation: AnyRecord | null | undefined): AnyRecord | null {
  if (!observation?.id) return null;
  observations.set(String(observation.id), observation);
  return observation;
}

function rememberObservationResponse(response: AnyRecord): AnyRecord | null {
  const single = response?.observation || (response?.id ? response : null);
  if (single) return rememberObservation(single);
  const rows = Array.isArray(response?.observations)
    ? response.observations
    : Array.isArray(response?.items)
      ? response.items
      : Array.isArray(response)
        ? response
        : [];
  rows.forEach((row: AnyRecord) => rememberObservation(row));
  return null;
}

function rememberTaskResponse(response: AnyRecord): AnyRecord | null {
  const rows = Array.isArray(response?.tasks)
    ? response.tasks
    : Array.isArray(response?.items)
      ? response.items
      : Array.isArray(response)
        ? response
        : [];
  rows.forEach((row: AnyRecord) => {
    if (row?.id) tasks.set(String(row.id), row);
  });
  const task = response?.task || (response?.id ? response : null);
  if (task?.id) tasks.set(String(task.id), task);
  return task || null;
}

async function getObservation(observationId: string): Promise<AnyRecord | null> {
  if (!observationId) return null;
  const cached = observations.get(observationId);
  if (cached) return cached;
  const response = await (apiClient as any).fieldIntelligence.observation(observationId);
  return rememberObservationResponse(response);
}

function linkedObservationEvidence(observation: AnyRecord): AnyRecord {
  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};
  const payload = {
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
  };
  return {
    filename: `Field Intelligence observation ${String(observation.id).slice(0, 8)}`,
    source_type: "field_observation",
    import_status: "linked",
    observation_id: observation.id,
    parsed_preview: JSON.stringify(payload).slice(0, 12000),
  };
}

function patchApiClient(): void {
  const client = apiClient as any;
  const fieldIntelligence = client.fieldIntelligence;
  const fieldOps = client.fieldOps;

  if (fieldIntelligence?.observations && !fieldIntelligence.observations.__agroAiOperatingLoop) {
    const original = fieldIntelligence.observations.bind(fieldIntelligence);
    const wrapped = async (...args: any[]) => {
      const response = await original(...args);
      rememberObservationResponse(response);
      scheduleEnhancement();
      return response;
    };
    wrapped.__agroAiOperatingLoop = true;
    fieldIntelligence.observations = wrapped;
  }

  if (fieldIntelligence?.observation && !fieldIntelligence.observation.__agroAiOperatingLoop) {
    const original = fieldIntelligence.observation.bind(fieldIntelligence);
    const wrapped = async (...args: any[]) => {
      const response = await original(...args);
      rememberObservationResponse(response);
      scheduleEnhancement();
      return response;
    };
    wrapped.__agroAiOperatingLoop = true;
    fieldIntelligence.observation = wrapped;
  }

  if (fieldIntelligence?.createTask && !fieldIntelligence.createTask.__agroAiOperatingLoop) {
    const original = fieldIntelligence.createTask.bind(fieldIntelligence);
    const wrapped = async (observationId: string, payload: AnyRecord = {}) => {
      activeObservationId = String(observationId || activeObservationId);
      try {
        const response = await original(observationId, payload);
        const task = rememberTaskResponse(response);
        if (!task?.id) throw new Error("The server did not return the created task.");
        window.dispatchEvent(new CustomEvent(TASK_READY_EVENT, {
          detail: { observationId, task, response },
        }));
        scheduleEnhancement();
        return response;
      } catch (error) {
        window.dispatchEvent(new CustomEvent(TASK_ERROR_EVENT, {
          detail: {
            observationId,
            message: error instanceof Error ? error.message : String(error || "Task creation failed"),
          },
        }));
        throw error;
      }
    };
    wrapped.__agroAiOperatingLoop = true;
    fieldIntelligence.createTask = wrapped;
  }

  if (fieldOps?.tasks && !fieldOps.tasks.__agroAiOperatingLoop) {
    const original = fieldOps.tasks.bind(fieldOps);
    const wrapped = async (...args: any[]) => {
      const response = await original(...args);
      rememberTaskResponse(response);
      scheduleEnhancement();
      return response;
    };
    wrapped.__agroAiOperatingLoop = true;
    fieldOps.tasks = wrapped;
  }

  if (client.post && !client.post.__agroAiOperatingLoop) {
    const originalPost = client.post.bind(client);
    const wrappedPost = async (path: string, body?: AnyRecord, ...rest: any[]) => {
      if (INTELLIGENCE_EXECUTION_PATHS.has(String(path))) {
        const observationId = new URLSearchParams(window.location.search || "").get(OBSERVATION_PARAM) || "";
        if (observationId) {
          const observation = await getObservation(observationId).catch(() => null);
          if (observation) {
            const existingEvidence = Array.isArray(body?.uploaded_evidence) ? body.uploaded_evidence : [];
            const withoutDuplicate = existingEvidence.filter(
              (item: AnyRecord) => String(item?.observation_id || "") !== observationId,
            );
            body = {
              ...(body || {}),
              field_id: body?.field_id || observation.field_id,
              field_observation_id: observationId,
              uploaded_evidence: [linkedObservationEvidence(observation), ...withoutDuplicate],
            };
          }
        }
      }
      return originalPost(path, body, ...rest);
    };
    wrappedPost.__agroAiOperatingLoop = true;
    client.post = wrappedPost;
  }
}

function scoreObservation(observation: AnyRecord, sourceText: string): number {
  const haystack = normalize(sourceText);
  let score = 0;
  const candidates = [
    observation.field_name,
    observation.block_name,
    observation.summary,
    observation.corrected_transcript,
    observation.transcript,
  ];
  candidates.forEach((candidate, index) => {
    const normalized = normalize(candidate);
    if (!normalized) return;
    const fragment = normalized.slice(0, index < 2 ? 40 : 72);
    if (fragment.length >= 4 && haystack.includes(fragment)) score += index < 2 ? 4 : 7;
  });
  return score;
}

function observationForElement(element: Element | null): AnyRecord | null {
  const directId = currentObservationId();
  if (directId && observations.has(directId)) return observations.get(directId) || null;
  if (!element) return null;
  const sourceText = text((element as HTMLElement).innerText || element.textContent);
  let winner: AnyRecord | null = null;
  let winnerScore = 0;
  observations.forEach((observation) => {
    const score = scoreObservation(observation, sourceText);
    if (score > winnerScore) {
      winner = observation;
      winnerScore = score;
    }
  });
  return winnerScore >= 4 ? winner : null;
}

function setActiveObservation(observation: AnyRecord | null): void {
  if (!observation?.id) return;
  activeObservationId = String(observation.id);
  rememberObservation(observation);
  if (window.location.pathname === "/field-intelligence") {
    const url = new URL(window.location.href);
    url.searchParams.set(ACTIVE_OBSERVATION_PARAM, activeObservationId);
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }
}

function createElement<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  styles?: Partial<CSSStyleDeclaration>,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (styles) Object.assign(element.style, styles);
  return element;
}

function makeActionLink(label: string, href: string, primary = false): HTMLAnchorElement {
  const link = createElement("a", {
    alignItems: "center",
    background: primary ? "#0D2B1E" : "#FFFDF8",
    border: primary ? "1px solid #0D2B1E" : "1px solid #D6DDD0",
    borderRadius: "10px",
    color: primary ? "#FFFFFF" : "#10231B",
    display: "inline-flex",
    fontSize: "12px",
    fontWeight: "700",
    justifyContent: "center",
    minHeight: "40px",
    padding: "8px 12px",
    textDecoration: "none",
  });
  link.textContent = label;
  link.href = href;
  return link;
}

function showTaskToast(detail: AnyRecord, isError = false): void {
  document.querySelectorAll("[data-fi-operating-loop-toast]").forEach((node) => node.remove());
  const toast = createElement("section", {
    background: isError ? "#FFF4F1" : "#FFFDF8",
    border: `1px solid ${isError ? "#E6B7AD" : "#BFD8C9"}`,
    borderRadius: "18px",
    bottom: "max(18px, env(safe-area-inset-bottom))",
    boxShadow: "0 24px 70px rgba(16,35,27,0.24)",
    color: "#10231B",
    left: "max(14px, env(safe-area-inset-left))",
    maxWidth: "430px",
    padding: "16px",
    position: "fixed",
    right: "max(14px, env(safe-area-inset-right))",
    zIndex: "10000",
  });
  toast.dataset.fiOperatingLoopToast = "true";
  toast.setAttribute("role", isError ? "alert" : "status");

  const header = createElement("div", { alignItems: "flex-start", display: "flex", gap: "12px", justifyContent: "space-between" });
  const copy = createElement("div", { minWidth: "0" });
  const title = createElement("div", { color: isError ? "#9F2D20" : "#1B5E3F", fontSize: "13px", fontWeight: "800" });
  title.textContent = isError ? "Task could not be created" : "Task created and linked";
  const description = createElement("div", { color: "#536158", fontSize: "12px", lineHeight: "1.55", marginTop: "5px" });
  description.textContent = isError
    ? text(detail?.message, "Please retry from the observation.")
    : text(detail?.task?.title, "The observation is now accountable work in Tasks.");
  copy.append(title, description);

  const close = createElement("button", { background: "transparent", border: "0", color: "#65736A", cursor: "pointer", fontSize: "20px", lineHeight: "1", padding: "0" });
  close.type = "button";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  close.addEventListener("click", () => toast.remove());
  header.append(copy, close);
  toast.append(header);

  if (!isError && detail?.task?.id) {
    const actions = createElement("div", { display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "13px" });
    const taskId = encodeURIComponent(String(detail.task.id));
    const observationId = encodeURIComponent(String(detail.observationId || activeObservationId));
    actions.append(
      makeActionLink("Open task", `/tasks?task_id=${taskId}&observation_id=${observationId}`, true),
      makeActionLink(t("fieldIntelligence"), `/field-intelligence?observation_id=${observationId}`),
    );
    toast.append(actions);
  }
  document.body.append(toast);
  if (!isError) window.setTimeout(() => toast.remove(), 14_000);
}

function workflowStep(label: string, complete: boolean, index: number): HTMLElement {
  const item = createElement("div", {
    background: complete ? "#EDF7F1" : "#F6F4EE",
    border: `1px solid ${complete ? "#8FC3A6" : "#D6DDD0"}`,
    borderRadius: "10px",
    color: complete ? "#1B5E3F" : "#65736A",
    fontSize: "10px",
    fontWeight: "700",
    lineHeight: "1.35",
    minWidth: "0",
    padding: "8px 5px",
    textAlign: "center",
  });
  const number = createElement("div", { fontSize: "10px", opacity: "0.75" });
  number.textContent = String(index + 1);
  const textNode = createElement("div", { marginTop: "3px", overflow: "hidden", textOverflow: "ellipsis" });
  textNode.textContent = label;
  item.append(number, textNode);
  return item;
}

function enhanceObservationDrawer(): void {
  const dialog = document.querySelector<HTMLElement>("[role='dialog']");
  const drawer = dialog?.querySelector<HTMLElement>("aside");
  if (!drawer) return;
  const observation = observationForElement(drawer);
  if (observation) setActiveObservation(observation);

  if (!drawer.querySelector("[data-fi-operating-loop]") && observation) {
    const container = createElement("section", {
      background: "#FFFDF8",
      border: "1px solid #D6DDD0",
      borderRadius: "14px",
      marginTop: "16px",
      padding: "13px",
    });
    container.dataset.fiOperatingLoop = "true";
    const heading = createElement("div", { color: "#10231B", fontSize: "12px", fontWeight: "800" });
    heading.textContent = "One observation. One operating loop.";
    const body = createElement("div", { color: "#65736A", fontSize: "11px", lineHeight: "1.5", marginTop: "4px" });
    body.textContent = "The transcript, media analysis, evidence, uncertainty, AGRO-AI discussion, and task stay linked.";
    const steps = createElement("div", { display: "grid", gap: "5px", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", marginTop: "11px" });
    const vision = observation?.structured?.vision || {};
    const taskId = String(observation?.task_ids?.[0] || observation?.task_ids_json?.[0] || "");
    steps.append(
      workflowStep("Capture", true, 0),
      workflowStep("Understand", Boolean(observation.summary || observation.transcript || vision.summary), 1),
      workflowStep("Decide", Boolean(observation.recommended_action || vision.recommended_follow_up), 2),
      workflowStep("Act", Boolean(taskId), 3),
    );
    container.append(heading, body, steps);
    drawer.firstElementChild?.insertAdjacentElement("afterend", container);
  }
}

function tryOpenDirectObservation(): void {
  if (window.location.pathname !== "/field-intelligence") return;
  const observationId = new URLSearchParams(window.location.search || "").get(ACTIVE_OBSERVATION_PARAM) || "";
  if (!observationId || directObservationOpened.has(observationId) || document.querySelector("[role='dialog']")) return;
  const observation = observations.get(observationId);
  if (!observation) return;
  const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>("button"))
    .filter((button) => !button.closest("[role='dialog']"));
  const best = buttons
    .map((button) => ({ button, score: scoreObservation(observation, button.innerText) }))
    .sort((a, b) => b.score - a.score)[0];
  if (best && best.score >= 4) {
    directObservationOpened.add(observationId);
    activeObservationId = observationId;
    best.button.click();
  }
}

function contextPrompt(observation: AnyRecord): string {
  const summary = text(
    observation.summary || observation.corrected_transcript || observation.transcript,
    "Review the linked field observation.",
  );
  return [
    "Analyze this linked Field Intelligence observation as one operational case.",
    "Use its transcript, media analysis, visible facts, hypotheses, evidence, and uncertainty. Separate confirmed facts from hypotheses, explain what matters, state what must be verified, and recommend the best next accountable action. Do not invent measurements or diagnoses.",
    summary,
  ].join("\n\n");
}

function setControlledTextarea(textarea: HTMLTextAreaElement, value: string): void {
  const descriptor = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
  descriptor?.set?.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.dispatchEvent(new Event("change", { bubbles: true }));
}

async function autoStartContextualAsk(observation: AnyRecord): Promise<void> {
  const observationId = String(observation.id || "");
  if (!observationId || contextSent.has(observationId)) return;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const textarea = document.querySelector<HTMLTextAreaElement>("textarea");
    if (textarea) {
      contextSent.add(observationId);
      if (!textarea.value.trim()) setControlledTextarea(textarea, contextPrompt(observation));
      for (let buttonAttempt = 0; buttonAttempt < 20; buttonAttempt += 1) {
        const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
        const sendButton = buttons.find((button) => button.querySelector("svg") && button.closest("footer") && !button.disabled)
          || buttons.find((button) => button.title && normalize(button.title) === normalize(t("send")) && !button.disabled);
        if (sendButton) {
          sendButton.click();
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 100));
      }
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 125));
  }
}

async function enhanceContextualAsk(): Promise<void> {
  if (window.location.pathname !== "/intelligence") return;
  const observationId = new URLSearchParams(window.location.search || "").get(OBSERVATION_PARAM) || "";
  if (!observationId) return;
  const observation = await getObservation(observationId).catch(() => null);
  if (!observation) return;
  activeObservationId = observationId;

  const existing = document.querySelector<HTMLElement>("[data-fi-linked-context]");
  if (!existing) {
    const header = document.querySelector<HTMLElement>("main header");
    if (header) {
      const banner = createElement("section", {
        background: "#EDF7F1",
        borderBottom: "1px solid #BFD8C9",
        color: "#10231B",
        padding: "14px clamp(16px, 4vw, 32px)",
      });
      banner.dataset.fiLinkedContext = observationId;
      const inner = createElement("div", { alignItems: "flex-start", display: "flex", flexWrap: "wrap", gap: "12px", justifyContent: "space-between", margin: "0 auto", maxWidth: "900px" });
      const copy = createElement("div", { flex: "1 1 420px", minWidth: "0" });
      const eyebrow = createElement("div", { color: "#2D6A4F", fontSize: "10px", fontWeight: "800", letterSpacing: "0.12em", textTransform: "uppercase" });
      eyebrow.textContent = `${t("fieldIntelligence")} · linked context`;
      const title = createElement("div", { color: "#10231B", fontSize: "14px", fontWeight: "800", marginTop: "5px" });
      title.textContent = text(observation.field_name || observation.block_name, "Field observation");
      const summary = createElement("div", { color: "#536158", fontSize: "12px", lineHeight: "1.55", marginTop: "4px" });
      summary.textContent = text(observation.summary || observation.corrected_transcript || observation.transcript, "The exact observation is attached to this AGRO-AI thread.");
      copy.append(eyebrow, title, summary);
      const actions = createElement("div", { display: "flex", flex: "0 1 auto", flexWrap: "wrap", gap: "8px" });
      actions.append(
        makeActionLink("Open observation", `/field-intelligence?observation_id=${encodeURIComponent(observationId)}`),
        makeActionLink(t("tasks"), "/tasks", true),
      );
      inner.append(copy, actions);
      banner.append(inner);
      header.insertAdjacentElement("afterend", banner);
    }
  }
  void autoStartContextualAsk(observation);
}

function operatingLoopNavigation(): HTMLElement {
  const nav = createElement("nav", {
    display: "grid",
    gap: "7px",
    gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
    margin: "0 0 16px",
  });
  nav.dataset.fiPortalLoop = "true";
  const rows = [
    ["1", "Capture", "/field-intelligence"],
    ["2", "Understand", "/field-queue"],
    ["3", "Decide", "/intelligence"],
    ["4", "Act", "/tasks"],
  ];
  rows.forEach(([step, label, href]) => {
    const active = window.location.pathname === href || (href === "/field-queue" && window.location.pathname === "/");
    const link = createElement("a", {
      background: active ? "#0D2B1E" : "#FFFDF8",
      border: `1px solid ${active ? "#0D2B1E" : "#D6DDD0"}`,
      borderRadius: "12px",
      color: active ? "#FFFFFF" : "#10231B",
      minWidth: "0",
      padding: "10px 6px",
      textAlign: "center",
      textDecoration: "none",
    });
    link.href = href;
    const number = createElement("div", { fontSize: "9px", fontWeight: "800", opacity: "0.65" });
    number.textContent = step;
    const copy = createElement("div", { fontSize: "11px", fontWeight: "800", marginTop: "3px", overflow: "hidden", textOverflow: "ellipsis" });
    copy.textContent = label;
    link.append(number, copy);
    nav.append(link);
  });
  return nav;
}

function enhanceOperatingRoom(): void {
  if (!["/", "/tasks", "/field-queue"].includes(window.location.pathname)) return;
  const content = document.querySelector<HTMLElement>("main") || document.querySelector<HTMLElement>("[class*='min-h-full']");
  const heading = content?.querySelector<HTMLHeadingElement>("h1");
  if (!content || !heading) return;

  if (window.location.pathname === "/tasks") {
    heading.textContent = t("tasks");
  } else if (window.location.pathname === "/field-queue") {
    heading.textContent = "Field Queue";
  }

  if (!content.querySelector("[data-fi-portal-loop]")) {
    const section = heading.closest("section") || heading.parentElement?.parentElement || heading.parentElement;
    section?.insertAdjacentElement("afterend", operatingLoopNavigation());
  }

  const focusedTaskId = new URLSearchParams(window.location.search || "").get("task_id") || "";
  tasks.forEach((task, taskId) => {
    const title = normalize(task.title);
    if (!title) return;
    const card = Array.from(content.querySelectorAll<HTMLElement>("article"))
      .find((article) => normalize(article.innerText).includes(title));
    if (!card) return;
    if (taskId === focusedTaskId) {
      card.style.borderColor = "#2D6A4F";
      card.style.boxShadow = "0 0 0 3px rgba(45,106,79,0.12)";
      card.style.background = "#EDF7F1";
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    const observationId = String(task.source_observation_id || "");
    if (!observationId || card.querySelector("[data-fi-task-source]")) return;
    const source = createElement("div", {
      background: "#FFFDF8",
      border: "1px solid #D6DDD0",
      borderRadius: "11px",
      marginTop: "12px",
      padding: "11px",
    });
    source.dataset.fiTaskSource = observationId;
    const label = createElement("div", { color: "#65736A", fontSize: "10px", fontWeight: "800", letterSpacing: "0.1em", textTransform: "uppercase" });
    label.textContent = `${t("fieldIntelligence")} · source observation`;
    const actions = createElement("div", { display: "flex", flexWrap: "wrap", gap: "7px", marginTop: "8px" });
    actions.append(
      makeActionLink("Review observation", `/field-intelligence?observation_id=${encodeURIComponent(observationId)}`),
      makeActionLink(t("askAgroAi"), `/intelligence?field_observation_id=${encodeURIComponent(observationId)}&source=task`, true),
    );
    source.append(label, actions);
    card.append(source);
  });
}

function enhancePage(): void {
  tryOpenDirectObservation();
  enhanceObservationDrawer();
  void enhanceContextualAsk();
  enhanceOperatingRoom();
}

function scheduleEnhancement(): void {
  if (enhancementQueued) return;
  enhancementQueued = true;
  window.requestAnimationFrame(() => {
    enhancementQueued = false;
    enhancePage();
  });
}

function patchHistory(): void {
  (["pushState", "replaceState"] as const).forEach((method) => {
    const original = window.history[method].bind(window.history);
    (window.history as any)[method] = (...args: any[]) => {
      const result = original(...args);
      window.dispatchEvent(new Event(LOCATION_EVENT));
      return result;
    };
  });
  window.addEventListener("popstate", () => window.dispatchEvent(new Event(LOCATION_EVENT)));
  window.addEventListener(LOCATION_EVENT, scheduleEnhancement);
}

function installClickBridge(): void {
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    if (window.location.pathname === "/field-intelligence") {
      const dialog = target.closest("[role='dialog']");
      const anchor = target.closest<HTMLAnchorElement>("a[href]");
      if (dialog && anchor) {
        const url = new URL(anchor.href, window.location.origin);
        if (url.pathname === "/intelligence") {
          const observation = observationForElement(dialog);
          const observationId = String(observation?.id || currentObservationId());
          if (observationId) {
            event.preventDefault();
            activeObservationId = observationId;
            window.location.assign(`/intelligence?field_observation_id=${encodeURIComponent(observationId)}&source=field-intelligence`);
            return;
          }
        }
      }

      const button = target.closest<HTMLButtonElement>("button");
      if (button && !dialog) {
        const observation = observationForElement(button);
        if (observation) setActiveObservation(observation);
      }
    }
    scheduleEnhancement();
  }, true);
}

function install(): void {
  if (window.__agroAiFieldIntelligenceOperatingLoop) return;
  window.__agroAiFieldIntelligenceOperatingLoop = true;
  patchApiClient();
  patchHistory();
  installClickBridge();
  window.addEventListener(TASK_READY_EVENT, (event) => showTaskToast((event as CustomEvent).detail));
  window.addEventListener(TASK_ERROR_EVENT, (event) => showTaskToast((event as CustomEvent).detail, true));
  const observer = new MutationObserver(scheduleEnhancement);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  scheduleEnhancement();
}

try {
  if (typeof window !== "undefined" && typeof document !== "undefined") install();
} catch (error) {
  // This bridge must never be capable of taking down the portal shell.  All
  // canonical capture and task routes remain available if enhancement fails.
  console.error("AGRO-AI Field Intelligence operating-loop enhancement failed", error);
}
