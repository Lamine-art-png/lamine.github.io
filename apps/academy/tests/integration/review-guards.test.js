// Regression tests for the Codex review of f8dcc66: pre-account hijacking
// through email verification, lower roles disabling super administrators,
// unusable quizzes passing readiness, and graders overriding auto-scored answers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, publishCourse, lastEmail, tokenFrom } from "../helpers.js";
import { publishReadiness } from "../../src/services/readiness.js";

const ATTACKER_PASSWORD = "attacker chosen passphrase 1";

test("verifying an address registered by someone else signs them out and clears their password", async () => {
  const env = makeEnv();
  // The attacker registers the victim's address and stays signed in.
  const attacker = await registeredLearner(env, { email: "victim@academy.test", verify: false, password: ATTACKER_PASSWORD });
  assert.equal((await attacker.get("/dashboard")).status, 200);
  const tok = tokenFrom(await lastEmail(env, "victim@academy.test", "verify_email"), "/verify-email");
  // The victim confirms the unsolicited email in their own browser.
  const victim = new Client(env);
  await victim.get(`/verify-email?token=${tok}`);
  const r = await victim.post("/verify-email", { token: tok });
  assert.equal(r.status, 303);
  assert.match(r.location, /^\/reset-password\?token=/, "the mailbox owner chooses the password");
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = 'victim@academy.test'").first();
  assert.ok(user.email_verified_at);
  assert.equal(user.password_hash, null);
  assert.equal((await attacker.get("/dashboard")).status, 303, "the attacker's session is revoked");
  const again = new Client(env);
  await again.get("/login");
  assert.equal((await again.post("/login", { email: "victim@academy.test", password: ATTACKER_PASSWORD })).status, 401, "the attacker's password no longer works");
  // The victim sets a password through the link they were sent to.
  const reset = new URL(r.location, "https://academy.test");
  await victim.get(reset.pathname + reset.search);
  assert.equal((await victim.post("/reset-password", { token: reset.searchParams.get("token"), password: "mailbox owner passphrase 2" })).status, 303);
  await again.get("/login");
  assert.equal((await again.post("/login", { email: "victim@academy.test", password: "mailbox owner passphrase 2" })).status, 303);
});

test("verifying from the registrant's own session keeps that session and password, and signs out others", async () => {
  const env = makeEnv();
  const u = await registeredLearner(env, { email: "self@academy.test", verify: false });
  const other = new Client(env);
  await other.get("/login");
  await other.post("/login", { email: u.email, password: u.password });
  const tok = tokenFrom(await lastEmail(env, "self@academy.test", "verify_email"), "/verify-email");
  await u.get(`/verify-email?token=${tok}`);
  const r = await u.post("/verify-email", { token: tok });
  assert.equal(r.location, "/dashboard?verified=1");
  assert.equal((await u.get("/dashboard")).status, 200);
  assert.equal((await other.get("/dashboard")).status, 303, "sessions from before verification are revoked");
  assert.ok((await env.DB.prepare("SELECT password_hash FROM users WHERE email = 'self@academy.test'").first()).password_hash);
});

test("an academy administrator cannot disable a super administrator", async () => {
  const env = makeEnv();
  const founder = await registeredLearner(env, { email: "founder@academy.test" }); // bootstrap super administrator
  const staff = await registeredLearner(env, { email: "staff@academy.test" });
  const learner = await registeredLearner(env, { email: "someone@academy.test" });
  const ids = Object.fromEntries((await env.DB.prepare("SELECT id, email FROM users").all()).results.map((x) => [x.email, x.id]));
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'academy_admin', ?)").bind(ids["staff@academy.test"], new Date().toISOString()).run();
  let r = await staff.post(`/admin/learners/${ids["founder@academy.test"]}/status`, { status: "disabled" });
  assert.equal(r.status, 403);
  assert.equal((await env.DB.prepare("SELECT status FROM users WHERE id = ?").bind(ids["founder@academy.test"]).first()).status, "active");
  assert.equal((await founder.get("/admin")).status, 200, "the super administrator stays signed in");
  // Ordinary accounts can still be managed.
  r = await staff.post(`/admin/learners/${ids["someone@academy.test"]}/status`, { status: "disabled" });
  assert.equal(r.status, 303);
  assert.equal((await env.DB.prepare("SELECT status FROM users WHERE id = ?").bind(ids["someone@academy.test"]).first()).status, "disabled");
  assert.equal((await learner.get("/dashboard")).status, 303);
});

test("readiness refuses quiz lessons whose assessment learners cannot take", async () => {
  const env = makeEnv();
  const course = await env.DB.prepare("SELECT * FROM courses WHERE id = 'crs_a1'").first();
  const quizCheck = async () => (await publishReadiness(env, course)).checks.find((c) => /linked quiz|cannot take/.test(c.label));
  assert.equal((await quizCheck()).ok, true, "seeded quizzes are usable");
  await env.DB.prepare("UPDATE draft_assessments SET status = 'draft' WHERE id = 'asm_a1_q1'").run();
  let check = await quizCheck();
  assert.equal(check.ok, false);
  assert.match(check.label, /assessment is draft/);
  await env.DB.prepare("UPDATE draft_assessments SET status = 'active' WHERE id = 'asm_a1_q1'").run();
  await env.DB.prepare("UPDATE draft_assessment_rules SET draw_count = 999 WHERE assessment_id = 'asm_a1_q1'").run();
  check = await quizCheck();
  assert.equal(check.ok, false);
  assert.match(check.label, /need more active questions/);
  await env.DB.prepare("DELETE FROM draft_assessment_rules WHERE assessment_id = 'asm_a1_q1'").run();
  assert.match((await quizCheck()).label, /no question draw rules/);
});

test("graders can only score answers awaiting manual review", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare("INSERT INTO question_banks (id, course_id, title, created_at, updated_at) VALUES ('bnk_m','crs_a1','mixed',?,?)").bind(now, now),
    env.DB.prepare(
      "INSERT INTO questions (id, bank_id, type, difficulty, prompt, data_json, answer_json, grading, points, rubric, status, created_at, updated_at) VALUES ('q_m','bnk_m','short_answer','medium','Explain drift.','{\"max_length\":600}','{\"accepted\":[]}','manual',2,'Mentions changing conditions','active',?,?)",
    ).bind(now, now),
    env.DB.prepare(
      "INSERT INTO questions (id, bank_id, type, difficulty, prompt, data_json, answer_json, grading, points, status, created_at, updated_at) VALUES ('q_auto','bnk_m','single','easy','Pick one.','{\"options\":[{\"id\":\"o1\",\"text\":\"Right\"},{\"id\":\"o2\",\"text\":\"Wrong\"}]}','{\"correct\":[\"o1\"]}','auto',8,'active',?,?)",
    ).bind(now, now),
    env.DB.prepare("INSERT INTO assessments (id, course_id, kind, title, passing_score, feedback_policy, shuffle_questions, shuffle_options, status, created_at, updated_at) VALUES ('asm_m','crs_a1','quiz','Mixed quiz',50,'full',0,0,'active',?,?)").bind(now, now),
    env.DB.prepare("INSERT INTO assessment_rules (id, assessment_id, bank_id, draw_count) VALUES ('rul_m','asm_m','bnk_m',2)"),
  ]);
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  let r = await u.post("/assessments/asm_m/start", {});
  const attemptId = r.location.split("/").pop();
  await u.post(`/attempts/${attemptId}/submit`, { "q[q_m]": "Conditions change.", "q[q_auto]": "o2" });
  assert.equal((await env.DB.prepare("SELECT status FROM attempts WHERE id = ?").bind(attemptId).first()).status, "pending_review");
  const grader = await registeredLearner(env, { email: "founder@academy.test" });
  // The automatically scored (wrong) answer cannot be overridden.
  r = await grader.post(`/admin/grading/${attemptId}/q_auto`, { points: "8", comment: "" });
  assert.equal(r.status, 404);
  const auto = await env.DB.prepare("SELECT points_awarded, is_correct, reviewer_id FROM attempt_answers WHERE attempt_id = ? AND question_id = 'q_auto'").bind(attemptId).first();
  assert.deepEqual({ ...auto }, { points_awarded: 0, is_correct: 0, reviewer_id: null });
  // The manual answer is graded; the result counts the auto-scored answer as scored.
  r = await grader.post(`/admin/grading/${attemptId}/q_m`, { points: "2", comment: "Good." });
  assert.equal(r.status, 303);
  const a = await env.DB.prepare("SELECT status, score_pct, passed FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.deepEqual({ ...a }, { status: "graded", score_pct: 20, passed: 0 });
  // Once graded, no answer can be changed.
  r = await grader.post(`/admin/grading/${attemptId}/q_m`, { points: "0", comment: "" });
  assert.equal(r.status, 404);
});
