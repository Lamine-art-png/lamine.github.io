/* AGRO-AI portal service worker — safe app-shell cache only.
 *
 * Policy (enforced by tests/field-intelligence-launch-contract.mjs):
 *  - only same-origin GET requests are ever considered;
 *  - NEVER cache or intercept API traffic: any /v1/ path (same-origin or the
 *    API host) always goes to the network untouched, so authenticated
 *    responses and signed media never enter Cache Storage;
 *  - static hashed build assets (/assets/*) are cache-first (immutable);
 *  - JavaScript requests are never allowed to receive an HTML fallback;
 *  - the navigation shell ("/", index.html, manifest, icons) is
 *    network-first with cache fallback so the capture UI cold-starts
 *    offline while updates still land when online;
 *  - versioned, environment-scoped cache cleanup prevents staging and
 *    production shells from deleting one another;
 *  - the cache is scoped to the release: the build replaces
 *    __AGROAI_BUILD_ID__ with the Git SHA, so every release is a byte-different
 *    worker that installs, activates immediately and prunes the previous
 *    release's cache (release identity is equality, never ordering, so a
 *    rollback converges exactly like a roll-forward);
 *  - SKIP_WAITING lets the app apply an update on user consent.
 */
const SW_ENV = new URL(self.location.href).searchParams.get("env") || "production";
const CACHE_FAMILY = `agroai-shell-${SW_ENV}-`;
const BUILD_ID = "__AGROAI_BUILD_ID__";
const CACHE_VERSION = `${CACHE_FAMILY}${BUILD_ID}`;
const SHELL_PATHS = ["/", "/index.html", "/manifest.webmanifest", "/pwa-icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      await caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL_PATHS)).catch(() => undefined);
      // Production updates must not remain behind an old waiting worker.
      // Activating immediately is safe because API traffic is never cached.
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      // Delete only stale versions from this deployment environment. Never
      // delete another AGRO-AI environment's cache or an unrelated app cache.
      await Promise.all(
        names
          .filter((name) => name.startsWith(CACHE_FAMILY) && name !== CACHE_VERSION)
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
  if (event.data && event.data.type === "AGROAI_GET_BUILD" && event.source) {
    event.source.postMessage({ type: "AGROAI_SW_BUILD", build: BUILD_ID });
  }
});

function isApiRequest(url) {
  return url.pathname.startsWith("/v1/") || url.pathname.startsWith("/api/");
}

function isStaticAsset(url) {
  return url.pathname.startsWith("/assets/") || url.pathname === "/pwa-icon.svg"
    || url.pathname === "/manifest.webmanifest";
}

function isJavaScriptRequest(request, url) {
  return request.destination === "script" || /\.(?:m?js)(?:$|\?)/i.test(url.pathname);
}

function isJavaScriptResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  return /(?:application|text)\/javascript|application\/ecmascript/i.test(contentType);
}

function invalidJavaScriptAsset(url) {
  return new Response(
    `throw new Error(${JSON.stringify(`AGRO-AI frontend asset unavailable: ${url.pathname}`)});`,
    {
      status: 502,
      headers: {
        "content-type": "application/javascript; charset=utf-8",
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
      },
    },
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (isApiRequest(url)) return;

  if (isStaticAsset(url)) {
    event.respondWith(
      caches.open(CACHE_VERSION).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;

        const response = await fetch(request, { cache: "no-store" });
        if (isJavaScriptRequest(request, url) && !isJavaScriptResponse(response)) {
          return invalidJavaScriptAsset(url);
        }
        if (response.ok) await cache.put(request, response.clone());
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
          const response = await fetch(request, { cache: "no-store" });
          // Only a real HTML shell may become the offline fallback.
          if (response.ok && /text\/html/i.test(response.headers.get("content-type") || "")) {
            await cache.put("/index.html", response.clone());
          }
          return response;
        } catch {
          return (await cache.match("/index.html")) || (await cache.match("/")) || Response.error();
        }
      })(),
    );
  }
});
