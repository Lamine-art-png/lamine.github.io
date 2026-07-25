// Frontend runtime recovery contract.
//
// Prevents a stale Cloudflare Pages or service-worker shell from serving HTML
// to a JavaScript module request, which causes Chrome to reject the module on
// MIME-type grounds while a fresh browser can still appear healthy.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const main = readFileSync(join(root, "src", "main.tsx"), "utf8");
const sw = readFileSync(join(root, "public", "sw.js"), "utf8");
const headers = readFileSync(join(root, "public", "_headers"), "utf8");

assert.match(main, /agroai_frontend_cache_recovery_attempted/);
assert.match(main, /isStaleFrontendAssetError/);
assert.match(main, /window\.caches\.delete/);
assert.match(main, /registration\.unregister\(\)/);
assert.match(main, /updateViaCache:\s*"none"/);
assert.match(main, /registration\.update\(\)/);
assert.match(main, /frontend_recovery/);

assert.match(sw, /CACHE_VERSION = `\$\{CACHE_FAMILY\}v2`/);
assert.match(sw, /isJavaScriptResponse/);
assert.match(sw, /invalidJavaScriptAsset/);
assert.match(sw, /application\/javascript; charset=utf-8/);
assert.match(sw, /fetch\(request, \{ cache: "no-store" \}\)/);
assert.doesNotMatch(sw, /cache\.put\(request, response\.clone\(\)\)[\s\S]*return invalidJavaScriptAsset/);

assert.match(headers, /\/index\.html[\s\S]*Cache-Control: no-store/);
assert.match(headers, /\/sw\.js[\s\S]*Cache-Control: no-store/);
assert.match(headers, /\/assets\/\*[\s\S]*max-age=31536000, immutable/);

console.log("Frontend runtime recovery contract passed");
