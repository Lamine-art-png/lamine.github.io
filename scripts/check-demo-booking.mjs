import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Script } from "node:vm";

const source = readFileSync("cloudflare/form-page-runtime/src/index.js", "utf8");
const declaration = source.indexOf("const runtimeSource = String.raw");
assert.ok(declaration >= 0, "Cloudflare runtime is present");
const delimiter = String.fromCharCode(96);
const start = source.indexOf(delimiter, declaration) + 1;
const end = source.indexOf(delimiter + ";", start);
assert.ok(start > 0 && end > start, "Runtime template can be extracted");
const runtime = source.slice(start, end);

// The outer Worker and the JavaScript delivered to browsers must both parse.
new Script(source, { filename: "cloudflare-form-worker.js" });
new Script(runtime, { filename: "agroai-forms-runtime.js" });

// Existing careers route, POST targets, and notification success gate stay in place.
assert.match(runtime, /fetch\("\/api\/apply"/);
assert.match(runtime, /fetch\("\/api\/demo-request"/);
assert.match(runtime, /"Application received"/);
assert.match(runtime, /"Demo request received"/);
assert.match(runtime, /response\.headers\.get\("x-agroai-notification"\) !== "delivered"/);

// Calendar never substitutes for the original lead capture and confirmation.
const confirmedSubmission = runtime.indexOf('const result = await parseJson(response);', runtime.indexOf('fetch("/api/demo-request"'));
const deliveryCheck = runtime.indexOf('response.headers.get("x-agroai-notification") !== "delivered"', confirmedSubmission);
const calendarCall = runtime.indexOf("showDemoScheduling(form,", deliveryCheck);
assert.ok(confirmedSubmission >= 0 && deliveryCheck > confirmedSubmission && calendarCall > deliveryCheck);

// One scheduling provider owns availability/conflicts/confirmation.
assert.match(runtime, /https:\/\/calendly\.com\/agroaicontact\/30min/);
assert.match(runtime, /Calendly\.initInlineWidget/);
assert.match(runtime, /https:\/\/assets\.calendly\.com\/assets\/external\/widget\.js/);
assert.match(runtime, /calendly\.event_scheduled/);
assert.match(runtime, /prefill:\s*\{[\s\S]*?name:[\s\S]*?email:/);
assert.match(runtime, /target = "_blank"/);
assert.match(runtime, /rel = "noopener noreferrer"/);

// Calendly or iframe failure must not hide the direct scheduling fallback.
assert.match(runtime, /wrapper\.append\(heading, intro, status, fallback, calendar\)/);
assert.match(runtime, /script\.onerror/);
console.log("Demo scheduling regression checks passed.");
