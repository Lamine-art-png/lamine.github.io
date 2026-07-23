import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
const config = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
const landing = readFileSync(new URL("../../../platform-api/index.html", import.meta.url), "utf8");
const docs = readFileSync(new URL("../../../platform-api/docs/index.html", import.meta.url), "utf8");
const portalRoutes = readFileSync(new URL("../../../figma-enterprise-v4/src/app/routes.tsx", import.meta.url), "utf8");
const portalShell = readFileSync(new URL("../../../figma-enterprise-v4/src/app/components/MainLayout.tsx", import.meta.url), "utf8");
const consoleSource = readFileSync(new URL("../../../figma-enterprise-v4/src/app/components/PlatformConsole.tsx", import.meta.url), "utf8");

assert.match(config, /name = "agroai-platform-api-marketing"/);
assert.match(config, /pattern = "agroai-pilot\.com\/"/);
assert.match(config, /pattern = "agroai-pilot\.com\/platform-api"/);
assert.match(config, /pattern = "agroai-pilot\.com\/platform-api\/\*"/);
assert.match(config, /\[assets\]/);
assert.match(config, /directory = "\.\.\/\.\.\/platform-api"/);
assert.match(config, /binding = "ASSETS"/);
assert.match(config, /run_worker_first = true/);
assert.match(config, /PLATFORM_API_MARKETING_ENABLED = "true"/);
assert.match(config, /PLATFORM_API_PUBLIC_DOCS_ENABLED = "true"/);
assert.match(config, /PLATFORM_API_INDEXING_ENABLED = "false"/);
assert.match(config, /MARKETING_ORIGIN = "https:\/\/agroai-343\.pages\.dev"/);

for (const required of [
  "ASSETS: Fetcher",
  "env.ASSETS.fetch",
  'new URL(route.assetPath, request.url)',
  '"x-robots-tag": "noindex, nofollow"',
  'headers.set("x-robots-tag", "noindex, nofollow")',
  'headers.set("cache-control", "private, no-cache, must-revalidate")',
  'headers.set("x-agroai-platform-api-surface", route.surface)',
  'const PLATFORM_CONSOLE = "https://platform.agroai-pilot.com"',
  "if (!route) return notFound()",
  "if (!surfaceEnabled(route.surface, marketing, docs)) return notFound()",
  'identity: \'data-agroai-platform-page="landing"\'',
  'identity: \'data-agroai-platform-page="docs"\'',
  'return unavailable("identity-mismatch")',
  "This page doesn",
  "x-agroai-product-entry",
  "Enterprise Portal",
  "API Platform",
  "Open API Platform",
  'label==="open portal"',
  "href===PORTAL",
  'querySelectorAll("a,button")',
]) {
  assert.ok(source.includes(required), `missing worker contract: ${required}`);
}

assert.match(source, /\^\\\/platform-api\\\/contract\\\/\(platform_api_openapi\\\.json\|platform_api_openapi\\\.sha256\)\$/);
assert.match(source, /request\.method === "HEAD"/);
assert.match(source, /status: 405/);
assert.match(source, /status: 503/);
assert.match(source, /status: 404/);

assert.match(landing, /<html lang="en" data-agroai-platform-page="landing">/);
assert.match(landing, /<title>AGRO-AI Platform API<\/title>/);
assert.match(landing, /<meta name="robots" content="noindex,nofollow"/);
assert.match(docs, /<html lang="en" data-agroai-platform-page="docs">/);
assert.match(docs, /<title>AGRO-AI Platform API Documentation<\/title>/);
assert.match(docs, /<meta name="robots" content="noindex"/);

assert.match(portalRoutes, /path: "\/platform\/\*", Component: PlatformProduct/);
assert.match(portalRoutes, /isPlatformHostname/);
assert.match(portalShell, /name: "Platform API", path: "\/platform"/);
for (const productCapability of [
  "Projects", "Service accounts", "API keys", "Playground", "Usage", "Logs", "Webhooks", "Documentation", "Support",
]) {
  assert.ok(consoleSource.includes(`"${productCapability}"`), `missing developer console capability: ${productCapability}`);
}

console.log("Platform API product entry, bundled routes, and developer console contract: ok");
