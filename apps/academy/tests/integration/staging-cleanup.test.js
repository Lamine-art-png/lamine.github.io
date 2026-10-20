// One-off staging cleanup of synthetic accounts left by failed test runs: only
// named, verifiably synthetic accounts are deleted, through the normal
// account-deletion service, and any doubt about one account refuses them all.
import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "../../src/index.js";
import { makeEnv, registeredLearner, ORIGIN } from "../helpers.js";
import { ensureProbeCourse, PROBE } from "../../src/services/staging-probe.js";

const TOKEN = "t".repeat(40);
const FROM = "2000-01-01T00:00:00.000Z";
const TO = "2999-01-01T00:00:00.000Z";

async function call(env, body, token = TOKEN) {
  const r = await worker.fetch(
    new Request(`${ORIGIN}/__staging/cleanup`, { method: "POST", headers: { authorization: `Bearer ${token}`, "content-type": "application/json" }, body: JSON.stringify(body) }),
    env,
    { waitUntil() {} },
  );
  return { status: r.status, body: (r.headers.get("content-type") || "").includes("json") ? await r.json() : null };
}

/** What a failed run leaves: a learner with a probe-course certificate and a staff account. */
async function leftovers(env) {
  await ensureProbeCourse(env);
  const learner = await registeredLearner(env, { email: "staging-mg1abc-x1y2z@academy-staging-test.invalid" });
  const staff = await registeredLearner(env, { email: "staging-staff-mg1abc-x1y2z@academy-staging-test.invalid" });
  const id = async (email) => (await env.DB.prepare("SELECT id FROM users WHERE email = ?").bind(email).first()).id;
  const learnerId = await id(learner.email);
  const staffId = await id(staff.email);
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO enrollments (id, user_id, course_id, enrolled_at, last_activity_at) VALUES ('enr_left', ?, ?, ?, ?)").bind(learnerId, PROBE.courseId, now, now).run();
  await env.DB.prepare(
    "INSERT INTO certificates (id, credential_id, user_id, course_id, credential_name, course_title, issued_at, signature, created_at) VALUES ('crt_left', 'AGA-LEFT-OVER-0001', ?, ?, 'Staging Test', 'Probe', ?, 'sig', ?)",
  ).bind(learnerId, PROBE.courseId, now, now).run();
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_by, granted_at) VALUES (?, 'academy_admin', 'staging-test', ?)").bind(staffId, now).run();
  return { learnerId, staffId };
}

const stagingEnv = () => makeEnv({ ENVIRONMENT: "staging", STAGING_TEST_TOKEN: TOKEN });

test("cleanup: check reports without deleting, then delete removes only the named synthetic accounts", async () => {
  const env = stagingEnv();
  const real = await registeredLearner(env, { email: "person@example.org" });
  const { learnerId, staffId } = await leftovers(env);
  const ids = [learnerId, staffId];

  let r = await call(env, { ids, from: FROM, to: TO, mode: "check" });
  assert.equal(r.status, 200);
  assert.equal(r.body.deleted, 0);
  assert.ok(r.body.accounts.every((a) => a.eligible), JSON.stringify(r.body.accounts.map((a) => a.failed)));
  assert.ok(!JSON.stringify(r.body).includes("@"), "the report never contains an address");
  assert.equal(r.body.before.users, 3, "check deletes nothing");

  r = await call(env, { ids, from: FROM, to: TO, mode: "delete" });
  assert.equal(r.status, 200);
  assert.equal(r.body.deleted, 2);
  assert.deepEqual(r.body.remaining.map((x) => x.account + x.sessions + x.auth_tokens + x.certificates_held), [0, 0]);
  assert.equal(r.body.after.users, 1);
  assert.equal(r.body.after.synthetic_users, 0);
  const cert = await env.DB.prepare("SELECT status, user_id, revoked_reason, credential_name FROM certificates WHERE id = 'crt_left'").first();
  assert.deepEqual({ ...cert }, { status: "revoked", user_id: null, revoked_reason: "holder_account_deleted", credential_name: "Former learner" });
  assert.ok(await env.DB.prepare("SELECT 1 FROM users WHERE email = ?").bind(real.email).first(), "the real account is untouched");
  const audit = (await env.DB.prepare("SELECT actor_id FROM audit_log WHERE action = 'user.delete'").all()).results;
  assert.deepEqual(audit.map((a) => a.actor_id), ["staging-cleanup", "staging-cleanup"]);
});

test("cleanup refuses everything if any named account is real, out of window, privileged or has an early-access record", async () => {
  const env = stagingEnv();
  const real = await registeredLearner(env, { email: "person@example.org" });
  const realId = (await env.DB.prepare("SELECT id FROM users WHERE email = ?").bind(real.email).first()).id;
  const { learnerId, staffId } = await leftovers(env);
  const users = async () => (await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first()).n;

  let r = await call(env, { ids: [learnerId, realId], from: FROM, to: TO, mode: "delete" });
  assert.equal(r.status, 409);
  assert.equal(r.body.deleted, 0);
  assert.deepEqual(r.body.accounts.find((a) => a.id === realId).failed.slice(0, 2), ["staging_test_domain", "staging_test_address_pattern"]);
  assert.equal(await users(), 3, "nothing deleted, not even the eligible account");

  r = await call(env, { ids: [learnerId], from: "2000-01-01T00:00:00.000Z", to: "2000-01-02T00:00:00.000Z", mode: "delete" });
  assert.equal(r.status, 409);
  assert.deepEqual(r.body.accounts[0].failed, ["created_in_failed_run_window"]);

  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_by, granted_at) VALUES (?, 'super_admin', 'someone', ?)").bind(staffId, new Date().toISOString()).run();
  r = await call(env, { ids: [staffId], from: FROM, to: TO, mode: "delete" });
  assert.equal(r.status, 409);
  assert.deepEqual(r.body.accounts[0].failed, ["only_test_roles"]);

  await env.DB.prepare(
    "INSERT INTO early_access_registrants (id, source, email, registered_at, imported_at, status) VALUES ('ear_1', 'test', 'staging-mg1abc-x1y2z@academy-staging-test.invalid', ?, ?, 'pending')",
  ).bind(new Date().toISOString(), new Date().toISOString()).run();
  r = await call(env, { ids: [learnerId], from: FROM, to: TO, mode: "delete" });
  assert.equal(r.status, 409);
  assert.deepEqual(r.body.accounts[0].failed, ["no_early_access_record"]);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM early_access_registrants").first()).n, 1, "early-access records are never touched");
  assert.equal(await users(), 3);
});

test("cleanup is absent outside staging and without the token, and rejects malformed requests", async () => {
  const env = stagingEnv();
  const { learnerId } = await leftovers(env);
  assert.equal((await call(env, { ids: [learnerId], from: FROM, to: TO, mode: "delete" }, "x".repeat(40))).status, 404);
  assert.equal((await call(makeEnv({ ENVIRONMENT: "production", STAGING_TEST_TOKEN: TOKEN }), { ids: [learnerId], from: FROM, to: TO, mode: "delete" })).status, 404);
  assert.equal((await call(env, { ids: [learnerId], from: FROM, to: TO })).status, 400, "mode is required");
  assert.equal((await call(env, { ids: [], from: FROM, to: TO, mode: "check" })).status, 400);
  assert.equal((await call(env, { ids: [learnerId], from: TO, to: FROM, mode: "check" })).status, 400);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first()).n, 2);
});
