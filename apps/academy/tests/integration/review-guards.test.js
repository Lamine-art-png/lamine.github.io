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

test("overlapping draw rules are checked as one pool, as the runtime draws them", async () => {
  const env = makeEnv();
  const course = await env.DB.prepare("SELECT * FROM courses WHERE id = 'crs_a1'").first();
  const quizCheck = async () => (await publishReadiness(env, course)).checks.find((c) => /linked quiz|cannot take/.test(c.label));
  const rule = await env.DB.prepare("SELECT * FROM draft_assessment_rules WHERE assessment_id = 'asm_a1_q1' ORDER BY sort_order LIMIT 1").first();
  const pool = (await env.DB.prepare(`SELECT COUNT(*) AS n FROM draft_questions WHERE bank_id = ? AND status = 'active' ${rule.difficulty ? "AND difficulty = ?" : ""}`).bind(...(rule.difficulty ? [rule.bank_id, rule.difficulty] : [rule.bank_id])).first()).n;
  // Two rules over the same questions, each satisfiable alone, together needing one more than exist.
  const half = Math.ceil(pool / 2);
  await env.DB.prepare("DELETE FROM draft_assessment_rules WHERE assessment_id = 'asm_a1_q1'").run();
  await env.DB.batch(
    [1, 2].map((n) =>
      env.DB.prepare("INSERT INTO draft_assessment_rules (id, assessment_id, bank_id, difficulty, draw_count, sort_order) VALUES (?, 'asm_a1_q1', ?, ?, ?, ?)").bind(`rul_overlap_${n}`, rule.bank_id, rule.difficulty, n === 1 ? half : pool - half + 1, n),
    ),
  );
  const check = await quizCheck();
  assert.equal(check.ok, false, `${half} + ${pool - half + 1} from ${pool} questions`);
  assert.match(check.label, /need more active questions/);
  await env.DB.prepare("UPDATE draft_assessment_rules SET draw_count = ? WHERE id = 'rul_overlap_2'").bind(pool - half).run();
  assert.equal((await quizCheck()).ok, true, "exactly enough questions for both rules");
});

test("disabled super administrators do not count as the remaining one", async () => {
  const env = makeEnv();
  const founder = await registeredLearner(env, { email: "founder@academy.test" });
  await registeredLearner(env, { email: "other@academy.test" });
  const ids = Object.fromEntries((await env.DB.prepare("SELECT id, email FROM users").all()).results.map((x) => [x.email, x.id]));
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'super_admin', ?)").bind(ids["other@academy.test"], new Date().toISOString()).run();
  await env.DB.prepare("UPDATE users SET status = 'disabled' WHERE id = ?").bind(ids["other@academy.test"]).run();
  // Dropping their own role is refused...
  let r = await founder.post(`/admin/learners/${ids["founder@academy.test"]}/roles`, { roles: ["academy_admin"] });
  assert.match(decodeURIComponent(r.location), /only super administrator/);
  assert.ok(await env.DB.prepare("SELECT 1 FROM user_roles WHERE user_id = ? AND role = 'super_admin'").bind(ids["founder@academy.test"]).first());
  // ...and so is deleting their account.
  await founder.get("/account");
  r = await founder.post("/account/delete", { confirm: "DELETE", password: founder.password });
  assert.equal(r.status, 409);
  assert.ok(await env.DB.prepare("SELECT 1 FROM users WHERE id = ?").bind(ids["founder@academy.test"]).first());
  // With the other super administrator active again, both are allowed.
  await env.DB.prepare("UPDATE users SET status = 'active' WHERE id = ?").bind(ids["other@academy.test"]).run();
  r = await founder.post(`/admin/learners/${ids["founder@academy.test"]}/roles`, { roles: ["academy_admin"] });
  assert.doesNotMatch(decodeURIComponent(r.location), /only super administrator/);
});

/** Run `other` once, just before the next batch: a concurrent request that landed between the check and the write. */
function beforeNextBatch(env, other) {
  const orig = env.DB.batch.bind(env.DB);
  env.DB.batch = async (stmts) => {
    env.DB.batch = orig;
    await other();
    return orig(stmts);
  };
}

test("two super administrators removing themselves at once never leave none", async () => {
  const env = makeEnv();
  const founder = await registeredLearner(env, { email: "founder@academy.test" });
  await registeredLearner(env, { email: "other@academy.test" });
  const ids = Object.fromEntries((await env.DB.prepare("SELECT id, email FROM users").all()).results.map((x) => [x.email, x.id]));
  const grant = () => env.DB.prepare("INSERT OR IGNORE INTO user_roles (user_id, role, granted_at) VALUES (?, 'super_admin', ?)").bind(ids["other@academy.test"], new Date().toISOString()).run();
  const otherLeaves = () => env.DB.prepare("DELETE FROM user_roles WHERE user_id = ? AND role = 'super_admin'").bind(ids["other@academy.test"]).run();
  const activeSupers = async () => (await env.DB.prepare("SELECT COUNT(*) AS n FROM user_roles r JOIN users u ON u.id = r.user_id WHERE r.role = 'super_admin' AND u.status = 'active'").first()).n;
  // Self-demotion: the check sees the other super administrator, who leaves before the write.
  await grant();
  beforeNextBatch(env, otherLeaves);
  let r = await founder.post(`/admin/learners/${ids["founder@academy.test"]}/roles`, { roles: ["academy_admin"] });
  assert.match(decodeURIComponent(r.location), /only super administrator/);
  assert.equal(await activeSupers(), 1, "the founder kept the role");
  // Account deletion, same race.
  await grant();
  await founder.get("/account");
  beforeNextBatch(env, otherLeaves);
  r = await founder.post("/account/delete", { confirm: "DELETE", password: founder.password });
  assert.equal(r.status, 409);
  assert.ok(await env.DB.prepare("SELECT 1 FROM users WHERE id = ?").bind(ids["founder@academy.test"]).first(), "the account was not deleted");
  assert.equal(await activeSupers(), 1);
  // Without a concurrent removal, demotion with another active super administrator still works.
  await grant();
  r = await founder.post(`/admin/learners/${ids["founder@academy.test"]}/roles`, { roles: ["academy_admin"] });
  assert.doesNotMatch(decodeURIComponent(r.location), /only super administrator/);
  assert.equal(await activeSupers(), 1, "the other super administrator remains");
});

test("draws from unrelated banks do not count against a pool", async () => {
  const env = makeEnv();
  const course = await env.DB.prepare("SELECT * FROM courses WHERE id = 'crs_a1'").first();
  const now = new Date().toISOString();
  const q = (id, bank, difficulty) =>
    env.DB.prepare("INSERT INTO draft_questions (id, bank_id, type, difficulty, prompt, data_json, answer_json, grading, points, status, created_at, updated_at) VALUES (?, ?, 'true_false', ?, 'Synthetic', '{}', '{\"correct\":true}', 'auto', 1, 'active', ?, ?)").bind(id, bank, difficulty, now, now);
  const rule = (id, bank, difficulty, draw, order) => env.DB.prepare("INSERT INTO draft_assessment_rules (id, assessment_id, bank_id, difficulty, draw_count, sort_order) VALUES (?, 'asm_a1_q1', ?, ?, ?, ?)").bind(id, bank, difficulty, draw, order);
  await env.DB.batch([
    env.DB.prepare("INSERT INTO draft_question_banks (id, course_id, title, created_at, updated_at) VALUES ('bnk_A','crs_a1','A',?,?), ('bnk_B','crs_a1','B',?,?)").bind(now, now, now, now),
    q("qa1", "bnk_A", "easy"), q("qa2", "bnk_A", "easy"), q("qa3", "bnk_A", "hard"), q("qb1", "bnk_B", "easy"), q("qb2", "bnk_B", "easy"),
    env.DB.prepare("DELETE FROM draft_assessment_rules WHERE assessment_id = 'asm_a1_q1'"),
    // 1 of A's 2 easy, then 2 of B, then 2 of A's 3: at most 1 of A's questions is gone, so 2 remain.
    rule("r1", "bnk_A", "easy", 1, 1), rule("r2", "bnk_B", null, 2, 2), rule("r3", "bnk_A", null, 2, 3),
  ]);
  const check = (await publishReadiness(env, course)).checks.find((c) => /linked quiz|cannot take/.test(c.label));
  assert.equal(check.ok, true, check.label);
  await env.DB.prepare("UPDATE draft_assessment_rules SET draw_count = 3 WHERE id = 'r3'").run();
  assert.equal((await publishReadiness(env, course)).checks.find((c) => /linked quiz|cannot take/.test(c.label)).ok, false, "3 of A after 1 drawn is too many");
});

test("two super administrators disabling each other at once never leave none", async () => {
  const env = makeEnv();
  const founder = await registeredLearner(env, { email: "founder@academy.test" });
  await registeredLearner(env, { email: "other@academy.test" });
  const ids = Object.fromEntries((await env.DB.prepare("SELECT id, email FROM users").all()).results.map((x) => [x.email, x.id]));
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'super_admin', ?)").bind(ids["other@academy.test"], new Date().toISOString()).run();
  // The other super administrator disables the founder between the founder's check and write.
  beforeNextBatch(env, () => env.DB.prepare("UPDATE users SET status = 'disabled' WHERE id = ?").bind(ids["founder@academy.test"]).run());
  const r = await founder.post(`/admin/learners/${ids["other@academy.test"]}/status`, { status: "disabled" });
  assert.match(decodeURIComponent(r.location), /only active super administrator/);
  assert.equal((await env.DB.prepare("SELECT status FROM users WHERE id = ?").bind(ids["other@academy.test"]).first()).status, "active", "one super administrator stays active");
});

test("an enrollment racing an archive is refused, including re-enrolling after withdrawal", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const archive = () => env.DB.prepare("UPDATE courses SET status = 'archived' WHERE id = 'crs_a1'").run();
  const u = await registeredLearner(env);
  // The course is archived after the request's status check, before its insert.
  const orig = env.DB.prepare.bind(env.DB);
  env.DB.prepare = (sql) => {
    if (/INSERT INTO enrollments/.test(sql)) {
      env.DB.prepare = orig;
      const st = orig(sql);
      const bind = st.bind.bind(st);
      st.bind = (...a) => {
        const b = bind(...a);
        const run = b.run.bind(b);
        b.run = async () => (await archive(), run());
        return b;
      };
      return st;
    }
    return orig(sql);
  };
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  assert.equal(await env.DB.prepare("SELECT COUNT(*) AS n FROM enrollments WHERE course_id = 'crs_a1'").first().then((x) => x.n), 0, "no enrollment in an archived course");
  assert.equal((await u.get("/learn/introduction-to-ai-in-agriculture/welcome")).status, 404, "no classroom access");
  // Withdrawn learners cannot re-activate once the course is archived either.
  await env.DB.prepare("UPDATE courses SET status = 'published' WHERE id = 'crs_a1'").run();
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  await env.DB.prepare("UPDATE enrollments SET status = 'withdrawn' WHERE course_id = 'crs_a1'").run();
  const { enroll } = await import("../../src/services/progress.js");
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = ?").bind(u.email).first();
  const course = await env.DB.prepare("SELECT * FROM courses WHERE id = 'crs_a1'").first(); // loaded while still published
  await archive();
  await assert.rejects(enroll({ env, user, cfg: {}, locale: "en", defer: () => {} }, course), /course_not_open/);
  assert.equal((await env.DB.prepare("SELECT status FROM enrollments WHERE course_id = 'crs_a1'").first()).status, "withdrawn");
});

test("a promotion racing a status change keeps a lower role from disabling the new super administrator", async () => {
  const env = makeEnv();
  await registeredLearner(env, { email: "founder@academy.test" });
  const staff = await registeredLearner(env, { email: "staff@academy.test" });
  const target = await registeredLearner(env, { email: "target@academy.test" });
  const ids = Object.fromEntries((await env.DB.prepare("SELECT id, email FROM users").all()).results.map((x) => [x.email, x.id]));
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'academy_admin', ?)").bind(ids["staff@academy.test"], new Date().toISOString()).run();
  // The target is promoted after the staff member's role check, before the write.
  beforeNextBatch(env, () => env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'super_admin', ?)").bind(ids["target@academy.test"], new Date().toISOString()).run());
  const r = await staff.post(`/admin/learners/${ids["target@academy.test"]}/status`, { status: "disabled" });
  assert.equal(r.status, 403);
  assert.equal((await env.DB.prepare("SELECT status FROM users WHERE id = ?").bind(ids["target@academy.test"]).first()).status, "active");
  assert.equal((await target.get("/dashboard")).status, 200, "the new super administrator stays signed in");
});

test("a poster URL cannot inject markup into the lesson page", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  await env.DB.prepare("UPDATE video_assets SET status='approved', duration_seconds=200, mp4_url='https://media.example/a1.mp4', poster_url=? WHERE id='vid_a1_data'")
    .bind('https://media.example/p.jpg"><meta http-equiv="refresh" content="0;url=https://evil.example">')
    .run();
  await env.DB.prepare("UPDATE lessons SET type='video' WHERE id='les_a1_data'").run();
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  const page = await u.get("/learn/introduction-to-ai-in-agriculture/data-the-raw-material");
  assert.equal(page.status, 200);
  assert.doesNotMatch(page.text, /<meta http-equiv="refresh"/);
  assert.match(page.text, /poster="https:\/\/media\.example\/p\.jpg&quot;&gt;&lt;meta/);
});

/** A1 with an extra manually graded quiz; returns the learner and a started attempt of it. */
async function manualQuizSetup() {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare("INSERT INTO question_banks (id, course_id, title, created_at, updated_at) VALUES ('bnk_m','crs_a1','manual',?,?)").bind(now, now),
    env.DB.prepare(
      "INSERT INTO questions (id, bank_id, type, difficulty, prompt, data_json, answer_json, grading, points, rubric, status, created_at, updated_at) VALUES ('q_m','bnk_m','short_answer','medium','Explain drift.','{\"max_length\":600}','{\"accepted\":[]}','manual',2,'Mentions changing conditions','active',?,?)",
    ).bind(now, now),
    env.DB.prepare("INSERT INTO assessments (id, course_id, kind, title, passing_score, feedback_policy, status, created_at, updated_at) VALUES ('asm_m','crs_a1','quiz','Manual quiz',50,'full','active',?,?)").bind(now, now),
    env.DB.prepare("INSERT INTO assessment_rules (id, assessment_id, bank_id, draw_count) VALUES ('rul_m','asm_m','bnk_m',1)"),
  ]);
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  const r = await u.post("/assessments/asm_m/start", {});
  return { env, u, attemptId: r.location.split("/").pop() };
}

test("grading a pending answer after the learner withdrew never completes the enrollment", async () => {
  const { env, u, attemptId } = await manualQuizSetup();
  await u.post(`/attempts/${attemptId}/submit`, { "q[q_m]": "Conditions change." });
  // Everything else in the course is done; only the manual answer is pending.
  const { completeA1 } = await import("../helpers.js");
  await completeA1(env, u);
  await env.DB.prepare("UPDATE enrollments SET status = 'withdrawn', completed_at = NULL WHERE course_id = 'crs_a1'").run();
  await env.DB.prepare("DELETE FROM certificates").run();
  const grader = await registeredLearner(env, { email: "founder@academy.test" });
  await grader.post(`/admin/grading/${attemptId}/q_m`, { points: "2", comment: "Good." });
  const e = await env.DB.prepare("SELECT status FROM enrollments WHERE course_id = 'crs_a1'").first();
  assert.equal(e.status, "withdrawn", "withdrawal is not undone");
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM certificates").first()).n, 0, "no certificate issued");
});

test("an in-progress attempt cannot be viewed, saved or submitted after withdrawal", async () => {
  const { env, u, attemptId } = await manualQuizSetup();
  await u.post("/courses/introduction-to-ai-in-agriculture/withdraw", {});
  assert.equal((await env.DB.prepare("SELECT status FROM enrollments WHERE course_id = 'crs_a1'").first()).status, "withdrawn");
  assert.equal((await u.get(`/attempts/${attemptId}`)).status, 403);
  assert.equal((await u.postJson(`/api/attempts/${attemptId}/save`, { responses: { q_m: "late" } })).status, 403);
  assert.equal((await u.post(`/attempts/${attemptId}/submit`, { "q[q_m]": "late" })).status, 403);
  const a = await env.DB.prepare("SELECT status, submitted_at FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.deepEqual({ ...a }, { status: "in_progress", submitted_at: null });
  // A save racing the withdrawal is rejected by the write itself.
  const { saveResponses } = await import("../../src/services/assessments.js");
  const attempt = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  await saveResponses(env, attempt, { q_m: "raced" });
  assert.equal((await env.DB.prepare("SELECT response_json FROM attempt_answers WHERE attempt_id = ?").bind(attemptId).first()).response_json, null);
});

test("a withdrawn learner cannot claim the certificate, even if withdrawal races issuance", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  const { completeA1 } = await import("../helpers.js");
  await completeA1(env, u);
  // Learner finished everything but holds no certificate (e.g. issued later after grading), then withdraws.
  await env.DB.prepare("DELETE FROM certificate_events").run();
  await env.DB.prepare("DELETE FROM certificates").run();
  await env.DB.prepare("UPDATE enrollments SET status = 'withdrawn' WHERE course_id = 'crs_a1'").run();
  const r = await u.post("/certificates/claim/introduction-to-ai-in-agriculture", {});
  assert.match(r.location, /missing=cert\.reason\.enrollment/);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM certificates").first()).n, 0);
  // Eligible at check time, withdrawn before the insert: the insert itself refuses.
  await env.DB.prepare("UPDATE enrollments SET status = 'completed' WHERE course_id = 'crs_a1'").run();
  beforeNextBatch(env, () => env.DB.prepare("UPDATE enrollments SET status = 'withdrawn' WHERE course_id = 'crs_a1'").run());
  const { issueIfEligible } = await import("../../src/services/certificates.js");
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = ?").bind(u.email).first();
  const course = await env.DB.prepare("SELECT * FROM courses WHERE id = 'crs_a1'").first();
  const out = await issueIfEligible(env, { certSecret: "synthetic-test-secret", origin: "https://academy.test" }, user, course);
  assert.equal(out.certificate, null);
  assert.deepEqual(out.reasons, ["cert.reason.enrollment"]);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM certificates").first()).n, 0);
});

test("the scheduled job never grades a withdrawn learner's expired attempt", async () => {
  const { env, u, attemptId } = await manualQuizSetup();
  await env.DB.prepare("UPDATE attempts SET deadline_at = ? WHERE id = ?").bind(new Date(Date.now() - 3600_000).toISOString(), attemptId).run();
  await u.post("/courses/introduction-to-ai-in-agriculture/withdraw", {});
  const { runScheduled } = await import("../../src/services/jobs.js");
  await runScheduled(env);
  let a = await env.DB.prepare("SELECT status, submitted_at FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.deepEqual({ ...a }, { status: "in_progress", submitted_at: null }, "left untouched while withdrawn");
  // Closing it directly is refused by the write itself.
  const { submitAttempt } = await import("../../src/services/assessments.js");
  const attempt = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  const user = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(attempt.user_id).first();
  await assert.rejects(submitAttempt({ env, user, cfg: {}, defer: () => {} }, attempt, { auto: true }), /not_enrolled/);
  a = await env.DB.prepare("SELECT status FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a.status, "in_progress");
});

test("an attempt cannot be started by a request racing the learner's withdrawal", async () => {
  const { env, u } = await manualQuizSetup();
  await env.DB.prepare("DELETE FROM attempt_answers").run();
  await env.DB.prepare("DELETE FROM attempts").run();
  beforeNextBatch(env, () => env.DB.prepare("UPDATE enrollments SET status = 'withdrawn' WHERE course_id = 'crs_a1'").run());
  const r = await u.post("/assessments/asm_m/start", {});
  assert.equal(r.status, 403);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM attempts").first()).n, 0);
});
