import { apiClient } from "../api/client";
import {
  ensureLocaleSourceCatalog,
  primeLocaleSourceCatalogFromCache,
} from "../dynamicLocaleCatalog";
import { getStoredLocale, normalizeLocale, t } from "../i18n";
import {
  dynamicCopySourceForNamespaces,
  translatePortalLiteral,
} from "../portalLiteralCatalog";

type AnyRecord = Record<string, any>;

const CONTEXT_PARAM = "field_observation_id";
const ACTIVE_OBSERVATION_PARAM = "observation_id";
const COPY_SOURCE = dynamicCopySourceForNamespaces(["fiOperatingLoop"]);
const sent = new Set<string>();
let localeReady: Promise<boolean> | null = null;
let translationQueued = false;

function contextualObservationId(): string {
  if (window.location.pathname !== "/intelligence") return "";
  return new URLSearchParams(window.location.search || "").get(CONTEXT_PARAM) || "";
}

async function ensureOperatingLoopLocale(): Promise<boolean> {
  const locale = getStoredLocale();
  const effective = normalizeLocale(locale);
  if (effective === "en" || !Object.keys(COPY_SOURCE).length) return true;
  if (!localeReady) {
    primeLocaleSourceCatalogFromCache(locale, COPY_SOURCE);
    localeReady = ensureLocaleSourceCatalog(locale, COPY_SOURCE)
      .catch(() => false)
      .finally(() => { localeReady = null; });
  }
  return localeReady;
}

function translateInjectedCopy(): void {
  const locale = getStoredLocale();
  const selectors = [
    "[data-fi-operating-loop-toast]",
    "[data-fi-operating-loop]",
    "[data-fi-linked-context]",
    "[data-fi-portal-loop]",
    "[data-fi-task-source]",
  ].join(",");
  document.querySelectorAll<HTMLElement>(selectors).forEach((root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const original = node.nodeValue || "";
      const translated = translatePortalLiteral(original, locale);
      if (translated !== original) node.nodeValue = translated;
      node = walker.nextNode();
    }
    root.querySelectorAll<HTMLElement>("[title],[aria-label]").forEach((element) => {
      for (const attribute of ["title", "aria-label"] as const) {
        const original = element.getAttribute(attribute) || "";
        const translated = translatePortalLiteral(original, locale);
        if (translated !== original) element.setAttribute(attribute, translated);
      }
    });
  });
}

function scheduleTranslation(): void {
  if (translationQueued) return;
  translationQueued = true;
  window.requestAnimationFrame(() => {
    translationQueued = false;
    void ensureOperatingLoopLocale().finally(translateInjectedCopy);
  });
}

function setControlledTextarea(textarea: HTMLTextAreaElement, value: string): void {
  const descriptor = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
  descriptor?.set?.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.dispatchEvent(new Event("change", { bubbles: true }));
}

function isImportButton(button: HTMLButtonElement): boolean {
  const label = `${button.innerText || ""} ${button.title || ""}`.replace(/\s+/g, " ").trim().toLocaleLowerCase();
  const translated = String(t("intelligence.importFiles") || "").toLocaleLowerCase();
  return label.includes("import") || label.includes("upload") || (translated && label.includes(translated));
}

function linkedObservationEvidence(observation: AnyRecord): AnyRecord {
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

async function enrichLegacyIntelligencePayload(payload: AnyRecord): Promise<AnyRecord> {
  const observationId = contextualObservationId();
  if (!observationId || payload?.field_observation_id === observationId) return payload;
  const response = await (apiClient as any).fieldIntelligence.observation(observationId);
  const observation = response?.observation || response;
  if (!observation?.id) return payload;
  const existing = Array.isArray(payload?.uploaded_evidence) ? payload.uploaded_evidence : [];
  return {
    ...(payload || {}),
    field_id: payload?.field_id || observation.field_id,
    field_observation_id: observationId,
    uploaded_evidence: [
      linkedObservationEvidence(observation),
      ...existing.filter((item: AnyRecord) => String(item?.observation_id || "") !== observationId),
    ],
  };
}

function installLegacyIntelligenceContext(): void {
  const intelligence = (apiClient as any).intelligence;
  for (const methodName of ["brainRun", "run"] as const) {
    const original = intelligence?.[methodName];
    if (typeof original !== "function" || original.__agroAiObservationContext) continue;
    const wrapped = async (payload: AnyRecord) => original(await enrichLegacyIntelligencePayload(payload));
    wrapped.__agroAiObservationContext = true;
    intelligence[methodName] = wrapped;
  }
}

// The core runtime prepares the contextual prompt before attempting to send it.
// Its fallback selector must never be allowed to treat an import control as the
// send action. Programmatic clicks are untrusted; real customer clicks remain
// untouched.
document.addEventListener("click", (event) => {
  if (event.isTrusted || !contextualObservationId()) return;
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest<HTMLButtonElement>("button");
  if (button && button.closest("footer") && isImportButton(button)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

async function sendPreparedContext(): Promise<void> {
  const observationId = contextualObservationId();
  if (!observationId || sent.has(observationId)) return;

  for (let attempt = 0; attempt < 60; attempt += 1) {
    const textarea = document.querySelector<HTMLTextAreaElement>("footer textarea");
    const sendButton = Array.from(document.querySelectorAll<HTMLButtonElement>("footer button"))
      .find((button) => {
        const label = `${button.title || ""} ${button.getAttribute("aria-label") || ""}`.trim().toLocaleLowerCase();
        const translated = String(t("send") || "").toLocaleLowerCase();
        return !button.disabled && (label === translated || label === "send" || label.includes("send"));
      });

    if (textarea?.value.trim() && sendButton) {
      await ensureOperatingLoopLocale();
      const translatedPrompt = translatePortalLiteral(textarea.value, getStoredLocale());
      if (translatedPrompt !== textarea.value) setControlledTextarea(textarea, translatedPrompt);
      sent.add(observationId);
      sendButton.click();
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
}

installLegacyIntelligenceContext();

// Fresh-tab routes can finish their initial React requests before this
// post-render enhancement is installed. These read-only calls warm the already-
// wrapped runtime caches; they never create observations, tasks, or messages.
if (window.location.pathname === "/field-intelligence") {
  const observationId = new URLSearchParams(window.location.search || "").get(ACTIVE_OBSERVATION_PARAM) || "";
  if (observationId) {
    void (apiClient as any).fieldIntelligence.observation(observationId).catch(() => undefined);
  }
  void (apiClient as any).fieldIntelligence.observations("limit=100").catch(() => undefined);
}
if (["/", "/field-queue", "/tasks"].includes(window.location.pathname)) {
  void (apiClient as any).fieldOps.tasks().catch(() => undefined);
}

const observer = new MutationObserver(() => {
  scheduleTranslation();
  void sendPreparedContext();
});
observer.observe(document.documentElement, { childList: true, subtree: true });
window.addEventListener("agroai:locale-change", () => {
  localeReady = null;
  scheduleTranslation();
});

scheduleTranslation();
void sendPreparedContext();
