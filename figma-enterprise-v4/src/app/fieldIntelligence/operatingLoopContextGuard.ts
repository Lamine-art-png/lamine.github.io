import { t } from "../i18n";

const CONTEXT_PARAM = "field_observation_id";
const sent = new Set<string>();

function contextualObservationId(): string {
  if (window.location.pathname !== "/intelligence") return "";
  return new URLSearchParams(window.location.search || "").get(CONTEXT_PARAM) || "";
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
      sent.add(observationId);
      sendButton.click();
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
}

const observer = new MutationObserver(() => { void sendPreparedContext(); });
observer.observe(document.documentElement, { childList: true, subtree: true });
void sendPreparedContext();
