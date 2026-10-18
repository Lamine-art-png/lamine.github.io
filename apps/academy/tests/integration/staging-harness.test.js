// Runs the remote staging test (tests/remote/staging.mjs) over real HTTP
// against the Worker configured exactly as staging, so the script that the
// deploy workflow runs against Cloudflare is itself tested.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import worker from "../../src/index.js";
import { makeEnv, Client } from "../helpers.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const TOKEN = "t".repeat(40);

async function serve(env) {
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const body = chunks.length ? Buffer.concat(chunks) : undefined;
    const request = new Request(`${env.APP_ORIGIN}${req.url}`, { method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body });
    const pending = [];
    const r = await worker.fetch(request, env, { waitUntil: (p) => pending.push(p) });
    await Promise.allSettled(pending);
    const headers = {};
    r.headers.forEach((v, k) => {
      if (k !== "set-cookie") headers[k] = v;
    });
    const cookies = r.headers.getSetCookie();
    if (cookies.length) headers["set-cookie"] = cookies;
    res.writeHead(r.status, headers);
    res.end(Buffer.from(await r.arrayBuffer()));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return server;
}

function runStaging(base, token) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [join(root, "tests/remote/staging.mjs"), base], { env: { ...process.env, STAGING_TEST_INBOX_TOKEN: token } });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("close", (code) => resolve({ code, out }));
  });
}

async function stagingEnv(overrides = {}) {
  const env = makeEnv({ ENVIRONMENT: "staging", CERT_SIGNING_SECRET: "s".repeat(64), STAGING_TEST_TOKEN: TOKEN, ...overrides });
  const server = await serve(env);
  env.APP_ORIGIN = `http://127.0.0.1:${server.address().port}`;
  return { env, server, base: env.APP_ORIGIN };
}

test("the staging integration test passes end to end over HTTP", async () => {
  // A1 is not published (its normal pre-launch state): the write path still runs fully.
  const { env, server, base } = await stagingEnv();
  const r = await runStaging(base, TOKEN);
  server.close();
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /✔ register a synthetic learner/);
  assert.match(r.out, /✔ staging probe course is published through the revision path/);
  assert.match(r.out, /✔ enrollment, progress and lesson completion/);
  assert.match(r.out, /✔ certification exam attempt, grading and certificate issuance — AGA-/);
  assert.match(r.out, /✔ public verification recomputes the certificate signature/);
  assert.doesNotMatch(r.out, /skipped/);
  assert.equal((await env.DB.prepare("SELECT number FROM course_revisions WHERE course_id = 'crs_staging_probe'").first()).number, 1);
  assert.match(r.out, /✔ password reset email and new password/);
  assert.match(r.out, /✔ delete the synthetic learner/);
  const left = await env.DB.prepare("SELECT COUNT(*) AS n FROM users WHERE email LIKE '%@academy-staging-test.invalid'").first();
  assert.equal(left.n, 0, "synthetic learner removed");
  const sent = await env.DB.prepare("SELECT COUNT(*) AS n FROM email_outbox WHERE to_email LIKE '%@academy-staging-test.invalid' AND status != 'suppressed'").first();
  assert.equal(sent.n, 0, "synthetic mail never queued for delivery");
});

test("a missing or short inbox token fails the staging gate instead of skipping writes", async () => {
  for (const token of ["", "short-token"]) {
    const { server, base } = await stagingEnv();
    const r = await runStaging(base, token);
    server.close();
    assert.equal(r.code, 1, r.out);
    assert.match(r.out, /::error::ACADEMY_STAGING_TEST_INBOX_TOKEN is missing/);
    assert.match(r.out, /Staging integration test FAILED/);
  }
});

test("the staging probe endpoint exists only on staging with the token", async () => {
  let { env, server, base } = await stagingEnv();
  assert.equal((await fetch(`${base}/__staging/probe-course`, { method: "POST" })).status, 404);
  assert.equal((await fetch(`${base}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${"x".repeat(40)}` } })).status, 404);
  assert.equal((await fetch(`${base}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } })).status, 200);
  assert.equal((await fetch(`${base}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } })).status, 200, "idempotent");
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM course_revisions WHERE course_id = 'crs_staging_probe'").first()).n, 1);
  server.close();
  ({ env, server, base } = await stagingEnv({ ENVIRONMENT: "production" }));
  assert.equal((await fetch(`${base}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } })).status, 404);
  assert.equal(await env.DB.prepare("SELECT 1 FROM courses WHERE id = 'crs_staging_probe'").first(), null);
  server.close();
});

test("the staging test refuses to write to a non-staging environment", async () => {
  const { server, base } = await stagingEnv({ ENVIRONMENT: "production" });
  const r = await runStaging(base, TOKEN);
  server.close();
  assert.equal(r.code, 1);
  assert.match(r.out, /refusing write-path checks: target reports environment "production"/);
  assert.doesNotMatch(r.out, /register a synthetic learner/);
});

test("the staging inbox is unavailable outside staging or without the token", async () => {
  for (const [envOverrides, header] of [
    [{ ENVIRONMENT: "production" }, `Bearer ${TOKEN}`],
    [{}, "Bearer wrong-token-wrong-token-wrong-token-x"],
    [{ STAGING_TEST_TOKEN: "short" }, "Bearer short"],
  ]) {
    const env = makeEnv({ ENVIRONMENT: "staging", CERT_SIGNING_SECRET: "s".repeat(64), STAGING_TEST_TOKEN: TOKEN, ...envOverrides });
    const r = await new Client(env).get("/__staging/inbox?to=a@academy-staging-test.invalid", { headers: { authorization: header } });
    assert.equal(r.status, 404);
  }
  const env = makeEnv({ ENVIRONMENT: "staging", CERT_SIGNING_SECRET: "s".repeat(64), STAGING_TEST_TOKEN: TOKEN });
  const r = await new Client(env).get("/__staging/inbox?to=someone@example.com", { headers: { authorization: `Bearer ${TOKEN}` } });
  assert.equal(r.status, 404, "only synthetic test addresses can be read");
});
