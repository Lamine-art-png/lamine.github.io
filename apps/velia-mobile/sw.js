const CACHE_NAME = "velia-v2-stabilized";
const ASSETS = ["./","./index.html","./styles.css","./js/app.js","./manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isAppAsset = event.request.mode === "navigate" || url.pathname.endsWith("index.html") || url.pathname.endsWith("styles.css") || url.pathname.endsWith("app.js");
  if (isAppAsset) {
    event.respondWith(fetch(event.request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
      return response;
    }).catch(() => caches.match(event.request)));
    return;
  }
  event.respondWith(caches.match(event.request).then((hit) => hit || fetch(event.request)));
});
