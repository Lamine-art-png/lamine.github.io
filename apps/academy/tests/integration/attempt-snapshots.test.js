// Attempts are frozen at creation: changing questions, answer keys, scoring
// settings, translations or the assessment policy afterwards never changes
// what an open or finished attempt shows, how it is scored, its passing
// threshold or its deadline. Live rows are changed directly here, as a
// published revision of the course would change them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, registeredLearner, publishCourse, correctResponses, A1_SLUG } from "../helpers.js";

const EXAM = "asm_a1_exam";

async function examInProgress() {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const learner = await registeredLearner(env, { email: `s${Math.random().toString(36).slice(2, 7)}@academy.test` });
  await learner.post(`/courses/${A1_SLUG}/enroll`, {});
  await env.DB.prepare("UPDATE lessons SET is_required = 0 WHERE course_id = 'crs_a1'").run();
  const r = await learner.post(`/assessments/${EXAM}/start`, {});
  const attemptId = r.location.split("/").pop();
  const attempt = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  const layout = JSON.parse(attempt.layout_json);
  return { env, learner, attemptId, attempt, layout };
}

const save = (learner, attemptId, body) =>
  learner.request("POST", `/api/attempts/${attemptId}/save`, { body, headers: { accept: "application/json", "x-csrf-token": learner.csrf } });

test("changing questions and answer keys during an active exam does not change the attempt", async () => {
  const { env, learner, attemptId, layout } = await examInProgress();
  const single = (await env.DB.prepare(`SELECT * FROM questions WHERE id IN (${layout.map(() => "?").join(",")}) AND type = 'single' LIMIT 1`).bind(...layout.map((l) => l.q)).first());
  const before = await learner.get(`/attempts/${attemptId}`);
  const answers = await correctResponses(env, attemptId);
  assert.equal((await save(learner, attemptId, answers)).status, 200);

  // An administrator rewrites the question: new prompt, the correct option removed, a new key.
  const data = JSON.parse(single.data_json);
  const correct = JSON.parse(single.answer_json).correct[0];
  data.options = data.options.filter((o) => o.id !== correct).concat([{ id: "zz", text: "A brand-new option" }]);
  await env.DB.prepare("UPDATE questions SET prompt = 'REWRITTEN PROMPT', data_json = ?, answer_json = ?, points = 9 WHERE id = ?").bind(JSON.stringify(data), JSON.stringify({ correct: ["zz"] }), single.id).run();
  // …and every other question in the attempt gets a key that the saved answers fail.
  for (const { q } of layout) if (q !== single.id) await env.DB.prepare("UPDATE questions SET answer_json = '{\"correct\":[\"nope\"],\"value\":false,\"accepted\":[\"nope\"],\"pairs\":{},\"order\":[]}', grading = 'manual' WHERE id = ?").bind(q).run();

  const during = await learner.get(`/attempts/${attemptId}`);
  assert.doesNotMatch(during.text, /REWRITTEN PROMPT|A brand-new option/);
  assert.ok(during.text.includes(single.prompt.replace(/&/g, "&amp;").replace(/'/g, "&#39;").replace(/"/g, "&quot;")) || during.text.includes(single.prompt), "original prompt still shown");
  // Autosave still accepts the original option ids.
  assert.equal(JSON.parse((await save(learner, attemptId, { [`q[${single.id}]`]: correct })).text).saved, 1);
  assert.equal(before.status, 200);

  await learner.post(`/attempts/${attemptId}/submit`, {});
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a.status, "graded", "no question became manually graded");
  assert.equal(a.score_pct, 100);
  assert.equal(a.passed, 1);
  const row = await env.DB.prepare("SELECT max_points FROM attempt_answers WHERE attempt_id = ? AND question_id = ?").bind(attemptId, single.id).first();
  assert.equal(row.max_points, single.points, "points are those of the question as presented");
});

test("changing the passing score, time limit and feedback policy mid-exam does not change the result or deadline", async () => {
  const { env, learner, attemptId, attempt } = await examInProgress();
  // Answer 85% correctly: pass at 80, fail at 90.
  const answers = await correctResponses(env, attemptId);
  const keys = Object.keys(answers).filter((k) => k.startsWith("q["));
  const layout = JSON.parse(attempt.layout_json);
  const wrongIds = layout.slice(0, 3).map((l) => l.q);
  for (const k of Object.keys(answers)) if (wrongIds.some((id) => k.includes(`[${id}]`))) delete answers[k];
  void keys;
  await save(learner, attemptId, answers);

  await env.DB.prepare("UPDATE assessments SET passing_score = 95, time_limit_seconds = 60, feedback_policy = 'full', max_attempts = 1 WHERE id = ?").bind(EXAM).run();
  let page = await learner.get(`/attempts/${attemptId}`);
  assert.match(page.text, new RegExp(`data-deadline="${attempt.deadline_at}"`), "deadline unchanged");
  assert.equal((await env.DB.prepare("SELECT deadline_at FROM attempts WHERE id = ?").bind(attemptId).first()).deadline_at, attempt.deadline_at);

  await learner.post(`/attempts/${attemptId}/submit`, {});
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.ok(a.score_pct >= 80 && a.score_pct < 95, `score ${a.score_pct}`);
  assert.equal(a.passed, 1, "judged against the 80% threshold in force when it started");
  page = await learner.get(`/attempts/${attemptId}`);
  assert.match(page.text, /80/);
  // Exams started under a hidden-answers policy keep hiding answers after the policy changes.
  assert.doesNotMatch(page.text, /Correct answer/);
});

test("a finished attempt's review and score never change after later edits", async () => {
  const { env, learner, attemptId, layout } = await examInProgress();
  await learner.post(`/attempts/${attemptId}/submit`, await correctResponses(env, attemptId));
  const graded = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  const reviewBefore = (await learner.get(`/attempts/${attemptId}`)).text.replace(/<meta name="csrf-token"[^>]+>/, "");
  await env.DB.prepare(`UPDATE questions SET prompt = prompt || ' (edited)', answer_json = '{"correct":["x"]}' WHERE id IN (${layout.map(() => "?").join(",")})`).bind(...layout.map((l) => l.q)).run();
  await env.DB.prepare("UPDATE assessments SET passing_score = 100, feedback_policy = 'full' WHERE id = ?").bind(EXAM).run();
  const after = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.deepEqual(after, graded);
  const reviewAfter = (await learner.get(`/attempts/${attemptId}`)).text.replace(/<meta name="csrf-token"[^>]+>/, "");
  assert.doesNotMatch(reviewAfter, /\(edited\)/);
  assert.equal(reviewAfter.replace(/data-server-now="[^"]+"/, ""), reviewBefore.replace(/data-server-now="[^"]+"/, ""));
});

test("manual grading after a policy change uses the attempt's threshold", async () => {
  const { env, learner, attemptId, layout } = await examInProgress();
  // One question in this attempt is graded by a person (as frozen in its snapshot).
  const sa = { question_id: layout[0].q };
  await env.DB.prepare("UPDATE attempt_answers SET question_json = json_set(question_json, '$.grading', 'manual') WHERE attempt_id = ? AND question_id = ?").bind(attemptId, sa.question_id).run();
  await learner.post(`/attempts/${attemptId}/submit`, await correctResponses(env, attemptId));
  assert.equal((await env.DB.prepare("SELECT status FROM attempts WHERE id = ?").bind(attemptId).first()).status, "pending_review");
  await env.DB.prepare("UPDATE assessments SET passing_score = 100 WHERE id = ?").bind(EXAM).run();
  const founder = await registeredLearner(env, { email: "founder@academy.test" });
  await founder.get(`/admin/grading`);
  const max = (await env.DB.prepare("SELECT max_points FROM attempt_answers WHERE attempt_id = ? AND question_id = ?").bind(attemptId, sa.question_id).first()).max_points;
  const r = await founder.post(`/admin/grading/${attemptId}/${sa.question_id}`, { points: String(max * 0), comment: "Too brief." });
  assert.equal(r.status, 303);
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a.status, "graded");
  assert.ok(a.score_pct >= 80 && a.score_pct < 100);
  assert.equal(a.passed, 1, "the 80% threshold applies, not the later 100%");
  void layout;
});
