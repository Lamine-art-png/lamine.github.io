import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../assets/reference.js", import.meta.url), "utf8");

for (const expression of [
  'extra.push("min " + esc(schema.minimum))',
  'extra.push("max " + esc(schema.maximum))',
  'extra.push("≤" + esc(schema.maxLength) + " chars")',
  'extra.push("default " + esc(JSON.stringify(schema.default)))',
  'esc(p.description || "")',
  'esc(op.summary)',
  'esc(readiness[k])',
  'esc(sec.bearerFormat || "agro_test_... or agro_live_...")',
]) {
  assert.ok(source.includes(expression), `reference renderer must escape contract-derived HTML value: ${expression}`);
}

assert.ok(!source.includes('extra.push("default " + JSON.stringify(schema.default))'), "schema defaults must never enter innerHTML without escaping");
assert.ok(!source.includes('extra.push("min " + schema.minimum)'), "schema minimum values must never enter innerHTML without escaping");
assert.ok(!source.includes('extra.push("max " + schema.maximum)'), "schema maximum values must never enter innerHTML without escaping");
assert.ok(source.includes("Permanent API keys") || source.includes("never with a browser-held key"), "the reference renderer must preserve the no-browser-key boundary");
assert.ok(!source.includes("sessionStorage") && !source.includes("localStorage"), "the reference surface must not persist credentials");

console.log("Platform API reference renderer contract passed: contract-derived annotations are escaped and no browser-key storage exists.");
