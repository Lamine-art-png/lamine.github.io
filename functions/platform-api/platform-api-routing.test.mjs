import assert from "node:assert/strict";
import { onRequest } from "./[[path]].ts";

async function invoke(pathname, flags = {}, options = {}) {
  const fetched = [];
  const response = await onRequest({
    request: new Request(`https://agroai-pilot.com${pathname}`, {
      method: "GET",
      headers: { "user-agent": "platform-route-contract" },
    }),
    env: {
      PLATFORM_API_MARKETING_ENABLED: flags.marketing ? "true" : "false",
      PLATFORM_API_PUBLIC_DOCS_ENABLED: flags.docs ? "true" : "false",
      ASSETS: {
        async fetch(request) {
          const url = new URL(request.url);
          fetched.push(url.pathname);
          if (options.assetFailure) return new Response("missing", { status: 404 });
          return new Response(url.pathname.endsWith(".html") ? "<html></html>" : "asset", {
            status: 200,
            headers: { "content-type": url.pathname.endsWith(".html") ? "text/html" : "text/plain" },
          });
        },
      },
    },
  });
  return { response, fetched };
}

for (const pathname of [
  "/platform-api",
  "/platform-api/docs/",
  "/platform-api/assets/platform.css",
  "/platform-api/contract/platform_api_openapi.json",
]) {
  const { response, fetched } = await invoke(pathname);
  assert.equal(response.status, 404, `${pathname} must fail closed when both flags are disabled`);
  assert.deepEqual(fetched, [], "disabled routes must not touch static storage");
}

{
  const marketing = await invoke("/platform-api", { marketing: true });
  assert.equal(marketing.response.status, 200);
  assert.deepEqual(marketing.fetched, ["/platform-api/index.html"]);
  assert.equal(marketing.response.headers.get("x-robots-tag"), "noindex, nofollow");
  assert.equal(marketing.response.headers.get("x-frame-options"), "DENY");

  const shared = await invoke("/platform-api/assets/platform.css", { marketing: true });
  assert.equal(shared.response.status, 200, "marketing must retain its shared CSS/JS/logo assets while docs stay private");
  assert.deepEqual(shared.fetched, ["/platform-api/assets/platform.css"]);
  assert.match(shared.response.headers.get("cache-control") || "", /^public,/);

  assert.equal((await invoke("/platform-api/docs/", { marketing: true })).response.status, 404);
  assert.equal((await invoke("/platform-api/contract/platform_api_openapi.json", { marketing: true })).response.status, 404);
}

{
  assert.equal((await invoke("/platform-api", { docs: true })).response.status, 404);
  const docs = await invoke("/platform-api/docs/authentication", { docs: true });
  assert.equal(docs.response.status, 200);
  assert.deepEqual(docs.fetched, ["/platform-api/docs/authentication.html"]);
  assert.equal(docs.response.headers.get("x-robots-tag"), "noindex, nofollow");

  assert.equal((await invoke("/platform-api/assets/reference.js", { docs: true })).response.status, 200);
  assert.equal((await invoke("/platform-api/contract/platform_api_openapi.json", { docs: true })).response.status, 200);
}

for (const pathname of [
  "/platform-api/private",
  "/platform-api/assets/../index.html",
  "/platform-api/assets/%2e%2e/index.html",
  "/platform-api/contract/private.json",
]) {
  const { response, fetched } = await invoke(pathname, { marketing: true, docs: true });
  assert.equal(response.status, 404, `${pathname} must never resolve to a static asset`);
  assert.deepEqual(fetched, []);
}

{
  const { response, fetched } = await invoke("/platform-api", { marketing: true }, { assetFailure: true });
  assert.deepEqual(fetched, ["/platform-api/index.html"]);
  assert.equal(response.status, 404, "missing static assets must not leak the upstream error surface");
  assert.equal(response.headers.get("cache-control"), "no-store");
}

console.log("Platform API Pages flag matrix passed: marketing, docs, shared assets, contracts, traversal rejection, and fail-closed storage errors.");
