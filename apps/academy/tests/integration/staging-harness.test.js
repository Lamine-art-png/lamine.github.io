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
import { makeEnv, Client, fakeR2 } from "../helpers.js";

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
  const env = makeEnv({ ENVIRONMENT: "staging", CERT_SIGNING_SECRET: "s".repeat(64), STAGING_TEST_TOKEN: TOKEN, FILES: fakeR2(), ...overrides });
  const server = await serve(env);
  env.APP_ORIGIN = `http://127.0.0.1:${server.address().port}`;
  return { env, server, base: env.APP_ORIGIN };
}

test("the staging integration test passes end to end over HTTP", async (t) => {
  // A1 is not published (its normal pre-launch state): the write path still runs fully.
  const { env, server, base } = await stagingEnv();
  t.after(() => server.close());
  const r = await runStaging(base, TOKEN);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /✔ register a synthetic learner/);
  assert.match(r.out, /✔ staging probe course is published through the revision path/);
  assert.match(r.out, /✔ enrollment, progress and lesson completion/);
  assert.match(r.out, /✔ certification exam attempt, grading and certificate issuance — AGA-/);
  assert.match(r.out, /✔ public verification recomputes the certificate signature/);
  assert.doesNotMatch(r.out, /skipped/);
  for (const name of [
    "language selection: Portuguese, French, Spanish, Arabic and Persian (RTL)",
    "certificate PDF download and LinkedIn sharing",
    "administration is closed to learners",
    "staff account: admin access and role restrictions",
    "publication requires the academic approvals (Course A1 stays unpublished)",
    "R2: staff upload, learner download, anonymous refusal, removal",
    "delete the synthetic staff account",
  ])
    assert.ok(r.out.includes(`✔ ${name}`), `missing step: ${name}\n${r.out}`);
  // Two revisions in the probe step, two more around the R2 upload and its removal.
  assert.equal((await env.DB.prepare("SELECT MAX(number) AS n FROM course_revisions WHERE course_id = 'crs_staging_probe'").first()).n, 4, "four revisions published in one run");
  assert.equal(await env.DB.prepare("SELECT 1 FROM lesson_resources WHERE lesson_id = 'les_staging_probe'").first(), null, "the uploaded test file is removed again");
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM courses WHERE id = 'crs_a1' AND status = 'published'").first()).n, 0, "A1 was not published");
  // The next deploy's run publishes again.
  const again = await runStaging(base, TOKEN);
  assert.equal(again.code, 0, again.out);
  assert.match(again.out, /✔ staging probe course is published through the revision path — revision 6/);
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
  assert.equal((await fetch(`${base}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } })).status, 200, "repeatable");
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM course_revisions WHERE course_id = 'crs_staging_probe'").first()).n, 2, "each call publishes a new revision");
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

test("the staging staff endpoint: staging only, token required, synthetic verified accounts, never super_admin", async () => {
  const { env, server, base } = await stagingEnv();
  const call = (body, token = TOKEN) => fetch(`${base}/__staging/staff`, { method: "POST", headers: { authorization: `Bearer ${token}`, "content-type": "application/json" }, body: JSON.stringify(body) });
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO users (id, email, display_name, email_verified_at, created_at, updated_at) VALUES ('usr_syn', 'staff@academy-staging-test.invalid', 'Synthetic', ?, ?, ?)").bind(now, now, now).run();
  await env.DB.prepare("INSERT INTO users (id, email, display_name, email_verified_at, created_at, updated_at) VALUES ('usr_real', 'person@example.org', 'Real', ?, ?, ?)").bind(now, now, now).run();
  assert.equal((await call({ email: "staff@academy-staging-test.invalid", role: "academy_admin" }, "x".repeat(40))).status, 404, "wrong token");
  assert.equal((await call({ email: "staff@academy-staging-test.invalid", role: "super_admin" })).status, 400, "super_admin is never granted");
  assert.equal((await call({ email: "person@example.org", role: "academy_admin" })).status, 400, "only synthetic test addresses");
  assert.equal((await call({ email: "staff@academy-staging-test.invalid", role: "academy_admin" })).status, 200);
  const roles = (await env.DB.prepare("SELECT user_id, role FROM user_roles WHERE role != 'learner'").all()).results.map((x) => `${x.user_id}:${x.role}`);
  assert.deepEqual(roles, ["usr_syn:academy_admin"]);
  server.close();
  const prod = await stagingEnv({ ENVIRONMENT: "production" });
  const r = await fetch(`${prod.base}/__staging/staff`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" }, body: JSON.stringify({ email: "staff@academy-staging-test.invalid", role: "academy_admin" }) });
  prod.server.close();
  assert.equal(r.status, 404, "absent outside staging");
});

test("plain HTTP on the deployed hostname is redirected to HTTPS", async () => {
  const env = makeEnv();
  const worker = (await import("../../src/index.js")).default;
  const r = await worker.fetch(new Request("http://academy.test/courses?lang=fr", { redirect: "manual" }), env, { waitUntil() {} });
  assert.equal(r.status, 308);
  assert.equal(r.headers.get("location"), "https://academy.test/courses?lang=fr");
  const ok = await worker.fetch(new Request("https://academy.test/courses"), env, { waitUntil() {} });
  assert.equal(ok.status, 200);
});
