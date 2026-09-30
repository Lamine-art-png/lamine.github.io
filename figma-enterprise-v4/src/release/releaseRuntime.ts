/*
 * AGRO-AI portal release convergence.
 *
 * Invariant: a browser never keeps running an obsolete portal release
 * indefinitely, and converging never costs the customer their session,
 * language, workspace or unsaved work.
 *
 * - Identity: the build compiles in its release id (Git SHA, see
 *   vite.config.ts). The deployed release publishes the same id in the
 *   no-store /deployment.json. Releases are compared by equality, never by
 *   ordering, so a rollback converges exactly like a roll-forward.
 * - Detection: at boot (bounded, fail-open), when the tab becomes visible,
 *   on focus, when connectivity returns, when the page is restored from the
 *   back-forward cache, when a new service worker takes control, and every
 *   15 minutes while visible. Checks are throttled; offline means "no news".
 * - Convergence: a pending release is applied only at a safe point: a route
 *   navigation, the tab being hidden, the customer returning to the tab, or a
 *   long idle period. It is never applied while an input has unsaved text, a
 *   write request or upload is in flight, the microphone/camera is live, a
 *   single-use link is being redeemed, or code holds the release explicitly.
 *   Applying is a plain reload: storage (auth token, locale, workspace) is
 *   never cleared.
 * - Tabs: a tab that discovers a release tells the others (BroadcastChannel,
 *   with a storage-event fallback); each tab converges at its own safe point.
 * - Loops: at most two immediate automatic reloads per target release (e.g.
 *   while a CDN edge still serves the previous shell); further attempts back
 *   off exponentially (2, 4, 8… minutes) and reload_loop_prevented is
 *   reported, so the tab keeps working and still converges once propagation
 *   completes.
 */

declare const __AGROAI_BUILD_ID__: string;

export const RUNNING_BUILD: string =
  typeof __AGROAI_BUILD_ID__ === "string" && __AGROAI_BUILD_ID__ ? __AGROAI_BUILD_ID__ : "unversioned";

const DEPLOYMENT_URL = "/deployment.json";
const EVENTS_URL = "/v1/client/release-events";
const CHECK_TIMEOUT_MS = 4000;
const BOOT_CHECK_BUDGET_MS = 2500;
const MIN_CHECK_INTERVAL_MS = 60_000;
const PERIODIC_CHECK_MS = 15 * 60_000;
const IDLE_APPLY_MS = 10 * 60_000;
const GUARD_BACKOFF_MS = 2 * 60_000;
const GUARD_FORGET_MS = 60 * 60_000;
const MAX_ATTEMPTS_PER_TARGET = 2;
const GUARD_KEY = "agroai_release_convergence_v1";
const PEER_KEY = "agroai_release_latest_v1";
const CHANNEL = "agroai-release";
const RETURN_FORCES_CHECK_AFTER_MS = 15_000;
// Browser tests may shorten the check throttle by defining this before load;
// production never defines it.
const testOverrides = (typeof window !== "undefined"
  ? (window as typeof window & { __AGROAI_RELEASE_TEST__?: { minCheckIntervalMs?: number; guardBackoffMs?: number } }).__AGROAI_RELEASE_TEST__
  : undefined) || {};
const minCheckInterval = typeof testOverrides.minCheckIntervalMs === "number" && testOverrides.minCheckIntervalMs >= 0
  ? testOverrides.minCheckIntervalMs
  : MIN_CHECK_INTERVAL_MS;
const guardBackoff = typeof testOverrides.guardBackoffMs === "number" && testOverrides.guardBackoffMs >= 0
  ? testOverrides.guardBackoffMs
  : GUARD_BACKOFF_MS;
const SINGLE_USE_LINK_PATHS = new Set(["/verify-email", "/accept-invite", "/recover-account", "/reset-password"]);

type Latest = { build: string; entry: string | null };
type Guard = { target: string; count: number; last: number };

let installed = false;
let pending: { target: string; reason: string } | null = null;
let latestKnown: string | null = null;
let lastCheck = 0;
let checking: Promise<void> | null = null;
let lastInteraction = Date.now();
let dirtySinceNavigation = false;
let inflightWrites = 0;
let applying = false;
let loopReported = false;
let deferReported = false;
const liveTracks = new Set<MediaStreamTrack>();
const holds = new Set<symbol>();
let channel: BroadcastChannel | null = null;
const reported = new Set<string>();

function storageGet(storage: "local" | "session", key: string): string | null {
  try {
    return (storage === "local" ? window.localStorage : window.sessionStorage).getItem(key);
  } catch {
    return null; // Safari private / restricted storage is non-fatal.
  }
}

function storageSet(storage: "local" | "session", key: string, value: string | null) {
  try {
    const target = storage === "local" ? window.localStorage : window.sessionStorage;
    if (value === null) target.removeItem(key);
    else target.setItem(key, value);
  } catch {
    // Restricted storage: convergence still works, only loop memory is lost.
  }
}

export function currentEntryPath(): string {
  const src = document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src || "";
  try {
    return src ? new URL(src, window.location.origin).pathname : "";
  } catch {
    return "";
  }
}

function routeFamily(): string {
  const segment = window.location.pathname.split("/")[1] || "";
  return /^[a-z][a-z-]{0,39}$/.test(segment) ? `/${segment}` : segment ? "/other" : "/";
}

/** Privacy-safe diagnostics: build ids, event, route family. Never tokens, form data or identifiers. */
export function reportReleaseEvent(event: string, detail: Record<string, string | number | boolean | null> = {}) {
  const dedupe = `${event}:${latestKnown || ""}:${detail.trigger || detail.reason || ""}`;
  if (reported.has(dedupe)) return;
  reported.add(dedupe);
  const body = JSON.stringify({
    event,
    running_build: RUNNING_BUILD,
    latest_build: latestKnown,
    route: routeFamily(),
    visibility: document.visibilityState,
    ...detail,
  });
  try {
    const blob = new Blob([body], { type: "application/json" });
    if (!navigator.sendBeacon?.(EVENTS_URL, blob)) {
      void originalFetch(EVENTS_URL, { method: "POST", body, keepalive: true, headers: { "Content-Type": "application/json" } }).catch(() => undefined);
    }
  } catch {
    // Diagnostics must never affect the portal.
  }
}

let originalFetch: typeof window.fetch = (...args) => window.fetch(...args);

async function fetchNoStore(url: string): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), CHECK_TIMEOUT_MS);
  try {
    return await originalFetch(url, { cache: "no-store", credentials: "same-origin", signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

function entryFromHtml(html: string): { entry: string | null; build: string | null } {
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const src = doc.querySelector<HTMLScriptElement>('script[type="module"][src]')?.getAttribute("src") || "";
    const build = doc.querySelector<HTMLMetaElement>('meta[name="agroai-build"]')?.content || null;
    return { entry: src ? new URL(src, window.location.origin).pathname : null, build };
  } catch {
    return { entry: null, build: null };
  }
}

/** The release production currently serves, or null when it cannot be determined (fail open). */
async function latestProductionRelease(): Promise<Latest | null> {
  try {
    const response = await fetchNoStore(`${DEPLOYMENT_URL}?t=${Date.now()}`);
    if (response.ok && /json/i.test(response.headers.get("content-type") || "")) {
      const data = await response.json() as { build_sha?: unknown; entry?: unknown };
      if (typeof data.build_sha === "string" && /^[A-Za-z0-9._-]{1,80}$/.test(data.build_sha)) {
        return { build: data.build_sha, entry: typeof data.entry === "string" ? data.entry : null };
      }
    }
  } catch {
    // Fall through to the shell probe (e.g. rollback to a release without metadata).
  }
  try {
    const response = await fetchNoStore(`/?agroai_freshness_probe=${Date.now()}`);
    if (!response.ok) return null;
    const { entry, build } = entryFromHtml(await response.text());
    if (!entry) return null;
    return { build: build || `entry:${entry}`, entry };
  } catch {
    return null;
  }
}

function isCurrent(latest: Latest): boolean {
  if (latest.build === RUNNING_BUILD && RUNNING_BUILD !== "unversioned") return true;
  const running = currentEntryPath();
  return Boolean(latest.entry && running && latest.entry === running);
}

function readGuard(): Guard | null {
  try {
    const value = JSON.parse(storageGet("local", GUARD_KEY) || "null") as Guard | null;
    return value && typeof value.target === "string" ? value : null;
  } catch {
    return null;
  }
}

function isEditable(element: Element | null): boolean {
  if (!element || element.closest("[data-release-ignore], [data-language-selector]")) return false;
  if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) return true;
  if (element instanceof HTMLInputElement) return !["button", "submit", "reset", "checkbox", "radio", "range", "color"].includes(element.type);
  return (element as HTMLElement).isContentEditable === true;
}

function hasContent(element: Element | null): boolean {
  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) return element.value.trim().length > 0;
  if (element instanceof HTMLSelectElement) return false;
  return Boolean((element as HTMLElement | null)?.textContent?.trim());
}

/** Why converging right now could cost the customer something, or null when it is safe. */
export function unsafeReason(atNavigation = false): string | null {
  if (holds.size) return "held";
  if (SINGLE_USE_LINK_PATHS.has(window.location.pathname)) return "single_use_link";
  if (inflightWrites > 0) return "write_in_flight";
  for (const track of liveTracks) {
    if (track.readyState === "live") return "media_capture";
    liveTracks.delete(track);
  }
  if (!atNavigation) {
    if (dirtySinceNavigation) return "unsaved_input";
    // A focused field only blocks when it holds content: an autofocused
    // empty field must not pin a tab to an obsolete release forever.
    if (isEditable(document.activeElement) && hasContent(document.activeElement)) return "editing";
  }
  return null;
}

/** Keep the current release while an irreversible operation runs. Call the returned function to release. */
export function holdRelease(): () => void {
  const token = Symbol("release-hold");
  holds.add(token);
  return () => {
    holds.delete(token);
    applyPending("hold_released");
  };
}

function reload(trigger: string) {
  if (applying || !pending) return;
  const guard = readGuard();
  const now = Date.now();
  const sameTarget = Boolean(guard && guard.target === pending.target && now - guard.last < GUARD_FORGET_MS);
  const count = sameTarget && guard ? guard.count : 0;
  if (count >= MAX_ATTEMPTS_PER_TARGET) {
    const wait = guardBackoff * 2 ** (count - MAX_ATTEMPTS_PER_TARGET);
    if (guard && now - guard.last < wait) {
      if (!loopReported) {
        loopReported = true;
        reportReleaseEvent("reload_loop_prevented", { trigger });
      }
      return;
    }
  }
  storageSet("local", GUARD_KEY, JSON.stringify({ target: pending.target, count: count + 1, last: now }));
  applying = true;
  reportReleaseEvent("recovery_attempted", { trigger });
  const go = () => window.location.reload();
  const registration = navigator.serviceWorker?.getRegistration?.();
  if (!registration) return go();
  // Give the new service worker a moment to install; never block on it.
  Promise.race([
    registration.then((value) => value?.update()).catch(() => undefined),
    new Promise((resolve) => window.setTimeout(resolve, 1500)),
  ]).finally(go);
}

export function applyPending(trigger: string): boolean {
  if (!pending || applying) return false;
  const reason = unsafeReason(trigger === "navigation");
  if (reason) {
    if (!deferReported) {
      deferReported = true;
      reportReleaseEvent("recovery_deferred", { trigger, reason });
    }
    return false;
  }
  if (trigger === "detected" || trigger === "idle") {
    // Never reload a visible page the customer is actively using; wait for a
    // navigation, the tab being hidden, their return to it, or a long idle.
    const idle = Date.now() - lastInteraction >= IDLE_APPLY_MS;
    if (document.visibilityState === "visible" && !idle) return false;
  }
  reload(trigger);
  return true;
}

function markPending(target: string, reason: string, announce: boolean) {
  if (!target || target === RUNNING_BUILD) return;
  if (pending?.target === target) return;
  pending = { target, reason };
  latestKnown = target;
  deferReported = false;
  reportReleaseEvent("stale_build_detected", { reason });
  if (announce) {
    try {
      channel?.postMessage({ type: "agroai-release-available", target });
    } catch {
      // ignore
    }
    storageSet("local", PEER_KEY, JSON.stringify({ target, at: Date.now() }));
  }
  applyPending("detected");
}

export function checkForRelease(reason: string, force = false): Promise<void> {
  if (checking) return checking;
  const now = Date.now();
  if (!force && now - lastCheck < minCheckInterval) return Promise.resolve();
  if (navigator.onLine === false) return Promise.resolve();
  lastCheck = now;
  checking = (async () => {
    const latest = await latestProductionRelease();
    if (!latest) return;
    latestKnown = latest.build;
    if (isCurrent(latest)) {
      pending = null; // e.g. a rollback back to the release this tab runs.
      return;
    }
    markPending(latest.build, reason, true);
  })().catch(() => undefined).finally(() => {
    checking = null;
  });
  return checking;
}

/** Bounded boot check. Resolves false when the page is being replaced by the current release. */
export async function bootReleaseCheck(): Promise<boolean> {
  if (import.meta.env.DEV) return true;
  const guard = readGuard();
  if (guard && (guard.target === RUNNING_BUILD)) {
    reportReleaseEvent("recovery_succeeded", { attempts: guard.count });
    storageSet("local", GUARD_KEY, null);
  }
  const outcome = await Promise.race([
    checkForRelease("boot", true).then(() => "checked"),
    new Promise<string>((resolve) => window.setTimeout(() => resolve("timeout"), BOOT_CHECK_BUDGET_MS)),
  ]);
  if (outcome !== "checked" || !pending) return true;
  // Nothing has rendered yet, so no customer state can be lost.
  if (unsafeReason(true)) return true;
  reload("boot");
  return !applying;
}

/**
 * A lazy route or chunk failed to load. After a release its hashed file may be
 * retired; load the current release instead of showing a broken module.
 * Returns true when a reload has been started.
 */
export function recoverFromAssetFailure(error: unknown, source: string): boolean {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error || "");
  reportReleaseEvent(source === "dynamic_import" ? "dynamic_import_failure" : "asset_load_failure", { reason: message.slice(0, 120) });
  if (!pending) pending = { target: latestKnown && latestKnown !== RUNNING_BUILD ? latestKnown : `asset-failure:${currentEntryPath()}`, reason: source };
  if (unsafeReason(true)) return false;
  reload(source);
  return applying;
}

function trackActivity() {
  const touch = () => {
    lastInteraction = Date.now();
  };
  for (const type of ["pointerdown", "keydown", "wheel", "touchstart"]) {
    window.addEventListener(type, touch, { capture: true, passive: true });
  }
  document.addEventListener("input", (event) => {
    if (isEditable(event.target as Element)) dirtySinceNavigation = true;
  }, true);

  const nativeFetch = window.fetch.bind(window);
  originalFetch = nativeFetch;
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const write = !["GET", "HEAD", "OPTIONS"].includes(method);
    const promise = nativeFetch(input, init);
    if (write) {
      inflightWrites += 1;
      const done = () => {
        inflightWrites = Math.max(0, inflightWrites - 1);
        if (pending) window.setTimeout(() => applyPending("write_settled"), 0);
      };
      promise.then(done, done);
    }
    return promise;
  };

  const xhrOpen = XMLHttpRequest.prototype.open;
  const xhrSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (this: XMLHttpRequest & { __agroaiMethod?: string }, method: string, ...rest: unknown[]) {
    this.__agroaiMethod = String(method || "GET").toUpperCase();
    return (xhrOpen as (...args: unknown[]) => void).call(this, method, ...rest);
  } as typeof XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.send = function (this: XMLHttpRequest & { __agroaiMethod?: string }, body?: Document | XMLHttpRequestBodyInit | null) {
    if (!["GET", "HEAD", "OPTIONS"].includes(this.__agroaiMethod || "GET")) {
      inflightWrites += 1;
      this.addEventListener("loadend", () => {
        inflightWrites = Math.max(0, inflightWrites - 1);
      }, { once: true });
    }
    return xhrSend.call(this, body);
  };

  const media = navigator.mediaDevices;
  if (media?.getUserMedia) {
    const getUserMedia = media.getUserMedia.bind(media);
    media.getUserMedia = async (constraints?: MediaStreamConstraints) => {
      const stream = await getUserMedia(constraints);
      for (const track of stream.getTracks()) {
        liveTracks.add(track);
        track.addEventListener("ended", () => liveTracks.delete(track), { once: true });
      }
      return stream;
    };
  }
}

function trackNavigation() {
  let lastPath = window.location.pathname;
  const onPathMaybeChanged = () => {
    if (window.location.pathname === lastPath) return;
    lastPath = window.location.pathname;
    dirtySinceNavigation = false; // the previous page's form was left
    applyPending("navigation");
  };
  for (const method of ["pushState", "replaceState"] as const) {
    const original = window.history[method].bind(window.history);
    window.history[method] = ((...args: Parameters<History["pushState"]>) => {
      original(...args);
      onPathMaybeChanged();
    }) as History["pushState"];
  }
  window.addEventListener("popstate", onPathMaybeChanged);
}

export function installReleaseRuntime() {
  if (installed || import.meta.env.DEV) return;
  installed = true;
  trackActivity();
  trackNavigation();

  try {
    channel = typeof BroadcastChannel === "function" ? new BroadcastChannel(CHANNEL) : null;
    channel?.addEventListener("message", (event: MessageEvent) => {
      if (event.data?.type === "agroai-release-available" && typeof event.data.target === "string") {
        markPending(event.data.target, "peer_tab", false);
      }
    });
  } catch {
    channel = null;
  }
  window.addEventListener("storage", (event) => {
    if (event.key !== PEER_KEY || !event.newValue) return;
    try {
      const value = JSON.parse(event.newValue) as { target?: string };
      if (typeof value.target === "string") markPending(value.target, "peer_tab", false);
    } catch {
      // ignore malformed peer data
    }
  });

  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      hiddenAt = Date.now();
      if (pending) window.setTimeout(() => document.visibilityState === "hidden" && applyPending("hidden"), 250 + Math.random() * 1500);
      return;
    }
    const awayLongEnough = hiddenAt > 0 && Date.now() - hiddenAt >= RETURN_FORCES_CHECK_AFTER_MS;
    void checkForRelease("visible", awayLongEnough).then(() => applyPending("visible"));
  });
  window.addEventListener("focus", () => void checkForRelease("focus"));
  window.addEventListener("online", () => void checkForRelease("online", true));
  window.addEventListener("pageshow", (event) => {
    if ((event as PageTransitionEvent).persisted) void checkForRelease("bfcache", true).then(() => applyPending("visible"));
  });
  const pruneWorkerCaches = () => {
    try {
      navigator.serviceWorker?.controller?.postMessage({ type: "AGROAI_PRUNE_CACHES" });
    } catch {
      // ignore
    }
  };
  navigator.serviceWorker?.addEventListener?.("controllerchange", () => {
    reportReleaseEvent("service_worker_updated");
    window.setTimeout(pruneWorkerCaches, 3000);
    void checkForRelease("service_worker", true);
  });
  window.setTimeout(pruneWorkerCaches, 5000);
  window.setInterval(() => {
    if (document.visibilityState !== "visible") return;
    void checkForRelease("interval").then(() => applyPending("idle"));
  }, PERIODIC_CHECK_MS);

  (window as typeof window & { __agroaiRelease?: unknown }).__agroaiRelease = {
    running: RUNNING_BUILD,
    latest: () => latestKnown,
    pending: () => pending?.target || null,
    unsafeReason: () => unsafeReason(),
    check: (reason = "diagnostic") => checkForRelease(reason, true),
  };
}
