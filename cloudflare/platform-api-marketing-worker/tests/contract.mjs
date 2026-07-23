import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
const config = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
const landing = readFileSync(new URL("../../../platform-api/index.html", import.meta.url), "utf8");
const docs = readFileSync(new URL("../../../platform-api/docs/index.html", import.meta.url), "utf8");

assert.match(config, /name = "agroai-platform-api-marketing"/);
assert.match(config, /pattern = "agroai-pilot\.com\/platform-api\*"/);
assert.match(config, /PLATFORM_API_MARKETING_ENABLED = "true"/);
assert.match(config, /PLATFORM_API_PUBLIC_DOCS_ENABLED = "true"/);
assert.match(config, /PLATFORM_API_INDEXING_ENABLED = "false"/);
assert.match(config, /MARKETING_ORIGIN = "https:\/\/agroai-343\.pages\.dev"/);

for (const required of [
  '"x-robots-tag": "noindex, nofollow"',
  'headers.set("x-robots-tag", "noindex, nofollow")',
  'headers.set("cache-control", "private, no-cache, must-revalidate")',
  'headers.set("x-agroai-platform-api-surface", route.surface)',
  'const PLATFORM_CONSOLE = "https://platform.agroai-pilot.com"',
  'if (!route) return notFound()',
  'if (!surfaceEnabled(route.surface, marketing, docs)) return notFound()',
  '"/platform-api/docs/": { upstreamPath: "/platform-api/docs/index.html"',
]) {
  assert.ok(source.includes(required), `missing worker contract: ${required}`);
}

assert.match(source, /\^\\\/platform-api\\\/contract\\\/\(platform_api_openapi\\\.json\|platform_api_openapi\\\.sha256\)\$/);
assert.match(source, /<title>AGRO-AI Platform API<\/title>/);
assert.match(source, /<title>AGRO-AI Platform API Documentation<\/title>/);
assert.match(source, /request\.method === "HEAD"/);
assert.match(source, /status: 405/);
assert.match(source, /status: 503/);
assert.match(source, /status: 404/);
assert.doesNotMatch(source, /fetch\(request\)/);

assert.match(landing, /<meta name="robots" content="noindex,nofollow"/);
assert.match(docs, /<meta name="robots" content="noindex"/);

console.log("Platform API marketing overlay contract: ok");
