type DesktopRuntimeInfo = {
  product: string;
  channel: string;
  version: string;
  platform: string;
};

type Invoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
type NativeFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type Unlisten = () => void;

type TauriGlobal = {
  core?: {
    invoke?: Invoke;
  };
  http?: {
    fetch?: NativeFetch;
  };
  deepLink?: {
    getCurrent?: () => Promise<string[] | null>;
    onOpenUrl?: (handler: (urls: string[]) => void) => Promise<Unlisten>;
  };
};

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
  }
}

const tokenKey = "agroai_access_token";
const desktopReadyEvent = "agroai:desktop-ready";
const desktopRouteEvent = "agroai:desktop-route-requested";
const desktopCredentialEvent = "agroai:desktop-credential-state";
const browserFetch = window.fetch.bind(window);
const nativeStorageGetItem = Storage.prototype.getItem;
const nativeStorageSetItem = Storage.prototype.setItem;
const nativeStorageRemoveItem = Storage.prototype.removeItem;
let desktopAccessToken: string | null = null;
let credentialFacadeInstalled = false;

const desktopRouteAllowlist = new Set([
  "/",
  "/field-queue",
  "/field-intelligence",
  "/tasks",
  "/readiness",
  "/fields",
  "/exceptions",
  "/decision-workbench",
  "/report-factory",
  "/operations",
  "/operations/new",
  "/assurance",
  "/evidence",
  "/reports",
  "/agents",
  "/intelligence",
  "/integrations",
  "/sources",
  "/audit",
  "/profile",
  "/billing",
  "/security",
  "/support",
  "/settings",
  "/team",
]);

function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const desktopInvoke = window.__TAURI__?.core?.invoke;
  if (!desktopInvoke) return Promise.reject(new Error("desktop_runtime_unavailable"));
  return desktopInvoke<T>(command, args);
}

export function isDesktopRuntime(): boolean {
  return Boolean(window.__TAURI__?.core?.invoke);
}

function setCredentialState(state: "ready" | "empty" | "error"): void {
  document.documentElement.dataset.agroaiDesktopCredentialState = state;
  window.dispatchEvent(new CustomEvent(desktopCredentialEvent, { detail: { state } }));
}

function persistDesktopToken(token: string): void {
  desktopAccessToken = token;
  void invoke<void>("desktop_set_access_token", { token })
    .then(() => setCredentialState("ready"))
    .catch(() => setCredentialState("error"));
}

function deleteDesktopToken(): void {
  desktopAccessToken = null;
  void invoke<void>("desktop_delete_access_token")
    .then(() => setCredentialState("empty"))
    .catch(() => setCredentialState("error"));
}

function installCredentialFacade(): void {
  if (credentialFacadeInstalled) return;
  credentialFacadeInstalled = true;

  Storage.prototype.getItem = function getItem(key: string): string | null {
    if (this === window.localStorage && key === tokenKey && isDesktopRuntime()) {
      return desktopAccessToken;
    }
    return nativeStorageGetItem.call(this, key);
  };

  Storage.prototype.setItem = function setItem(key: string, value: string): void {
    if (this === window.localStorage && key === tokenKey && isDesktopRuntime()) {
      persistDesktopToken(String(value));
      return;
    }
    nativeStorageSetItem.call(this, key, value);
  };

  Storage.prototype.removeItem = function removeItem(key: string): void {
    if (this === window.localStorage && key === tokenKey && isDesktopRuntime()) {
      deleteDesktopToken();
      return;
    }
    nativeStorageRemoveItem.call(this, key);
  };
}

async function hydrateDesktopCredential(): Promise<void> {
  try {
    desktopAccessToken = await invoke<string | null>("desktop_get_access_token");
    setCredentialState(desktopAccessToken ? "ready" : "empty");
  } catch {
    desktopAccessToken = null;
    setCredentialState("error");
  }
}

function normalizeDesktopRoute(raw: unknown): string | null {
  if (typeof raw !== "string" || raw.length > 4096) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "agroai:" || parsed.hostname !== "open") return null;
    const path = parsed.pathname || "/";
    if (!desktopRouteAllowlist.has(path)) return null;
    return `${path}${parsed.search}`;
  } catch {
    return null;
  }
}

function dispatchDesktopRoute(raw: unknown): void {
  const route = normalizeDesktopRoute(raw);
  if (!route) return;
  window.dispatchEvent(new CustomEvent(desktopRouteEvent, { detail: { route } }));
  if (`${window.location.pathname}${window.location.search}` === route) return;
  window.history.pushState({}, "", route);
  window.dispatchEvent(new PopStateEvent("popstate"));
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

function installDeepLinks(): void {
  const deepLink = window.__TAURI__?.deepLink;
  if (!deepLink) return;

  void deepLink.getCurrent?.()
    .then((urls) => urls?.forEach(dispatchDesktopRoute))
    .catch(() => undefined);

  void deepLink.onOpenUrl?.((urls) => {
    urls.forEach(dispatchDesktopRoute);
  }).catch(() => undefined);
}

export async function requestDesktopOpenExternal(url: string): Promise<void> {
  if (!isDesktopRuntime()) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  await invoke<void>("desktop_open_external", { url });
}

export async function installDesktopRuntime(): Promise<void> {
  if (!isDesktopRuntime()) return;

  document.documentElement.dataset.agroaiDesktop = "true";
  installCredentialFacade();
  installNativeHttpTransport();
  installDeepLinks();

  const runtimeInfo = invoke<DesktopRuntimeInfo>("desktop_runtime_info")
    .then((info) => {
      document.documentElement.dataset.agroaiDesktopPlatform = info.platform;
      document.documentElement.dataset.agroaiDesktopVersion = info.version;
      window.dispatchEvent(new CustomEvent(desktopReadyEvent, { detail: info }));
    })
    .catch(() => {
      document.documentElement.dataset.agroaiDesktopPlatform = "unknown";
    });

  await Promise.all([hydrateDesktopCredential(), runtimeInfo]);
}
