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

const CONTEXT_PARAM = "field_observation_id";
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

// A fresh-tab direct load can finish the page's initial observations request
// before this post-render enhancement is installed. Calling the already-wrapped
// client once warms the runtime cache without duplicating captures or writes.
if (window.location.pathname === "/field-intelligence") {
  void (apiClient as any).fieldIntelligence.observations("limit=100")
    .catch(() => undefined);
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
