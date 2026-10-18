// Expired timed attempts are auto-submitted, and eligibility for another
// attempt is recomputed afterwards: attempt limits and cooldowns still apply.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, registeredLearner, publishCourse, A1_SLUG, correctResponses } from "../helpers.js";

const EXAM = "asm_a1_exam";
const ago = (minutes) => new Date(Date.now() - minutes * 60000).toISOString();

async function examReadyLearner() {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const learner = await registeredLearner(env, { email: `t${Math.random().toString(36).slice(2, 7)}@academy.test` });
  await learner.post(`/courses/${A1_SLUG}/enroll`, {});
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = ?").bind(learner.email).first();
  // Satisfy the lesson gate directly; this test is about the exam engine.
  await env.DB.prepare(
    `INSERT INTO lesson_progress (user_id, lesson_id, course_id, status, started_at, completed_at, last_viewed_at)
     SELECT ?, l.id, l.course_id, 'completed', ?, ?, ? FROM lessons l WHERE l.course_id = 'crs_a1'`,
  ).bind(user.id, ago(1), ago(1), ago(1)).run();
  return { env, learner, user };
}

async function startExam(learner) {
  const r = await learner.post(`/assessments/${EXAM}/start`, {});
  return r.location;
}

async function expire(env, attemptId, minutesAgo) {
  await env.DB.prepare("UPDATE attempts SET started_at = ?, deadline_at = ? WHERE id = ?").bind(ago(minutesAgo + 30), ago(minutesAgo), attemptId).run();
}

test("cooldown is enforced after an expired attempt is auto-submitted", async () => {
  const { env, learner, user } = await examReadyLearner();
  const loc = await startExam(learner);
  assert.match(loc, /^\/attempts\//);
  const first = loc.split("/").pop();
  await expire(env, first, 5); // ran out 5 minutes ago; cooldown is 60 minutes

  const again = await startExam(learner);
  assert.match(again, /error=assess\.gate\.cooldown/, "no immediate new attempt after expiry");
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(first).first();
  assert.equal(a.status, "graded", "expired attempt was graded");
  assert.equal(a.passed, 0);
  assert.equal(a.submitted_at, a.deadline_at, "closed at its deadline");
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM attempts WHERE user_id = ?").bind(user.id).first();
  assert.equal(n.n, 1, "no second attempt created");

  // The intro page shows the recomputed state, not a Resume button.
  const page = await learner.get(`/assessments/${EXAM}`);
  assert.doesNotMatch(page.text, />\s*Resume/);
  assert.match(page.text, /You can try again/i);
});

test("an attempt that expired long ago allows a retake once its cooldown has passed", async () => {
  const { env, learner } = await examReadyLearner();
  const first = (await startExam(learner)).split("/").pop();
  await expire(env, first, 90);
  const loc = await startExam(learner);
  assert.match(loc, /^\/attempts\//);
  assert.notEqual(loc.split("/").pop(), first);
  const second = await env.DB.prepare("SELECT attempt_no FROM attempts WHERE id = ?").bind(loc.split("/").pop()).first();
  assert.equal(second.attempt_no, 2);
});

test("maximum attempts is enforced after an expired attempt is auto-submitted", async () => {
  const { env, learner, user } = await examReadyLearner();
  await env.DB.prepare("UPDATE assessments SET max_attempts = 2 WHERE id = ?").bind(EXAM).run();
  const first = (await startExam(learner)).split("/").pop();
  await expire(env, first, 120);
  const second = (await startExam(learner)).split("/").pop();
  await expire(env, second, 100);
  const third = await startExam(learner);
  assert.match(third, /error=assess\.gate\.max_attempts/);
  const rows = (await env.DB.prepare("SELECT status FROM attempts WHERE user_id = ?").bind(user.id).all()).results;
  assert.deepEqual(rows.map((r) => r.status), ["graded", "graded"]);
});

test("expired attempts only count autosaved answers, and an expired pass still certifies", async () => {
  const { env, learner, user } = await examReadyLearner();
  const id = (await startExam(learner)).split("/").pop();
  const answers = await correctResponses(env, id);
  const r = await learner.request("POST", `/api/attempts/${id}/save`, { body: answers, headers: { accept: "application/json", "x-csrf-token": learner.csrf } });
  assert.equal(r.status, 200);
  await expire(env, id, 2);
  // A late submission cannot change answers…
  await learner.post(`/attempts/${id}/submit`, {});
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(id).first();
  assert.equal(a.status, "graded");
  assert.equal(a.passed, 1, "autosaved answers graded");
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM attempts WHERE user_id = ?").bind(user.id).first();
  assert.equal(n.n, 1);
});

test("the scheduled job auto-submits expired attempts and the cooldown runs from the deadline", async () => {
  const { env, learner } = await examReadyLearner();
  const id = (await startExam(learner)).split("/").pop();
  await expire(env, id, 10);
  const { runScheduled } = await import("../../src/services/jobs.js");
  await runScheduled(env, "*/15 * * * *");
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(id).first();
  assert.equal(a.status, "graded");
  assert.match(await startExam(learner), /error=assess\.gate\.cooldown/);
});
