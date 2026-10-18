// Published content is immutable: editors change a draft, learners keep the
// live revision until the draft passes readiness (including fresh reviews)
// and is explicitly published. Publication hides or retires removed content
// instead of deleting it, so learner progress, attempts and certificates stay.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, approveReviews, correctResponses, A1_SLUG } from "../helpers.js";
import { toEditorLines } from "../../src/pages/admin/assessments.js";

const publish = (admin, id = "crs_a1") => admin.post(`/admin/courses/${id}/status`, { status: "published" });
const blocked = (r) => /Readiness checks must pass/.test(decodeURIComponent(r.location || ""));

/** A1 released as revision 1 (text-first video policy, three reviews recorded). */
async function released() {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
  await env.DB.prepare("UPDATE courses SET video_requirement = 'optional', video_waiver_reason = 'Synthetic text-first test' WHERE id = 'crs_a1'").run();
  await approveReviews(admin, "crs_a1");
  const r = await publish(admin);
  assert.ok(!blocked(r), "initial publication");
  const learner = await registeredLearner(env, { email: "learner@academy.test" });
  await learner.post(`/courses/${A1_SLUG}/enroll`, {});
  return { env, admin, learner };
}

async function lessonForm(env, id, overrides = {}) {
  const l = await env.DB.prepare("SELECT * FROM draft_lessons WHERE id = ?").bind(id).first();
  const body = {
    title: l.title, slug: l.slug, type: l.type, module_id: l.module_id, est_minutes: String(l.est_minutes), sort_order: String(l.sort_order),
    video_id: l.video_id || "", assessment_id: l.assessment_id || "", status: l.status, is_required: l.is_required ? "1" : undefined,
    is_preview: l.is_preview ? "1" : undefined, summary: l.summary, body_md: l.body_md, interactive_json: l.interactive_json || "", after: "stay", ...overrides,
  };
  for (const k of Object.keys(body)) if (body[k] === undefined) delete body[k];
  return body;
}

async function questionForm(env, id, overrides = {}) {
  const q = await env.DB.prepare("SELECT * FROM draft_questions WHERE id = ?").bind(id).first();
  const key = JSON.parse(q.answer_json);
  return {
    type: q.type, difficulty: q.difficulty, points: String(q.points), status: q.status, case_id: q.case_id || "", lesson_id: q.lesson_id || "",
    prompt: q.prompt, lines: toEditorLines(q), tf: String(key.value ?? true), grading: q.grading, match: key.match || "exact", max_length: "600",
    rubric: q.rubric || "", explanation: q.explanation || "", ...overrides,
  };
}

const live = (env, sql, ...args) => env.DB.prepare(sql).bind(...args).first();

test("edits to a published course stay in the draft until reviewed and published again", async () => {
  const { env, admin, learner } = await released();
  assert.equal((await live(env, "SELECT number FROM course_revisions WHERE course_id = 'crs_a1'")).number, 1);
  const before = await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'");

  // Lesson text, a certification question's answer key, and the course title change.
  let r = await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Synthetic replacement lesson text." }));
  assert.match(r.location, /ok=saved/);
  const q = await live(env, "SELECT * FROM questions WHERE id = 'q_a1x_e1'");
  // Move the correct mark to the next option.
  const opts = toEditorLines(q).split("\n");
  const right = opts.findIndex((l) => l.startsWith("* "));
  const lines = opts.map((l, i) => (i === (right + 1) % opts.length ? `* ${l.replace(/^\* /, "")}` : l.replace(/^\* /, ""))).join("\n");
  r = await admin.post("/admin/questions/q_a1x_e1", await questionForm(env, "q_a1x_e1", { lines }));
  assert.match(r.location, /ok=saved/);

  // Learners and the live tables are unchanged.
  assert.equal((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, before.body_md);
  assert.equal((await live(env, "SELECT answer_json FROM questions WHERE id = 'q_a1x_e1'")).answer_json, q.answer_json);
  r = await learner.get(`/learn/${A1_SLUG}/welcome`);
  assert.doesNotMatch(r.text, /Synthetic replacement lesson text/);

  // The editor sees unpublished changes; the earlier approvals no longer apply.
  r = await admin.get("/admin/courses/crs_a1");
  assert.match(r.text, /unpublished changes/);
  assert.match(r.text, /no longer applies — the content changed afterwards/);
  assert.ok(blocked(await publish(admin)), "publication needs fresh reviews");
  assert.equal((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, before.body_md);

  // Fresh reviews, explicit publication: revision 2 goes live.
  await approveReviews(admin, "crs_a1", "Second Synthetic Reviewer");
  r = await publish(admin);
  assert.ok(!blocked(r));
  const rev = await live(env, "SELECT * FROM course_revisions WHERE course_id = 'crs_a1' ORDER BY number DESC");
  assert.equal(rev.number, 2);
  const reviewed = await live(env, "SELECT content_hash FROM course_reviews WHERE course_id = 'crs_a1' AND reviewer_name = 'Second Synthetic Reviewer' LIMIT 1");
  assert.equal(rev.content_hash, reviewed.content_hash, "the published revision is exactly the reviewed content");
  r = await learner.get(`/learn/${A1_SLUG}/welcome`);
  assert.match(r.text, /Synthetic replacement lesson text/);
  assert.notEqual((await live(env, "SELECT answer_json FROM questions WHERE id = 'q_a1x_e1'")).answer_json, q.answer_json);
  assert.ok(await live(env, "SELECT 1 FROM audit_log WHERE action = 'course.revision.published'"));
  r = await admin.get("/admin/courses/crs_a1");
  assert.match(r.text, /The draft matches the live revision/);
});

test("course settings edits (title, passing score) also wait for publication", async () => {
  const { env, admin } = await released();
  const c = await live(env, "SELECT * FROM courses WHERE id = 'crs_a1'");
  const form = {
    title: "Synthetic Renamed Course", slug: c.slug, subtitle: c.subtitle, description: c.description, objectives: JSON.parse(c.objectives_json).join("\n"),
    program_id: c.program_id || "", level: c.level, duration_minutes: String(c.duration_minutes), source_locale: c.source_locale,
    planned_release_date: c.planned_release_date || "", sort_order: String(c.sort_order), thumbnail_url: "", prerequisites_text: c.prerequisites_text,
    certificate_enabled: "1", require_all_lessons: "1", passing_score: "50", video_requirement: "optional", video_waiver_reason: c.video_waiver_reason,
  };
  const r = await admin.post("/admin/courses/crs_a1", form);
  assert.match(r.location, /ok=saved/);
  const now = await live(env, "SELECT title, passing_score FROM courses WHERE id = 'crs_a1'");
  assert.equal(now.title, c.title);
  assert.equal(now.passing_score, c.passing_score);
  assert.doesNotMatch((await new Client(env).get(`/courses/${A1_SLUG}`)).text, /Synthetic Renamed Course/);
  assert.ok(blocked(await publish(admin)));
});

test("removing content hides it from learners but keeps their progress and attempts", async () => {
  const { env, admin, learner } = await released();
  const user = await live(env, "SELECT id FROM users WHERE email = 'learner@academy.test'");
  // The learner completes a lesson and starts the module 4 lessons' exam.
  let r = await learner.post(`/learn/${A1_SLUG}/limits-and-when-to-challenge/complete`, {});
  assert.equal(r.status, 303);
  r = await learner.post("/assessments/asm_a1_q1/start", {});
  const attemptId = r.location.split("/").pop();
  const answers = await correctResponses(env, attemptId);

  // An editor removes the completed lesson and a question bank item, then republishes.
  r = await admin.post("/admin/lessons/les_a1_limits/delete", {});
  assert.match(r.location, /ok=deleted/);
  const drawn = (await env.DB.prepare("SELECT question_id FROM attempt_answers WHERE attempt_id = ? LIMIT 1").bind(attemptId).first()).question_id;
  r = await admin.post(`/admin/questions/${drawn}`, await questionForm(env, drawn, { status: "retired" }));
  assert.match(r.location, /ok=saved/);
  await approveReviews(admin, "crs_a1");
  assert.ok(!blocked(await publish(admin)));

  // Hidden, not deleted; progress kept; the lesson's old URL no longer shows it.
  const lesson = await live(env, "SELECT status, slug FROM lessons WHERE id = 'les_a1_limits'");
  assert.equal(lesson.status, "draft");
  assert.ok(await live(env, "SELECT 1 FROM lesson_progress WHERE user_id = ? AND lesson_id = 'les_a1_limits'", user.id), "progress row kept");
  r = await learner.get(`/courses/${A1_SLUG}`);
  assert.equal(r.status, 200);
  assert.match(r.text, /data-ownership-privacy-and-trust|Data ownership/);
  assert.doesNotMatch(r.text, /limits-and-when-to-challenge/);
  assert.equal((await learner.get(`/learn/${A1_SLUG}/data-ownership-privacy-and-trust`)).status, 200, "the rest of the course stays available");
  assert.equal((await learner.get(`/learn/${A1_SLUG}/limits-and-when-to-challenge`)).status, 404);
  assert.equal((await live(env, "SELECT status FROM questions WHERE id = ?", drawn)).status, "retired");

  // The attempt started before publication submits and scores on its frozen questions.
  r = await learner.post(`/attempts/${attemptId}/submit`, answers);
  const graded = await live(env, "SELECT status, score_pct FROM attempts WHERE id = ?", attemptId);
  assert.equal(graded.status, "graded");
  assert.equal(graded.score_pct, 100);

  // The freed slug can be reused by a new lesson without touching the hidden one.
  r = await admin.post("/admin/modules/mod_a1_4/lessons", { title: "Limits and when to challenge", type: "text" });
  const newId = r.location.split("/").pop().split("?")[0];
  assert.equal((await live(env, "SELECT slug FROM draft_lessons WHERE id = ?", newId)).slug, "limits-and-when-to-challenge");

  // Discarding restores exactly the published revision: removed content does not come back.
  await admin.post("/admin/courses/crs_a1/discard", {});
  assert.equal(await live(env, "SELECT 1 FROM draft_lessons WHERE id IN ('les_a1_limits', ?)", newId), null);
  assert.match((await admin.get("/admin/courses/crs_a1")).text, /The draft matches the live revision/);
});

test("content removed from the draft is retired on publication and not restored by a discard", async () => {
  const { env, admin } = await released();
  await env.DB.batch([
    env.DB.prepare("DELETE FROM draft_assessment_rules WHERE assessment_id = 'asm_a1_q3'"),
    env.DB.prepare("UPDATE draft_lessons SET assessment_id = NULL, type = 'text', body_md = 'Synthetic replacement.' WHERE id = 'les_a1_quiz3'"),
    env.DB.prepare("DELETE FROM draft_assessments WHERE id = 'asm_a1_q3'"),
    env.DB.prepare("DELETE FROM draft_questions WHERE id = 'q_a1x_e1'"),
  ]);
  await approveReviews(admin, "crs_a1");
  assert.ok(!blocked(await publish(admin)));
  const a = await live(env, "SELECT status, removed_at FROM assessments WHERE id = 'asm_a1_q3'");
  assert.equal(a.status, "retired");
  assert.ok(a.removed_at);
  assert.equal((await live(env, "SELECT status FROM questions WHERE id = 'q_a1x_e1'")).status, "retired");
  await admin.post("/admin/courses/crs_a1/discard", {});
  assert.equal(await live(env, "SELECT 1 FROM draft_assessments WHERE id = 'asm_a1_q3'"), null);
  assert.equal(await live(env, "SELECT 1 FROM draft_questions WHERE id = 'q_a1x_e1'"), null);
  assert.match((await admin.get("/admin/courses/crs_a1")).text, /The draft matches the live revision/);
});

test("a never-released course follows its draft immediately", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
  assert.equal((await live(env, "SELECT published_at FROM courses WHERE id = 'crs_a1'")).published_at, null);
  const r = await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Upcoming synthetic text." }));
  assert.match(r.location, /ok=saved/);
  assert.equal((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Upcoming synthetic text.");
  assert.match((await admin.get("/admin/courses/crs_a1")).text, /Not yet released/);
});

test("unpublished changes can be discarded", async () => {
  const { env, admin } = await released();
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Discard me." }));
  await admin.post("/admin/lessons/les_a1_summary/delete", {});
  assert.match((await admin.get("/admin/courses/crs_a1")).text, /unpublished changes/);
  const r = await admin.post("/admin/courses/crs_a1/discard", {});
  assert.match(r.location, /ok=saved/);
  assert.notEqual((await live(env, "SELECT body_md FROM draft_lessons WHERE id = 'les_a1_welcome'")).body_md, "Discard me.");
  assert.ok(await live(env, "SELECT 1 FROM draft_lessons WHERE id = 'les_a1_summary'"));
  const page = (await admin.get("/admin/courses/crs_a1")).text;
  assert.match(page, /The draft matches the live revision/);
  assert.doesNotMatch(page, /no longer applies/, "the existing approvals apply again to the restored content");
  assert.ok(await live(env, "SELECT 1 FROM audit_log WHERE action = 'course.draft.discarded'"));
});

test("only publishers can publish changes; learners cannot reach draft actions", async () => {
  const { env, admin, learner } = await released();
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Editor change." }));
  await approveReviews(admin, "crs_a1");
  const editor = await registeredLearner(env, { email: "editor@academy.test" });
  const eid = (await live(env, "SELECT id FROM users WHERE email = 'editor@academy.test'")).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'content_editor', ?)").bind(eid, new Date().toISOString()).run();
  assert.equal((await publish(editor)).status, 403);
  assert.notEqual((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Editor change.");
  assert.equal((await learner.post("/admin/courses/crs_a1/discard", {})).status, 403);
  assert.equal((await learner.post("/admin/lessons/les_a1_welcome", { body_md: "x" })).status, 403);
});

test("draw rules can only use the course's own question banks", async () => {
  const { env, admin } = await released();
  await env.DB.prepare("INSERT INTO draft_question_banks (id, course_id, title, created_at, updated_at) VALUES ('bnk_other', 'crs_a2', 'Other course bank', '2026-01-01', '2026-01-01')").run();
  const r = await admin.post("/admin/assessments/asm_a1_exam/rules", { bank_id: "bnk_other", draw_count: "1" });
  assert.match(decodeURIComponent(r.location), /belongs to this course/);
  assert.equal(await live(env, "SELECT 1 FROM draft_assessment_rules WHERE bank_id = 'bnk_other'"), null);
  // Even if one were inserted directly, readiness refuses publication.
  await env.DB.prepare("INSERT INTO draft_assessment_rules (id, assessment_id, bank_id, draw_count, sort_order) VALUES ('rul_x', 'asm_a1_exam', 'bnk_other', 1, 9)").run();
  await approveReviews(admin, "crs_a1");
  assert.match((await admin.get("/admin/courses/crs_a1")).text, /belongs to another course/);
  assert.ok(blocked(await publish(admin)));
});

test("publishing new exam settings while an exam is open changes neither its score, threshold nor deadline", async () => {
  const { env, admin, learner } = await released();
  await env.DB.batch([
    env.DB.prepare("UPDATE lessons SET is_required = 0 WHERE course_id = 'crs_a1'"),
    env.DB.prepare("UPDATE draft_lessons SET is_required = 0 WHERE course_id = 'crs_a1'"),
  ]);
  let r = await learner.post("/assessments/asm_a1_exam/start", {});
  const attemptId = r.location.split("/").pop();
  const before = await live(env, "SELECT * FROM attempts WHERE id = ?", attemptId);
  const answers = await correctResponses(env, attemptId);
  // Answer one question wrong: 95% would fail under a 100% threshold, passes under 80%.
  const layout = JSON.parse(before.layout_json);
  const wrong = layout.find((l) => Object.keys(answers).some((k) => k === `q[${l.q}]`));
  answers[`q[${wrong.q}]`] = "not-an-option";

  // The editor raises the threshold to 100%, cuts the time limit to 1 minute and shows full answers; reviewed and published.
  const a = await live(env, "SELECT * FROM draft_assessments WHERE id = 'asm_a1_exam'");
  r = await admin.post("/admin/assessments/asm_a1_exam", {
    title: a.title, instructions: a.instructions, kind: a.kind, status: a.status, passing_score: "100", time_limit_minutes: "1",
    max_attempts: String(a.max_attempts ?? ""), cooldown_minutes: String(a.cooldown_minutes), feedback_policy: "full",
    is_certification: "1", is_required: "1", shuffle_questions: a.shuffle_questions ? "1" : undefined, shuffle_options: a.shuffle_options ? "1" : undefined,
  });
  assert.match(r.location, /ok=saved/);
  await approveReviews(admin, "crs_a1");
  assert.ok(!blocked(await publish(admin)));
  assert.equal((await live(env, "SELECT passing_score FROM assessments WHERE id = 'asm_a1_exam'")).passing_score, 100, "live exam now requires 100%");

  const page = await learner.get(`/attempts/${attemptId}`);
  assert.match(page.text, new RegExp(`data-deadline="${before.deadline_at}"`), "deadline unchanged");
  r = await learner.post(`/attempts/${attemptId}/submit`, answers);
  const after = await live(env, "SELECT * FROM attempts WHERE id = ?", attemptId);
  assert.equal(after.status, "graded");
  assert.equal(after.deadline_at, before.deadline_at);
  assert.ok(after.score_pct < 100 && after.score_pct >= 80);
  assert.equal(after.passed, 1, "graded against the 80% threshold in force when the exam started");
  const result = await learner.get(`/attempts/${attemptId}`);
  const q = await live(env, "SELECT explanation FROM questions WHERE id = ?", wrong.q);
  assert.ok(q.explanation.length > 10);
  const esc = q.explanation.slice(0, 40).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  assert.ok(!result.text.includes(esc), "the exam's original feedback policy (correctness only) still applies: no explanations");
});

test("every published course field and relation is covered by the reviewed fingerprint", async () => {
  const { env, admin } = await released();
  const { courseContentHash } = await import("../../src/services/readiness.js");
  const base = await courseContentHash(env, "crs_a1");
  const changes = [
    "UPDATE draft_courses SET audience_json = '[\"agronomist\"]' WHERE id = 'crs_a1'",
    "UPDATE draft_courses SET topics_json = '[]' WHERE id = 'crs_a1'",
    "UPDATE draft_courses SET prerequisites_text = 'Synthetic change' WHERE id = 'crs_a1'",
    "UPDATE draft_courses SET slug = 'synthetic-new-slug' WHERE id = 'crs_a1'",
    "UPDATE draft_courses SET duration_minutes = duration_minutes + 1 WHERE id = 'crs_a1'",
    "UPDATE draft_courses SET thumbnail_url = 'https://media.example/x.png' WHERE id = 'crs_a1'",
    "DELETE FROM draft_course_instructors WHERE course_id = 'crs_a1'",
    "INSERT INTO draft_course_prerequisites (course_id, prerequisite_course_id, is_required) VALUES ('crs_a1', 'crs_a2', 1)",
    "UPDATE video_assets SET script_md = script_md || ' (edited)' WHERE id = 'vid_a1_data'",
    "INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES ('cap_x', 'vid_a1_data', 'fr-FR', 'Français', 'WEBVTT\n', 'reviewed', '2026-01-01')",
  ];
  let previous = base;
  for (const sql of changes) {
    await env.DB.prepare(sql).run();
    const next = await courseContentHash(env, "crs_a1");
    assert.notEqual(next, previous, `not fingerprinted: ${sql}`);
    previous = next;
  }
  // And the editor sees it as an unpublished change voiding the reviews.
  assert.match((await admin.get("/admin/courses/crs_a1")).text, /no longer applies/);
});

test("a draft edit between the readiness check and publication aborts the publication", async () => {
  const { env, admin } = await released();
  const { publishReadiness } = await import("../../src/services/readiness.js");
  const { publishDraft, DraftChangedError } = await import("../../src/services/drafts.js");
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Reviewed text." }));
  await approveReviews(admin, "crs_a1");
  const course = await live(env, "SELECT * FROM courses WHERE id = 'crs_a1'");
  const readiness = await publishReadiness(env, course);
  assert.ok(readiness.ok);
  // A concurrent save lands after the check.
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Unreviewed text." }));
  await assert.rejects(publishDraft(env, course, { hash: readiness.hash, version: readiness.version }), DraftChangedError);
  assert.notEqual((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Unreviewed text.", "nothing published");
  assert.equal((await live(env, "SELECT MAX(number) AS n FROM course_revisions WHERE course_id = 'crs_a1'")).n, 1, "no revision recorded");
});

test("an attempt completes the quiz lesson it started for, even if a revision moves the quiz", async () => {
  const { env, admin, learner } = await released();
  const r = await learner.post("/assessments/asm_a1_q1/start", {});
  const attemptId = r.location.split("/").pop();
  const answers = await correctResponses(env, attemptId);
  // The quiz moves from the module 1 quiz lesson to the summary lesson.
  await admin.post("/admin/lessons/les_a1_quiz1", await lessonForm(env, "les_a1_quiz1", { assessment_id: "", type: "text", body_md: "Synthetic replacement text." }));
  await admin.post("/admin/lessons/les_a1_summary", await lessonForm(env, "les_a1_summary", { type: "quiz", assessment_id: "asm_a1_q1" }));
  await approveReviews(admin, "crs_a1");
  assert.ok(!blocked(await publish(admin)));
  assert.equal((await live(env, "SELECT assessment_id FROM lessons WHERE id = 'les_a1_summary'")).assessment_id, "asm_a1_q1");
  await learner.post(`/attempts/${attemptId}/submit`, answers);
  const user = await live(env, "SELECT id FROM users WHERE email = 'learner@academy.test'");
  assert.equal((await live(env, "SELECT status FROM lesson_progress WHERE user_id = ? AND lesson_id = 'les_a1_quiz1'", user.id))?.status, "completed");
  assert.equal(await live(env, "SELECT status FROM lesson_progress WHERE user_id = ? AND lesson_id = 'les_a1_summary'", user.id), null, "the moved-to lesson is not completed");
});

test("a video shown by a released course cannot be changed in place", async () => {
  const { env, admin } = await released();
  const v = await live(env, "SELECT * FROM video_assets WHERE id = 'vid_a1_data'");
  let r = await admin.post("/admin/videos/vid_a1_data", { title: v.title, provider: "r2", status: "approved", duration_seconds: "60", mp4_url: "https://media.example/new.mp4", hls_url: "", script_md: "x" });
  assert.match(decodeURIComponent(r.location), /live in “Introduction to Artificial Intelligence in Agriculture”/);
  r = await admin.post("/admin/videos/vid_a1_data/captions", { locale: "en", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nReplaced" });
  assert.match(decodeURIComponent(r.location), /live in/);
  assert.equal(await live(env, "SELECT 1 FROM video_captions WHERE video_id = 'vid_a1_data'"), null);
  const after = await live(env, "SELECT * FROM video_assets WHERE id = 'vid_a1_data'");
  assert.deepEqual(after, v, "asset unchanged");
  // A video not linked by any released course's live lessons stays editable.
  r = await admin.post("/admin/videos", { title: "Replacement" });
  const id = r.location.split("/").pop().split("?")[0];
  r = await admin.post(`/admin/videos/${id}/captions`, { locale: "en", status: "reviewed", vtt: "WEBVTT\n" });
  assert.match(r.location, /ok=saved/);
});

test("an instructor profile shown by a released course cannot be changed in place", async () => {
  const { env, admin } = await released();
  const ins = await live(env, "SELECT i.* FROM instructors i JOIN course_instructors ci ON ci.instructor_id = i.id WHERE ci.course_id = 'crs_a1' LIMIT 1");
  assert.ok(ins, "A1 has an instructor");
  const r = await admin.post("/admin/instructors", { id: ins.id, name: "Renamed Synthetic", title: ins.title, bio: "Changed", status: "active" });
  assert.match(decodeURIComponent(r.location), /This profile is shown by/);
  assert.deepEqual(await live(env, "SELECT * FROM instructors WHERE id = ?", ins.id), ins);
  // Profile fields of linked instructors are part of the reviewed fingerprint.
  const { courseContentHash } = await import("../../src/services/readiness.js");
  const before = await courseContentHash(env, "crs_a1");
  await env.DB.prepare("UPDATE instructors SET bio = bio || ' x' WHERE id = ?").bind(ins.id).run();
  assert.notEqual(await courseContentHash(env, "crs_a1"), before);
});

test("taking a live course offline needs the publish permission", async () => {
  const { env } = await released();
  const editor = await registeredLearner(env, { email: "editor2@academy.test" });
  const eid = (await live(env, "SELECT id FROM users WHERE email = 'editor2@academy.test'")).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'content_editor', ?)").bind(eid, new Date().toISOString()).run();
  for (const status of ["draft", "review", "archived"]) {
    assert.equal((await editor.post("/admin/courses/crs_a1/status", { status })).status, 403, status);
  }
  assert.equal((await live(env, "SELECT status FROM courses WHERE id = 'crs_a1'")).status, "published");
});

test("an edit to a linked, not-yet-live video between readiness and publication aborts it", async () => {
  const { env, admin } = await released();
  const { publishReadiness } = await import("../../src/services/readiness.js");
  const { publishDraft, DraftChangedError } = await import("../../src/services/drafts.js");
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO video_assets (id, title, provider, status, created_at, updated_at) VALUES ('vid_new', 'Replacement', 'r2', 'planned', ?, ?)").bind(now, now).run();
  await admin.post("/admin/lessons/les_a1_summary", await lessonForm(env, "les_a1_summary", { video_id: "vid_new" }));
  await approveReviews(admin, "crs_a1");
  const course = await live(env, "SELECT * FROM courses WHERE id = 'crs_a1'");
  const readiness = await publishReadiness(env, course);
  assert.ok(readiness.ok, JSON.stringify(readiness.checks.filter((x) => !x.ok)));
  // The (not yet locked) asset changes after the check.
  await env.DB.prepare("UPDATE video_assets SET script_md = 'Unreviewed transcript' WHERE id = 'vid_new'").run();
  await assert.rejects(publishDraft(env, course, { hash: readiness.hash, version: readiness.version }), DraftChangedError);
  assert.notEqual((await live(env, "SELECT video_id FROM lessons WHERE id = 'les_a1_summary'")).video_id, "vid_new", "nothing published");
});

test("scheduling an update keeps the live revision published and enrollable", async () => {
  const { env, admin } = await released();
  const { runScheduled } = await import("../../src/services/jobs.js");
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Scheduled update text." }));
  await approveReviews(admin, "crs_a1");
  let r = await admin.post("/admin/courses/crs_a1/status", { status: "scheduled", scheduled_at: "2030-01-01T09:00" });
  assert.match(r.location, /ok=saved/);
  let c = await live(env, "SELECT status, scheduled_at FROM courses WHERE id = 'crs_a1'");
  assert.equal(c.status, "published", "live revision stays published");
  assert.ok(c.scheduled_at);
  const newcomer = await registeredLearner(env, { email: "newcomer@academy.test" });
  r = await newcomer.post(`/courses/${A1_SLUG}/enroll`, {});
  assert.equal(r.status, 303);
  assert.ok(await live(env, "SELECT 1 FROM enrollments e JOIN users u ON u.id = e.user_id WHERE u.email = 'newcomer@academy.test'"));
  // The time comes: the reviewed draft is published as a new revision.
  await env.DB.prepare("UPDATE courses SET scheduled_at = ? WHERE id = 'crs_a1'").bind(new Date(Date.now() - 60000).toISOString()).run();
  let report = await runScheduled(env, "*/15 * * * *");
  assert.equal(report.published, 1);
  assert.equal((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Scheduled update text.");
  // A scheduled update that no longer passes readiness is dropped; the live revision stays published.
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Unreviewed text." }));
  await env.DB.prepare("UPDATE courses SET scheduled_at = ? WHERE id = 'crs_a1'").bind(new Date(Date.now() - 60000).toISOString()).run();
  report = await runScheduled(env, "*/15 * * * *");
  assert.equal(report.publicationBlocked, 1);
  c = await live(env, "SELECT status, scheduled_at FROM courses WHERE id = 'crs_a1'");
  assert.equal(c.status, "published");
  assert.equal(c.scheduled_at, null);
  assert.equal((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Scheduled update text.");
});

/** Run `before` (once) just before the first statement whose SQL starts with `prefix` executes. */
function interleave(env, prefix, before) {
  const orig = env.DB;
  let done = false;
  const fire = async () => {
    if (!done) {
      done = true;
      await before(orig);
    }
  };
  const marked = new WeakSet();
  env.DB = new Proxy(orig, {
    get(target, prop) {
      if (prop === "batch") {
        return async (stmts) => {
          if (stmts.some((x) => marked.has(x))) await fire();
          return target.batch(stmts);
        };
      }
      if (prop !== "prepare") return typeof target[prop] === "function" ? target[prop].bind(target) : target[prop];
      return (sql) => {
        const stmt = target.prepare(sql);
        if (!sql.trimStart().startsWith(prefix)) return stmt;
        // Patch the real statement so batch() can still execute it.
        const patch = (st) => {
          marked.add(st);
          const { bind, run, first, all } = st;
          st.bind = (...a) => patch(bind.apply(st, a));
          st.run = async (...a) => (await fire(), run.apply(st, a));
          st.first = async (...a) => (await fire(), first.apply(st, a));
          st.all = async (...a) => (await fire(), all.apply(st, a));
          return st;
        };
        return patch(stmt);
      };
    },
  });
  return () => (env.DB = orig);
}

test("a status change is refused if the course was published after the permission check", async () => {
  const env = makeEnv();
  await registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
  const editor = await registeredLearner(env, { email: "editor3@academy.test" });
  const eid = (await live(env, "SELECT id FROM users WHERE email = 'editor3@academy.test'")).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'content_editor', ?)").bind(eid, new Date().toISOString()).run();
  assert.equal((await live(env, "SELECT status FROM courses WHERE id = 'crs_a1'")).status, "review");
  // A publisher publishes A1 between the editor's permission check and the write.
  const restore = interleave(env, "UPDATE courses SET status = ?, scheduled_at = ?", (db) => db.prepare("UPDATE courses SET status = 'published', published_at = ? WHERE id = 'crs_a1'").bind(new Date().toISOString()).run());
  const r = await editor.post("/admin/courses/crs_a1/status", { status: "draft" });
  restore();
  assert.match(decodeURIComponent(r.location), /changed while you were saving/);
  assert.equal((await live(env, "SELECT status FROM courses WHERE id = 'crs_a1'")).status, "published");
});

test("the scheduler skips a course whose schedule changed after it was selected", async () => {
  const { env, admin } = await released();
  const { runScheduled } = await import("../../src/services/jobs.js");
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Scheduled text." }));
  await approveReviews(admin, "crs_a1");
  await env.DB.prepare("UPDATE courses SET scheduled_at = ? WHERE id = 'crs_a1'").bind(new Date(Date.now() - 60000).toISOString()).run();
  // The course is archived after the scheduler selected it, before publication.
  let restore = interleave(env, "INSERT INTO course_revisions", (db) => db.prepare("UPDATE courses SET status = 'archived', scheduled_at = NULL WHERE id = 'crs_a1'").run());
  let report = await runScheduled(env, "*/15 * * * *");
  restore();
  assert.equal(report.published, 0);
  assert.equal((await live(env, "SELECT status FROM courses WHERE id = 'crs_a1'")).status, "archived", "not reopened");
  assert.notEqual((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Scheduled text.");
  // A failing re-check does not erase a schedule that replaced the selected one.
  await env.DB.prepare("UPDATE courses SET status = 'published', scheduled_at = ? WHERE id = 'crs_a1'").bind(new Date(Date.now() - 60000).toISOString()).run();
  await env.DB.prepare("UPDATE draft_lessons SET body_md = 'Unreviewed.' WHERE id = 'les_a1_welcome'").run();
  const replacement = "2031-01-01T00:00:00.000Z";
  restore = interleave(env, "UPDATE courses SET status = CASE", (db) => db.prepare("UPDATE courses SET scheduled_at = ? WHERE id = 'crs_a1'").bind(replacement).run());
  report = await runScheduled(env, "*/15 * * * *");
  restore();
  assert.equal(report.publicationBlocked, 0);
  assert.equal((await live(env, "SELECT scheduled_at FROM courses WHERE id = 'crs_a1'")).scheduled_at, replacement);
});

test("an archived course is taken down for the public but stays open to its learners", async () => {
  const { env, admin, learner } = await released();
  assert.equal((await admin.post("/admin/courses/crs_a1/status", { status: "archived" })).status, 303);
  assert.equal((await new Client(env).get(`/courses/${A1_SLUG}`)).status, 404, "anonymous");
  const stranger = await registeredLearner(env, { email: "stranger@academy.test" });
  assert.equal((await stranger.get(`/courses/${A1_SLUG}`)).status, 404, "not enrolled");
  assert.equal((await stranger.post(`/courses/${A1_SLUG}/enroll`, {})).status, 404, "no new enrollments");
  assert.equal((await learner.get(`/courses/${A1_SLUG}`)).status, 200, "enrolled learner keeps access");
  assert.equal((await learner.get(`/learn/${A1_SLUG}/welcome`)).status, 200);
  assert.equal((await admin.get(`/courses/${A1_SLUG}`)).status, 200, "staff");
});

test("manual publication does not override an archive made after the page was loaded", async () => {
  const { env, admin } = await released();
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Should not go live." }));
  await approveReviews(admin, "crs_a1");
  const restore = interleave(env, "INSERT INTO course_revisions", (db) => db.prepare("UPDATE courses SET status = 'archived' WHERE id = 'crs_a1'").run());
  const r = await publish(admin);
  restore();
  assert.match(decodeURIComponent(r.location), /changed while it was being published/);
  assert.equal((await live(env, "SELECT status FROM courses WHERE id = 'crs_a1'")).status, "archived");
  assert.notEqual((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Should not go live.");
});

test("caption, video and instructor locks hold even if the course is released mid-request", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
  const release = (db) => db.prepare("UPDATE courses SET status = 'published', published_at = ? WHERE id = 'crs_a1'").bind(new Date().toISOString()).run();
  // Not yet released: the separate lock check passes, then the course goes live before the write.
  let restore = interleave(env, "INSERT INTO video_captions", release);
  let r = await admin.post("/admin/videos/vid_a1_data/captions", { locale: "en", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nLate" });
  restore();
  assert.match(decodeURIComponent(r.location), /live in/);
  assert.equal(await live(env, "SELECT 1 FROM video_captions WHERE video_id = 'vid_a1_data'"), null);

  await env.DB.prepare("UPDATE courses SET status = 'review', published_at = NULL WHERE id = 'crs_a1'").run();
  const v = await live(env, "SELECT * FROM video_assets WHERE id = 'vid_a1_data'");
  restore = interleave(env, "UPDATE video_assets SET title", release);
  r = await admin.post("/admin/videos/vid_a1_data", { title: v.title, provider: "r2", status: "planned", mp4_url: "https://media.example/late.mp4", hls_url: "", script_md: "late" });
  restore();
  assert.match(decodeURIComponent(r.location), /live in/);
  assert.equal((await live(env, "SELECT mp4_url FROM video_assets WHERE id = 'vid_a1_data'")).mp4_url, v.mp4_url);

  await env.DB.prepare("UPDATE courses SET status = 'review', published_at = NULL WHERE id = 'crs_a1'").run();
  const ins = await live(env, "SELECT i.* FROM instructors i JOIN course_instructors ci ON ci.instructor_id = i.id WHERE ci.course_id = 'crs_a1' LIMIT 1");
  restore = interleave(env, "UPDATE instructors SET", release);
  r = await admin.post("/admin/instructors", { id: ins.id, name: "Late Rename", title: ins.title, bio: ins.bio, status: "active" });
  restore();
  assert.match(decodeURIComponent(r.location), /shown by a released course/);
  assert.equal((await live(env, "SELECT name FROM instructors WHERE id = ?", ins.id)).name, ins.name);
});

test("malformed interactive blocks are refused, and a stored one never breaks the lesson page", async () => {
  const { env, admin, learner } = await released();
  const r = await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { interactive_json: '{"kind":"reveal"}' }));
  assert.match(decodeURIComponent(r.location), /Interactive block must be JSON/);
  await env.DB.prepare(`UPDATE lessons SET interactive_json = '{"kind":"checklist","items":"oops"}' WHERE id = 'les_a1_welcome'`).run();
  assert.equal((await learner.get(`/learn/${A1_SLUG}/welcome`)).status, 200);
});

test("a scheduled update can be cancelled without publishing or taking the course offline", async () => {
  const { env, admin } = await released();
  await admin.post("/admin/lessons/les_a1_welcome", await lessonForm(env, "les_a1_welcome", { body_md: "Pending update." }));
  await approveReviews(admin, "crs_a1");
  await admin.post("/admin/courses/crs_a1/status", { status: "scheduled", scheduled_at: "2030-01-01T09:00" });
  assert.match((await admin.get("/admin/courses/crs_a1")).text, /Cancel scheduled publication/);
  const r = await admin.post("/admin/courses/crs_a1/unschedule", {});
  assert.match(r.location, /ok=saved/);
  const c = await live(env, "SELECT status, scheduled_at FROM courses WHERE id = 'crs_a1'");
  assert.equal(c.status, "published");
  assert.equal(c.scheduled_at, null);
  assert.notEqual((await live(env, "SELECT body_md FROM lessons WHERE id = 'les_a1_welcome'")).body_md, "Pending update.", "not published");
  const editor = await registeredLearner(env, { email: "editor4@academy.test" });
  const eid = (await live(env, "SELECT id FROM users WHERE email = 'editor4@academy.test'")).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'content_editor', ?)").bind(eid, new Date().toISOString()).run();
  assert.equal((await editor.post("/admin/courses/crs_a1/unschedule", {})).status, 403);
});

test("overlapping progress reports never move the resume position backwards", async () => {
  const { env, learner } = await released();
  const user = await live(env, "SELECT id FROM users WHERE email = 'learner@academy.test'");
  const newer = new Date().toISOString();
  const older = new Date(Date.now() - 60000).toISOString();
  await learner.postJson("/api/progress", { lessonId: "les_a1_welcome", position: 1, clientAt: new Date(Date.now() - 120000).toISOString() });
  // The newer report's write lands while the older report is in flight (after it read the row).
  const restore = interleave(env, "INSERT INTO lesson_progress", (db) =>
    db.prepare("UPDATE lesson_progress SET position_seconds = 100, client_updated_at = ? WHERE user_id = ? AND lesson_id = 'les_a1_welcome'").bind(newer, user.id).run(),
  );
  await learner.postJson("/api/progress", { lessonId: "les_a1_welcome", position: 10, clientAt: older });
  restore();
  const p = await live(env, "SELECT position_seconds, client_updated_at FROM lesson_progress WHERE user_id = ? AND lesson_id = 'les_a1_welcome'", user.id);
  assert.equal(p.position_seconds, 100);
  assert.equal(p.client_updated_at, newer);
});
