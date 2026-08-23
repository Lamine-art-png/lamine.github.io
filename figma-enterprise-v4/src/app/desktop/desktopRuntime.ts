type DesktopRuntimeInfo = {
  product: string;
  channel: string;
  version: string;
  platform: string;
};

type Invoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
type NativeFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

type TauriGlobal = {
  core?: {
    invoke?: Invoke;
  };
  http?: {
    fetch?: NativeFetch;
  };
};

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
  }
}

const deepLinkEvent = "agroai:desktop-deep-link";
const desktopReadyEvent = "agroai:desktop-ready";
const desktopRouteEvent = "agroai:desktop-route-requested";
const browserFetch = window.fetch.bind(window);

function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const desktopInvoke = window.__TAURI__?.core?.invoke;
  if (!desktopInvoke) return Promise.reject(new Error("desktop_runtime_unavailable"));
  return desktopInvoke<T>(command, args);
}

export function isDesktopRuntime(): boolean {
  return Boolean(window.__TAURI__?.core?.invoke);
}

function normalizeDeepLink(raw: unknown): string | null {
  if (typeof raw !== "string" || raw.length > 4096) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "agroai:") return null;
    return parsed.toString();
  } catch {
    return null;
  }
}

function inputUrl(input: RequestInfo | URL): string | null {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== "undefined" && input instanceof Request) return input.url;
  return null;
}

function isAgroAiApiRequest(input: RequestInfo | URL): boolean {
  const raw = inputUrl(input);
  if (!raw) return false;
  try {
    const url = new URL(raw, window.location.href);
    return url.protocol === "https:" && url.hostname === "api.agroai-pilot.com";
  } catch {
    return false;
  }
}

function installNativeHttpTransport(): void {
  const nativeFetch = window.__TAURI__?.http?.fetch;
  if (!nativeFetch) return;

  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (isAgroAiApiRequest(input)) return nativeFetch(input, init);
    return browserFetch(input, init);
  }) as typeof window.fetch;
}

export async function requestDesktopOpenExternal(url: string): Promise<void> {
  if (!isDesktopRuntime()) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  await invoke<void>("desktop_open_external", { url });
}

export function installDesktopRuntime(): void {
  if (!isDesktopRuntime()) return;

  document.documentElement.dataset.agroaiDesktop = "true";
  installNativeHttpTransport();

  window.addEventListener(deepLinkEvent, (event) => {
    const detail = event instanceof CustomEvent ? event.detail : undefined;
    const url = normalizeDeepLink(detail?.url);
    if (!url) return;
    window.dispatchEvent(new CustomEvent(desktopRouteEvent, { detail: { url } }));
  });

  void invoke<DesktopRuntimeInfo>("desktop_runtime_info")
    .then((info) => {
      document.documentElement.dataset.agroaiDesktopPlatform = info.platform;
      document.documentElement.dataset.agroaiDesktopVersion = info.version;
      window.dispatchEvent(new CustomEvent(desktopReadyEvent, { detail: info }));
    })
    .catch(() => {
      document.documentElement.dataset.agroaiDesktopPlatform = "unknown";
    });
}
