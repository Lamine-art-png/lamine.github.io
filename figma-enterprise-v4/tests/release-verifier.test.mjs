// Regression tests for scripts/verify-production-release.mjs: a release must
// never verify when deployment.json has the wrong environment, the wrong cache
// policy, or an inconsistent identity, even when every other check passes.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SHA = "a".repeat(40);
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const verifier = join(root, "scripts", "verify-production-release.mjs");

function release({ environment = "production", deploymentCache = "no-store, max-age=0, must-revalidate", identityAfterFirstRead = SHA } = {}) {
  const chunks = Array.from({ length: 12 }, (_, i) => `chunk${i}-abcdef${i}.js`);
  const entry = `/assets/index-abcdef12.js`;
  const html = `<!doctype html><html><head><meta name="agroai-build" content="${SHA}"><script type="module" crossorigin src="${entry}"></script></head><body></body></html>`;
  let deploymentReads = 0;
  return createServer((req, res) => {
    const path = new URL(req.url, "http://x").pathname;
    const send = (status, body, headers) => { res.writeHead(status, headers); res.end(body); };
    if (path === "/deployment.json") {
      deploymentReads += 1;
      const build = deploymentReads === 1 ? SHA : identityAfterFirstRead;
      return send(200, JSON.stringify({ build_sha: build, environment, entry }), { "content-type": "application/json", "cache-control": deploymentCache });
    }
    if (path === "/" || path === "/team") return send(200, html, { "content-type": "text/html; charset=utf-8", "cache-control": path === "/" ? "no-store, max-age=0, must-revalidate" : "public, max-age=0, must-revalidate" });
    if (path === entry) return send(200, chunks.map((c) => `import("./${c}");`).join("\n"), { "content-type": "application/javascript", "cache-control": "public, max-age=31536000, immutable" });
    if (path.startsWith("/assets/chunk")) return send(200, "export default 1;", { "content-type": "application/javascript", "cache-control": "public, max-age=31536000, immutable" });
    if (path.startsWith("/assets/")) return send(404, "missing", { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
    if (path === "/sw.js") return send(200, `const BUILD_ID = "${SHA}";`, { "content-type": "application/javascript", "cache-control": "no-store" });
    if (path === "/v1/health") return send(200, JSON.stringify({ status: "ok" }), { "content-type": "application/json" });
    return send(404, "", {});
  });
}

async function verify(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    return await new Promise((resolve) => {
      const child = spawn(process.execPath, [verifier, "--url", url, "--sha", SHA, "--timeout-seconds", "3", "--retry-interval-ms", "500"]);
      let output = "";
      child.stdout.on("data", (d) => { output += d; });
      child.stderr.on("data", (d) => { output += d; });
      child.on("close", (code) => resolve({ code, output }));
    });
  } finally {
    server.close();
  }
}

test("a fully consistent release verifies", async () => {
  const { code, output } = await verify(release());
  assert.equal(code, 0, output);
  assert.match(output, new RegExp(`production_release_verified=${SHA}`));
});

test("wrong deployment environment fails even though checks 2-6 pass", async () => {
  const { code, output } = await verify(release({ environment: "staging" }));
  assert.notEqual(code, 0, output);
  assert.match(output, /FAIL deployment\.json environment is production/);
  assert.match(output, /ok {3}all \d+ release assets load as immutable non-HTML/);
  assert.doesNotMatch(output, /production_release_verified/);
});

test("wrong deployment cache policy fails even though checks 2-6 pass", async () => {
  const { code, output } = await verify(release({ deploymentCache: "public, max-age=3600" }));
  assert.notEqual(code, 0, output);
  assert.match(output, /FAIL deployment\.json is no-store/);
  assert.doesNotMatch(output, /production_release_verified/);
});

test("deployment identity that changes after the initial read fails", async () => {
  const { code, output } = await verify(release({ identityAfterFirstRead: "b".repeat(40) }));
  assert.notEqual(code, 0, output);
  assert.match(output, /FAIL deployment\.json identity is/);
  assert.doesNotMatch(output, /production_release_verified/);
});
