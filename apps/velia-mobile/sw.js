const CACHE_NAME = "velia-v3-module-offline";
const ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./manifest.webmanifest",
  "./js/app.js",
  "./js/data/demoData.js",
  "./js/state/store.js",
  "./js/state/actions.js",
  "./js/i18n/translations.js",
  "./js/services/apiClient.js",
  "./js/services/storage.js",
  "./js/services/uiHelpers.js",
  "./js/services/voiceAgent.js",
  "./js/services/weatherProviders/baseAdapter.js",
  "./js/services/weatherProviders/mockAdapter.js",
  "./js/services/weatherProviders/registry.js",
  "./js/services/sync.js",
  "./js/services/weatherService.js",
  "./js/services/recommendationEngine.js",
  "./js/ai/fieldReasoningAgent.js",
  "./js/ai/safetyGuardrails.js",
  "./js/ai/agentPlanner.js",
  "./js/ai/toolRegistry.js",
  "./js/ai/knowledgeBase.js",
  "./js/ai/embeddingService.js",
  "./js/ai/ragEngine.js",
  "./js/ai/translationAgent.js",
  "./js/ai/weatherRiskAgent.js",
  "./js/ai/aiOrchestrator.js",
  "./js/ai/evaluationHarness.js",
  "./js/ai/verificationAgent.js",
  "./js/ai/irrigationDecisionAgent.js",
  "./js/ai/modelRouter.js",
  "./js/ai/vectorStore.js",
  "./js/ai/memoryStore.js",
  "./js/ai/multimodalProcessor.js",
];

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
  const isModule = url.origin === self.location.origin && url.pathname.includes("/js/") && url.pathname.endsWith(".js");
  if (isAppAsset) {
    event.respondWith(fetch(event.request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
      return response;
    }).catch(() => caches.match(event.request)));
    return;
  }
  if (isModule) {
    event.respondWith(fetch(event.request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
      return response;
    }).catch(() => caches.match(event.request)));
    return;
  }
  event.respondWith(caches.match(event.request).then((hit) => hit || fetch(event.request)));
});
