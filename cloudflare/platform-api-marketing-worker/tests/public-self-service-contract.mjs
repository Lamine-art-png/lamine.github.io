import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
const wrangler = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
const docs = readFileSync(new URL("../../../platform-api/docs/index.html", import.meta.url), "utf8");

// A code deployment alone must remain private/noindex.
assert.match(wrangler, /PLATFORM_API_PUBLIC_SELF_SERVICE_ENABLED\s*=\s*"false"/);
assert.match(wrangler, /PLATFORM_API_INDEXING_ENABLED\s*=\s*"false"/);

// Runtime mode is explicit, server-side, and represented in response evidence.
assert.ok(source.includes("PLATFORM_API_PUBLIC_SELF_SERVICE_ENABLED?: string"));
assert.ok(source.includes('publicSelfService ? "public-test-self-service" : "private-beta"'));
assert.ok(source.includes('headers.set("x-agroai-platform-api-access"'));
assert.ok(source.includes("if (indexing) headers.delete(\"x-robots-tag\")"));
assert.ok(source.includes('headers.set("x-robots-tag", "noindex, nofollow")'));

// Public mode changes acquisition copy but does not alter LIVE/provider/physical state.
assert.ok(source.includes("normalizePublicSelfServiceHtml"));
assert.ok(source.includes("Self-service TEST access is open to eligible verified agricultural developers."));
assert.ok(source.includes("LIVE projects, production providers, billing, production webhooks, and physical execution remain separately gated."));
assert.ok(source.includes("PLATFORM_API_PUBLIC_SELF_SERVICE_ENABLED"));
assert.ok(!source.includes("PLATFORM_API_LIVE_PROJECTS_ENABLED"));
assert.ok(!source.includes("VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED"));

// Static docs are deliberately safe to serve before activation; the Worker owns launch presentation.
assert.ok(docs.includes("AGRO-AI Platform API Documentation"));

// Unknown routes remain genuine closed 404s in either mode.
assert.ok(source.includes('status: 404'));
assert.ok(source.includes('"x-agroai-platform-api-surface": "closed"'));
assert.ok(source.includes('"x-robots-tag": "noindex, nofollow"'));

console.log("Platform marketing public/private cutover contract passed.");
