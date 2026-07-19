/* AGRO-AI portal service worker — safe app-shell cache only.
 *
 * Policy (enforced by tests/field-intelligence-launch-contract.mjs):
 *  - only same-origin GET requests are ever considered;
 *  - NEVER cache or intercept API traffic: any /v1/ path (same-origin or the
 *    API host) always goes to the network untouched, so authenticated
 *    responses and signed media never enter Cache Storage;
 *  - static hashed build assets (/assets/*) are cache-first (immutable);
 *  - the navigation shell ("/", index.html, manifest, icons) is
 *    network-first with cache fallback so the capture UI cold-starts
 *    offline while updates still land when online;
 *  - versioned cache name + activate-time cleanup prevents stale
 *    incompatible shells from surviving an upgrade;
 *  - SKIP_WAITING message lets the app apply an update on user consent.
 */
const CACHE_VERSION = "agroai-shell-v1";
const SHELL_PATHS = ["/", "/index.html", "/manifest.webmanifest", "/pwa-icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL_PATHS)).catch(() => undefined),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.filter((name) => name !== CACHE_VERSION).map((name) => caches.delete(name)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

function isApiRequest(url) {
  return url.pathname.startsWith("/v1/") || url.pathname.startsWith("/api/");
}

function isStaticAsset(url) {
  return url.pathname.startsWith("/assets/") || url.pathname === "/pwa-icon.svg"
    || url.pathname === "/manifest.webmanifest";
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; // never touch mutations
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // never touch cross-origin (API host, tiles)
  if (isApiRequest(url)) return; // authenticated API responses are never cached

  if (isStaticAsset(url)) {
    event.respondWith(
      caches.open(CACHE_VERSION).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      }),
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_VERSION);
        try {
          const response = await fetch(request);
          if (response.ok) cache.put("/index.html", response.clone());
          return response;
        } catch {
          return (await cache.match("/index.html")) || (await cache.match("/")) || Response.error();
        }
      })(),
    );
  }
});
