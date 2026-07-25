import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");
const read = (path) => readFileSync(resolve(root, path), "utf8");

const source = read("cloudflare/platform-api-marketing-worker/src/index.ts");
const fallback = read("functions/platform-api/[[path]].ts");
const config = read("cloudflare/platform-api-marketing-worker/wrangler.toml");
const portalRoutes = read("figma-enterprise-v4/src/app/routes.tsx");
const portalShell = read("figma-enterprise-v4/src/app/components/MainLayout.tsx");
const consoleSource = read("figma-enterprise-v4/src/app/components/PlatformConsole.tsx");
const officialLogo = read("platform-api/assets/logo.svg");

const htmlFiles = [
  "platform-api/index.html",
  "platform-api/reference.html",
  "platform-api/changelog.html",
  "platform-api/docs/index.html",
  "platform-api/docs/authentication.html",
  "platform-api/docs/pagination.html",
  "platform-api/docs/errors.html",
  "platform-api/docs/rate-limits.html",
  "platform-api/docs/support.html",
];

const exactRoutes = [
  "/platform-api", "/platform-api/", "/platform-api/index.html",
  "/platform-api/reference", "/platform-api/reference.html",
  "/platform-api/changelog", "/platform-api/changelog.html",
  "/platform-api/docs", "/platform-api/docs/", "/platform-api/docs/index.html",
  "/platform-api/docs/authentication", "/platform-api/docs/authentication.html",
  "/platform-api/docs/pagination", "/platform-api/docs/pagination.html",
  "/platform-api/docs/errors", "/platform-api/docs/errors.html",
  "/platform-api/docs/rate-limits", "/platform-api/docs/rate-limits.html",
  "/platform-api/docs/support", "/platform-api/docs/support.html",
];

assert.match(config, /name = "agroai-platform-api-marketing"/);
assert.match(config, /pattern = "agroai-pilot\.com\/"/);
assert.match(config, /pattern = "agroai-pilot\.com\/platform-api"/);
assert.match(config, /pattern = "agroai-pilot\.com\/platform-api\/\*"/);
assert.match(config, /directory = "\.\.\/\.\.\/platform-api"/);
assert.match(config, /binding = "ASSETS"/);
assert.match(config, /run_worker_first = true/);
assert.match(config, /html_handling = "none"/);
assert.match(config, /not_found_handling = "none"/);
assert.match(config, /PLATFORM_API_MARKETING_ENABLED = "true"/);
assert.match(config, /PLATFORM_API_PUBLIC_DOCS_ENABLED = "true"/);
assert.match(config, /PLATFORM_API_INDEXING_ENABLED = "false"/);

for (const required of [
  "ASSETS: Fetcher",
  "env.ASSETS.fetch",
  '"x-robots-tag": "noindex, nofollow"',
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
]) {
  assert.ok(source.includes(required), `missing worker contract: ${required}`);
}

for (const required of [
  'const OFFICIAL_LOGO = "/platform-api/assets/logo.svg"',
  'new URL(mapping.asset, "https://agroai-assets.invalid")',
  'headers: { accept: mapping.html ? "text/html"',
  'return unavailable("identity-mismatch")',
  '"x-agroai-platform-api-surface": "closed"',
  "HTML_FAILURE_MARKERS",
]) {
  assert.ok(fallback.includes(required), `missing fallback contract: ${required}`);
}

assert.match(officialLogo, /aria-label="AGRO-AI official logo"/);
assert.match(officialLogo, /data:image\/webp;base64,/);
assert.doesNotMatch(officialLogo, /id="agLeaf"|<rect x="1" y="1"/);

for (const relativePath of htmlFiles) {
  const absolutePath = resolve(root, relativePath);
  assert.ok(existsSync(absolutePath), `missing Platform page: ${relativePath}`);
  const html = read(relativePath);
  assert.match(html, /<title>[^<]*AGRO-AI Platform API[^<]*<\/title>/, `wrong title: ${relativePath}`);
  assert.match(html, /<img src="\/platform-api\/assets\/logo\.svg"/, `official header logo missing: ${relativePath}`);
  assert.doesNotMatch(html, /This page doesn[’']t exist|>404</i, `error page leaked into source: ${relativePath}`);
}

for (const route of exactRoutes) {
  assert.ok(source.includes(`"${route}"`), `Worker route missing: ${route}`);
  assert.ok(fallback.includes(`"${route}"`), `Pages fallback route missing: ${route}`);
}

assert.match(source, /\^\\\/platform-api\\\/assets\\\//);
assert.match(source, /\^\\\/platform-api\\\/contract\\\//);
assert.match(fallback, /\^\\\/platform-api\\\/assets\\\//);
assert.match(fallback, /\^\\\/platform-api\\\/contract\\\//);

assert.match(portalRoutes, /path: "\/platform\/\*", Component: PlatformProduct/);
assert.match(portalRoutes, /isPlatformHostname/);
assert.match(portalShell, /name: "Platform API", path: "\/platform"/);
for (const productCapability of [
  "Projects", "Service accounts", "API keys", "Playground", "Usage", "Logs", "Webhooks", "Documentation", "Support",
]) {
  assert.ok(consoleSource.includes(`"${productCapability}"`), `missing developer console capability: ${productCapability}`);
}

console.log(`Platform API contract green: ${htmlFiles.length} pages, ${exactRoutes.length} exact routes, official branding, exact asset handling.`);
