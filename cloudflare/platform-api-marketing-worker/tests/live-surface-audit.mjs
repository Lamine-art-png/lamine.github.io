import assert from "node:assert/strict";

const ORIGIN = process.env.PLATFORM_MARKETING_ORIGIN || "https://agroai-pilot.com";
const PLATFORM = process.env.PLATFORM_CONSOLE_ORIGIN || "https://platform.agroai-pilot.com";
const API = process.env.PLATFORM_API_ORIGIN || "https://api.agroai-pilot.com";
const expectedRelease = String(process.env.EXPECTED_RELEASE_SHA || "").trim();

const pages = [
  ["/platform-api", "marketing", "<title>AGRO-AI Platform API</title>"],
  ["/platform-api/", "marketing", "<title>AGRO-AI Platform API</title>"],
  ["/platform-api/reference", "docs", "<title>API reference"],
  ["/platform-api/reference.html", "docs", "<title>API reference"],
  ["/platform-api/changelog", "docs", "<title>Changelog"],
  ["/platform-api/changelog.html", "docs", "<title>Changelog"],
  ["/platform-api/docs", "docs", "<title>AGRO-AI Platform API Documentation</title>"],
  ["/platform-api/docs/", "docs", "<title>AGRO-AI Platform API Documentation</title>"],
  ["/platform-api/docs/authentication", "docs", "<title>Authentication"],
  ["/platform-api/docs/authentication.html", "docs", "<title>Authentication"],
  ["/platform-api/docs/pagination", "docs", "<title>Pagination"],
  ["/platform-api/docs/pagination.html", "docs", "<title>Pagination"],
  ["/platform-api/docs/errors", "docs", "<title>Errors"],
  ["/platform-api/docs/errors.html", "docs", "<title>Errors"],
  ["/platform-api/docs/rate-limits", "docs", "<title>Rate limits"],
  ["/platform-api/docs/rate-limits.html", "docs", "<title>Rate limits"],
  ["/platform-api/docs/support", "docs", "<title>Support"],
  ["/platform-api/docs/support.html", "docs", "<title>Support"],
];

const genericErrorPage = /This page doesn[’']t exist|<title>\s*(?:404|Not found)\b|<h1[^>]*>\s*(?:404|Not found)\s*<\/h1>/i;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    return await fetch(url, { redirect: "follow", cache: "no-store", signal: controller.signal, ...options });
  } finally {
    clearTimeout(timeout);
  }
}

async function auditOnce() {
  const result = { pages: {}, assets: {}, platform: {}, backend: {}, safety: {} };

  for (const [path, surface, marker] of pages) {
    const response = await request(`${ORIGIN}${path}`);
    const body = await response.text();
    const contentType = response.headers.get("content-type") || "";
    const actualSurface = response.headers.get("x-agroai-platform-api-surface") || "";
    const cacheControl = response.headers.get("cache-control") || "";
    const robots = response.headers.get("x-robots-tag") || "";

    assert.equal(response.status, 200, `${path}: expected HTTP 200, got ${response.status}`);
    assert.match(contentType, /^text\/html\b/i, `${path}: expected HTML, got ${contentType}`);
    assert.equal(actualSurface, surface, `${path}: wrong surface header ${actualSurface}`);
    assert.match(cacheControl, /private|no-cache|must-revalidate/i, `${path}: unsafe cache policy ${cacheControl}`);
    assert.match(robots, /noindex/i, `${path}: private-beta robots gate missing`);
    assert.ok(body.includes(marker), `${path}: expected identity marker missing`);
    assert.ok(body.includes('/platform-api/assets/logo.svg'), `${path}: official logo reference missing`);
    assert.doesNotMatch(body, genericErrorPage, `${path}: generic error page leaked`);
    assert.doesNotMatch(body.trimStart(), /^[{[]/, `${path}: raw JSON body leaked`);
    result.pages[path] = { status: response.status, surface: actualSurface, contentType };
  }

  for (const asset of ["/platform-api/assets/logo.svg", "/platform-api/assets/platform.css", "/platform-api/assets/platform.js"]) {
    const response = await request(`${ORIGIN}${asset}`);
    const body = await response.arrayBuffer();
    assert.equal(response.status, 200, `${asset}: expected HTTP 200`);
    assert.ok(body.byteLength > 100, `${asset}: empty or truncated asset`);
    result.assets[asset] = { status: response.status, bytes: body.byteLength, contentType: response.headers.get("content-type") || "" };
  }

  const unknown = await request(`${ORIGIN}/platform-api/not-a-real-route`);
  assert.equal(unknown.status, 404, "unknown Platform route must fail closed with 404");
  assert.equal(unknown.headers.get("x-agroai-platform-api-surface"), "closed", "unknown route missing closed surface header");
  result.safety.unknownRoute = 404;

  const consoleResponse = await request(`${PLATFORM}/`);
  const consoleHtml = await consoleResponse.text();
  assert.equal(consoleResponse.status, 200, "standalone Platform console is not reachable");
  assert.match(consoleHtml, /<title>[^<]*AGRO-AI/i, "standalone Platform console identity missing");
  result.platform.console = 200;

  const edgeResponse = await request(`${PLATFORM}/v1/edge-health`);
  const edge = await edgeResponse.json();
  assert.equal(edgeResponse.status, 200, "Platform edge health failed");
  assert.equal(edge.status, "ok", "Platform edge is not ready");
  result.platform.edge = edge;

  const healthResponse = await request(`${PLATFORM}/v1/health`);
  const health = await healthResponse.json();
  assert.equal(healthResponse.status, 200, "Platform backend health failed");
  assert.equal(health.status, "ok", "Platform backend is not healthy");
  if (expectedRelease && health.build_sha) {
    assert.equal(health.build_sha, expectedRelease, `backend SHA mismatch: ${health.build_sha}`);
  }
  result.backend.health = health;

  const runtimeResponse = await request(`${API}/v1/platform/health`);
  const runtime = await runtimeResponse.json();
  assert.equal(runtimeResponse.status, 200, "Platform runtime health failed");
  assert.equal(runtime.status, "ready", "Platform runtime is not ready");
  assert.equal(runtime.platform_api_enabled, true, "Platform API is disabled");
  assert.equal(runtime.developer_control_plane_enabled, true, "developer control plane is disabled");
  assert.equal(runtime.rate_limiter?.ready, true, "rate limiter is not ready");
  assert.equal(runtime.rate_limiter?.backend, "redis", "rate limiter is not using Redis");
  assert.equal(runtime.production_vault_keyring_ready, true, "production vault is not ready");
  assert.equal(runtime.cidr_trusted_proxy_ready, true, "trusted proxy boundary is not ready");
  assert.equal(runtime.webhook_delivery?.enabled, false, "outbound webhooks were enabled unexpectedly");
  assert.equal(runtime.webhook_delivery?.ready, true, "webhook subsystem is not safely ready");
  assert.equal(runtime.physical_irrigation_commands, "disabled", "physical commands were enabled unexpectedly");
  result.backend.runtime = runtime;

  return result;
}

let lastError;
for (let attempt = 1; attempt <= 18; attempt += 1) {
  try {
    const result = await auditOnce();
    console.log(JSON.stringify({ ready: true, attempt, auditedAt: new Date().toISOString(), ...result }, null, 2));
    process.exit(0);
  } catch (error) {
    lastError = error;
    console.error(`Platform live audit attempt ${attempt}/18 failed:`, error instanceof Error ? error.message : error);
    if (attempt < 18) await sleep(10_000);
  }
}

throw lastError || new Error("Platform live audit failed");
