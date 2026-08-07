import { apiClient } from "../api/client";
import { t } from "../i18n";

type AnyRecord = Record<string, any>;

const ACTIVE_PARAM = "observation_id";
const CONTEXT_PARAM = "field_observation_id";
const observations = new Map<string, AnyRecord>();
const tasks = new Map<string, AnyRecord>();
let activeObservationId = "";
let enhancementQueued = false;
let refreshBusy = false;

declare global {
  interface Window {
    __agroAiFieldIntelligenceDirectWorkflowV2?: boolean;
  }
}

function normalize(value: unknown): string {
  return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function safeText(value: unknown): string {
  if (typeof value === "string") {
    const clean = value.replace(/\s+/g, " ").trim();
    return normalize(clean) === "[object object]" ? "" : clean;
  }
  if (value && typeof value === "object") {
    const row = value as AnyRecord;
    for (const key of ["summary", "text", "label", "message", "description", "value"]) {
      const clean = safeText(row[key]);
      if (clean) return clean;
    }
  }
  return "";
}

function summaryFor(observation: AnyRecord): string {
  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};
  return safeText(observation?.summary)
    || safeText(vision?.summary)
    || safeText(observation?.corrected_transcript)
    || safeText(observation?.transcript)
    || "Field observation";
}

function recommendationFor(observation: AnyRecord): string {
  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};
  const correlation = observation?.correlation || observation?.correlation_json || {};
  return safeText(observation?.recommended_action)
    || safeText(vision?.recommended_follow_up)
    || safeText(correlation?.recommended_next_action);
}

function observationTaskIds(observation: AnyRecord): string[] {
  const values = observation?.task_ids || observation?.task_ids_json || [];
  return Array.isArray(values) ? values.map((value) => String(value || "")).filter(Boolean) : [];
}

function rememberObservation(row: AnyRecord | null | undefined): void {
  if (row?.id) observations.set(String(row.id), row);
}

function rememberObservationResponse(response: AnyRecord): void {
  const single = response?.observation || (response?.id ? response : null);
  if (single) rememberObservation(single);
  const rows = Array.isArray(response?.observations)
    ? response.observations
    : Array.isArray(response?.items)
      ? response.items
      : Array.isArray(response)
        ? response
        : [];
  rows.forEach((row: AnyRecord) => rememberObservation(row));
}

function rememberTaskResponse(response: AnyRecord): void {
  const rows = Array.isArray(response?.tasks)
    ? response.tasks
    : Array.isArray(response?.items)
      ? response.items
      : Array.isArray(response)
        ? response
        : [];
  rows.forEach((row: AnyRecord) => { if (row?.id) tasks.set(String(row.id), row); });
  const single = response?.task || (response?.id ? response : null);
  if (single?.id) tasks.set(String(single.id), single);
}

function linkedTask(observation: AnyRecord): AnyRecord | null {
  const explicit = observationTaskIds(observation);
  for (const id of explicit) {
    const task = tasks.get(id);
    if (task) return task;
  }
  for (const task of tasks.values()) {
    if (String(task?.source_observation_id || "") === String(observation?.id || "")) return task;
  }
  return null;
}

function currentObservationId(): string {
  const params = new URLSearchParams(window.location.search || "");
  return params.get(ACTIVE_PARAM) || activeObservationId || "";
}

function setActiveObservation(observation: AnyRecord): void {
  if (!observation?.id) return;
  activeObservationId = String(observation.id);
  rememberObservation(observation);
  if (window.location.pathname !== "/field-intelligence") return;
  const url = new URL(window.location.href);
  if (url.searchParams.get(ACTIVE_PARAM) === activeObservationId) return;
  url.searchParams.set(ACTIVE_PARAM, activeObservationId);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

function scoreObservation(observation: AnyRecord, sourceText: string): number {
  const haystack = normalize(sourceText);
  if (!haystack) return 0;
  let score = 0;
  const field = normalize(observation?.field_name);
  const block = normalize(observation?.block_name);
  const summary = normalize(summaryFor(observation));
  const transcript = normalize(observation?.corrected_transcript || observation?.transcript);
  if (field && haystack.includes(field.slice(0, 60))) score += 5;
  if (block && haystack.includes(block.slice(0, 60))) score += 4;
  if (summary.length >= 5 && haystack.includes(summary.slice(0, 90))) score += 10;
  if (transcript.length >= 5 && haystack.includes(transcript.slice(0, 90))) score += 8;
  const occurred = observation?.occurred_at ? new Date(observation.occurred_at) : null;
  if (occurred && !Number.isNaN(occurred.getTime())) {
    const local = normalize(occurred.toLocaleString());
    if (local && haystack.includes(local)) score += 5;
  }
  return score;
}

function observationForElement(element: Element | null, preferActive = false): AnyRecord | null {
  const directId = currentObservationId();
  if (preferActive && directId && observations.has(directId)) return observations.get(directId) || null;
  if (!element) return null;
  const sourceText = (element as HTMLElement).innerText || element.textContent || "";
  let winner: AnyRecord | null = null;
  let score = 0;
  for (const observation of observations.values()) {
    const next = scoreObservation(observation, sourceText);
    if (next > score) {
      score = next;
      winner = observation;
    }
  }
  return score >= 5 ? winner : null;
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, styles?: Partial<CSSStyleDeclaration>) {
  const node = document.createElement(tag);
  if (styles) Object.assign(node.style, styles);
  return node;
}

function actionLink(label: string, href: string, primary = false): HTMLAnchorElement {
  const link = element("a", {
    alignItems: "center",
    background: primary ? "#0D2B1E" : "#FFFFFF",
    border: primary ? "1px solid #0D2B1E" : "1px solid #D6DDD0",
    borderRadius: "10px",
    color: primary ? "#FFFFFF" : "#10231B",
    display: "inline-flex",
    fontSize: "12px",
    fontWeight: "700",
    justifyContent: "center",
    minHeight: "42px",
    padding: "8px 12px",
    textDecoration: "none",
  });
  link.href = href;
  link.textContent = label;
  return link;
}

function taskButton(label: string): HTMLButtonElement {
  const button = element("button", {
    alignItems: "center",
    background: "#0D2B1E",
    border: "1px solid #0D2B1E",
    borderRadius: "10px",
    color: "#FFFFFF",
    cursor: "pointer",
    display: "inline-flex",
    fontSize: "12px",
    fontWeight: "700",
    justifyContent: "center",
    minHeight: "42px",
    padding: "8px 12px",
  });
  button.type = "button";
  button.textContent = label;
  return button;
}

function workflowStep(label: string, complete: boolean, current: boolean, index: number): HTMLElement {
  const node = element("div", {
    background: complete ? "#EDF7F1" : current ? "#FFF9EA" : "#F7F8F5",
    border: `1px solid ${complete ? "#8FC3A6" : current ? "#E4C780" : "#DCE2DC"}`,
    borderRadius: "10px",
    color: complete ? "#1B5E3F" : current ? "#7A5700" : "#65736A",
    minWidth: "0",
    padding: "8px 4px",
    textAlign: "center",
  });
  const number = element("div", { fontSize: "9px", fontWeight: "800", opacity: "0.7" });
  number.textContent = String(index + 1);
  const copy = element("div", { fontSize: "10px", fontWeight: "800", marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis" });
  copy.textContent = label;
  node.append(number, copy);
  return node;
}

function isTaskClosed(task: AnyRecord | null): boolean {
  const status = normalize(task?.status);
  return ["completed", "complete", "closed", "done", "verified", "acknowledged"].includes(status);
}

function renderWorkflowPanel(drawer: HTMLElement, observation: AnyRecord): void {
  const observationId = String(observation.id || "");
  if (!observationId) return;

  drawer.querySelectorAll<HTMLElement>("[data-fi-direct-workflow]").forEach((node) => node.remove());
  drawer.querySelectorAll<HTMLElement>("[data-fi-operating-loop]").forEach((node) => { node.style.display = "none"; });

  const askLink = Array.from(drawer.querySelectorAll<HTMLAnchorElement>("a[href]"))
    .find((link) => new URL(link.href, window.location.origin).pathname === "/intelligence");
  if (askLink) {
    askLink.href = `/intelligence?${CONTEXT_PARAM}=${encodeURIComponent(observationId)}&source=field-intelligence`;
  }

  const legacyActionRow = askLink?.parentElement;
  if (legacyActionRow && legacyActionRow.querySelector("button")) legacyActionRow.style.display = "none";

  const task = linkedTask(observation);
  const explicitTaskId = observationTaskIds(observation)[0] || String(task?.id || "");
  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};
  const understood = Boolean(summaryFor(observation) || observation?.transcript || vision?.summary);
  const decided = Boolean(recommendationFor(observation));
  const acted = Boolean(explicitTaskId || task);
  const verified = isTaskClosed(task);
  const stages = [true, understood, decided, acted, verified];
  const firstIncomplete = stages.findIndex((complete) => !complete);

  const panel = element("section", {
    background: "#FFFDF8",
    border: "1px solid #C8D7CC",
    borderRadius: "14px",
    marginTop: "14px",
    padding: "13px",
  });
  panel.dataset.fiDirectWorkflow = observationId;
  panel.dataset.fiOperatingLoop = "true";

  const title = element("div", { color: "#10231B", fontSize: "12px", fontWeight: "800" });
  title.textContent = "Observation to action";
  const description = element("div", { color: "#65736A", fontSize: "11px", lineHeight: "1.5", marginTop: "4px" });
  description.textContent = "Voice, video, AGRO-AI analysis, the decision, the task, and verification stay attached to this observation.";
  const steps = element("div", { display: "grid", gap: "5px", gridTemplateColumns: "repeat(5,minmax(0,1fr))", marginTop: "11px" });
  ["Capture", "Understand", "Decide", "Act", "Verify"].forEach((label, index) => {
    steps.append(workflowStep(label, stages[index], firstIncomplete === index, index));
  });
  panel.append(title, description, steps);

  const recommendation = recommendationFor(observation);
  if (recommendation) {
    const next = element("div", {
      background: "#F3F8F5",
      border: "1px solid #D8E5DC",
      borderRadius: "10px",
      color: "#3B4A41",
      fontSize: "11px",
      lineHeight: "1.55",
      marginTop: "11px",
      padding: "10px",
    });
    const label = element("div", { color: "#2D6A4F", fontSize: "9px", fontWeight: "800", letterSpacing: "0.1em", textTransform: "uppercase" });
    label.textContent = "Recommended next action";
    const body = element("div", { marginTop: "3px" });
    body.textContent = recommendation;
    next.append(label, body);
    panel.append(next);
  }

  const status = element("div", { display: explicitTaskId ? "block" : "none", fontSize: "11px", lineHeight: "1.5", marginTop: "10px", padding: "9px 10px", borderRadius: "9px" });
  status.dataset.fiDirectStatus = "true";
  if (explicitTaskId) {
    status.style.background = "#EDF7F1";
    status.style.border = "1px solid #BFD8C9";
    status.style.color = "#1B5E3F";
    status.textContent = "Task created and linked to this observation.";
  }
  panel.append(status);

  const actions = element("div", { display: "grid", gap: "8px", gridTemplateColumns: "repeat(2,minmax(0,1fr))", marginTop: "11px" });
  const ask = actionLink(t("askAgroAi"), `/intelligence?${CONTEXT_PARAM}=${encodeURIComponent(observationId)}&source=field-intelligence`, true);

  if (explicitTaskId) {
    const open = actionLink("Open task", `/tasks?task_id=${encodeURIComponent(explicitTaskId)}&observation_id=${encodeURIComponent(observationId)}`);
    actions.append(open, ask);
  } else {
    const create = taskButton(t("fieldIntel.createTask"));
    create.addEventListener("click", async () => {
      create.disabled = true;
      create.style.opacity = "0.6";
      create.textContent = "Creating task…";
      status.style.display = "none";
      try {
        const response: AnyRecord = await (apiClient as any).fieldIntelligence.createTask(observationId, {});
        rememberTaskResponse(response);
        const created = response?.task || response;
        if (!created?.id) throw new Error("The server did not return the created task.");
        const current = observations.get(observationId) || observation;
        current.task_ids = [String(created.id)];
        current.task_ids_json = [String(created.id)];
        observations.set(observationId, current);
        status.style.display = "block";
        status.style.background = "#EDF7F1";
        status.style.border = "1px solid #BFD8C9";
        status.style.color = "#1B5E3F";
        status.textContent = "Task created and linked to this observation.";
        renderWorkflowPanel(drawer, current);
        void refreshData();
      } catch (error) {
        status.style.display = "block";
        status.style.background = "#FFF4F1";
        status.style.border = "1px solid #E6B7AD";
        status.style.color = "#9F2D20";
        status.textContent = error instanceof Error ? error.message : "Task could not be created. Please retry.";
        create.disabled = false;
        create.style.opacity = "1";
        create.textContent = t("fieldIntel.createTask");
      }
    });
    actions.append(create, ask);
  }
  panel.append(actions);

  const recommendationSection = legacyActionRow?.closest("section");
  if (recommendationSection) recommendationSection.append(panel);
  else drawer.firstElementChild?.insertAdjacentElement("afterend", panel);
}

function cleanTimeline(): void {
  if (window.location.pathname !== "/field-intelligence") return;
  const main = document.querySelector<HTMLElement>("main") || document.body;
  const buttons = Array.from(main.querySelectorAll<HTMLButtonElement>("button"))
    .filter((button) => !button.closest("[role='dialog']"));
  for (const button of buttons) {
    const observation = observationForElement(button, false);
    if (!observation?.id) continue;
    button.dataset.fiObservationId = String(observation.id);
    const summary = summaryFor(observation);
    if (summary) {
      Array.from(button.querySelectorAll<HTMLElement>("p"))
        .filter((node) => normalize(node.textContent).includes("[object object]"))
        .forEach((node) => { node.textContent = summary; });
    }
    if (observation.confidence == null && ["staged", "processing"].includes(normalize(observation.status))) {
      Array.from(button.querySelectorAll<HTMLElement>("span"))
        .filter((node) => /confidence\s*:\s*0%/i.test(node.textContent || ""))
        .forEach((node) => { node.textContent = t("fieldIntel.state.processing"); });
    }
  }
}

function enhanceDrawer(): void {
  if (window.location.pathname !== "/field-intelligence") return;
  const dialog = document.querySelector<HTMLElement>("[role='dialog']");
  const drawer = dialog?.querySelector<HTMLElement>("aside");
  if (!drawer) return;
  const observation = observationForElement(drawer, true);
  if (!observation) return;
  setActiveObservation(observation);
  const existing = drawer.querySelector<HTMLElement>(`[data-fi-direct-workflow='${CSS.escape(String(observation.id))}']`);
  if (!existing) renderWorkflowPanel(drawer, observation);
}

function enhancePage(): void {
  cleanTimeline();
  enhanceDrawer();
}

function scheduleEnhancement(): void {
  if (enhancementQueued) return;
  enhancementQueued = true;
  window.requestAnimationFrame(() => {
    enhancementQueued = false;
    enhancePage();
  });
}

async function refreshData(): Promise<void> {
  if (refreshBusy || window.location.pathname !== "/field-intelligence") return;
  refreshBusy = true;
  try {
    const [observationResponse, taskResponse] = await Promise.all([
      (apiClient as any).fieldIntelligence.observations("limit=200").catch(() => null),
      Promise.resolve((apiClient as any).fieldOps?.tasks?.()).catch(() => null),
    ]);
    if (observationResponse) rememberObservationResponse(observationResponse);
    if (taskResponse) rememberTaskResponse(taskResponse);
    const directId = new URLSearchParams(window.location.search || "").get(ACTIVE_PARAM) || "";
    if (directId && !observations.has(directId)) {
      const response = await (apiClient as any).fieldIntelligence.observation(directId).catch(() => null);
      if (response) rememberObservationResponse(response);
    }
  } finally {
    refreshBusy = false;
    scheduleEnhancement();
  }
}

function install(): void {
  if (window.__agroAiFieldIntelligenceDirectWorkflowV2) return;
  window.__agroAiFieldIntelligenceDirectWorkflowV2 = true;

  document.addEventListener("click", (event) => {
    if (window.location.pathname !== "/field-intelligence") return;
    const target = event.target instanceof Element ? event.target : null;
    const button = target?.closest<HTMLButtonElement>("button[data-fi-observation-id]");
    if (button) {
      const observation = observations.get(String(button.dataset.fiObservationId || ""));
      if (observation) setActiveObservation(observation);
    }
    window.setTimeout(scheduleEnhancement, 0);
  }, true);

  const observer = new MutationObserver(scheduleEnhancement);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("popstate", () => { void refreshData(); });
  window.addEventListener("agroai:location-change", () => { void refreshData(); });
  window.addEventListener("agroai:field-intelligence-task-ready", (event) => {
    const detail = (event as CustomEvent).detail || {};
    if (detail.response) rememberTaskResponse(detail.response);
    void refreshData();
  });

  void refreshData();
  window.setInterval(() => { void refreshData(); }, 7000);
}

try {
  if (typeof window !== "undefined" && typeof document !== "undefined") install();
} catch (error) {
  console.error("AGRO-AI Field Intelligence direct workflow enhancement failed", error);
}
