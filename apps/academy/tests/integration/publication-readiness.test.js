// Publication readiness: mandatory reviews bound to the reviewed content, the
// instructor-video policy, scheduled publication re-checks, and permissions.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, approveA1Videos, approveReviews, TEST_VTT } from "../helpers.js";
import { runScheduled } from "../../src/services/jobs.js";

async function setup() {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
  return { env, admin };
}
const status = async (env, id = "crs_a1") => (await env.DB.prepare("SELECT status FROM courses WHERE id = ?").bind(id).first()).status;
const publish = (admin, id = "crs_a1") => admin.post(`/admin/courses/${id}/status`, { status: "published" });
const blocked = (r) => /Readiness checks must pass/.test(decodeURIComponent(r.location || ""));

async function grant(env, email, role) {
  const u = await registeredLearner(env, { email });
  const id = (await env.DB.prepare("SELECT id FROM users WHERE email = ?").bind(email).first()).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, ?, ?)").bind(id, role, new Date().toISOString()).run();
  return u;
}

/** The full course form, as the edit page would submit it, with overrides. */
async function courseForm(env, id, overrides = {}) {
  const c = await env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(id).first();
  const ins = (await env.DB.prepare("SELECT instructor_id FROM course_instructors WHERE course_id = ?").bind(id).all()).results.map((r) => r.instructor_id);
  const flag = (v) => (v ? "1" : undefined);
  const body = {
    title: c.title, slug: c.slug, subtitle: c.subtitle, description: c.description, objectives: JSON.parse(c.objectives_json).join("\n"),
    program_id: c.program_id || "", level: c.level, duration_minutes: String(c.duration_minutes), source_locale: c.source_locale,
    planned_release_date: c.planned_release_date || "", sort_order: String(c.sort_order), thumbnail_url: c.thumbnail_url || "",
    prerequisites_text: c.prerequisites_text, audience: JSON.parse(c.audience_json), topics: JSON.parse(c.topics_json), instructors: ins,
    certificate_enabled: flag(c.certificate_enabled), require_all_lessons: flag(c.require_all_lessons), require_quizzes_pass: flag(c.require_quizzes_pass),
    passing_score: String(c.passing_score), content_review_note: c.content_review_note || "", video_requirement: c.video_requirement, video_waiver_reason: c.video_waiver_reason || "",
    ...overrides,
  };
  for (const k of Object.keys(body)) if (body[k] === undefined) delete body[k];
  return body;
}

test("mandatory reviews block publication until each is approved", async () => {
  const { env, admin } = await setup();
  await approveA1Videos(env, admin);
  let r = await admin.get("/admin/courses/crs_a1");
  assert.match(r.text, /Academic review of lesson content and learning objectives: not yet recorded/);
  assert.ok(blocked(await publish(admin)));

  // Decisions need confirmation, and change requests need notes.
  r = await admin.post("/admin/courses/crs_a1/reviews", { review_type: "academic", decision: "approved" });
  assert.match(decodeURIComponent(r.location), /Confirm that the review covered/);
  r = await admin.post("/admin/courses/crs_a1/reviews", { review_type: "academic", decision: "changes_requested", confirm: "1" });
  assert.match(decodeURIComponent(r.location), /Describe the changes/);
  r = await admin.post("/admin/courses/crs_a1/reviews", { review_type: "academic", decision: "changes_requested", confirm: "1", notes: "Clarify the NDVI example." });
  assert.match(r.location, /ok=saved/);

  await approveReviews(admin, "crs_a1"); // latest decision wins
  r = await admin.get("/admin/courses/crs_a1");
  assert.doesNotMatch(r.text, /❌/);
  assert.match(r.text, /approved by Synthetic Test Faculty/);
  assert.match(r.text, /changes requested · Synthetic Test Faculty|changes requested · Founder/, "history kept");
  r = await publish(admin);
  assert.equal(r.status, 303);
  assert.ok(!blocked(r));
  assert.equal(await status(env), "published");
  const audits = (await env.DB.prepare("SELECT action FROM audit_log WHERE action LIKE 'course.review.%'").all()).results.map((a) => a.action);
  assert.deepEqual(audits.sort(), ["course.review.approved", "course.review.approved", "course.review.approved", "course.review.changes_requested"]);
});

test("editing content after approval voids the approvals", async () => {
  const { env, admin } = await setup();
  await approveA1Videos(env, admin);
  await approveReviews(admin, "crs_a1");
  // An exam question changes after review.
  await env.DB.prepare("UPDATE questions SET prompt = prompt || ' (edited)' WHERE id = 'q_a1m1_1'").run();
  let r = await admin.get("/admin/courses/crs_a1");
  assert.match(r.text, /no longer applies — the content changed afterwards/);
  assert.ok(blocked(await publish(admin)));
  await approveReviews(admin, "crs_a1");
  assert.ok(!blocked(await publish(admin)));
});

test("required instructor videos must be approved, playable and captioned", async () => {
  const { env, admin } = await setup();
  await approveReviews(admin, "crs_a1");
  let r = await admin.get("/admin/courses/crs_a1");
  assert.match(r.text, /14 required lesson video\(s\) not approved and playable/);
  assert.ok(blocked(await publish(admin)));

  // Approve every video but give one only machine captions.
  await approveA1Videos(env, admin);
  const one = (await env.DB.prepare("SELECT video_id FROM lessons WHERE course_id='crs_a1' AND video_id IS NOT NULL ORDER BY sort_order LIMIT 1").first()).video_id;
  await admin.post(`/admin/videos/${one}/captions`, { locale: "en", status: "machine", vtt: TEST_VTT });
  r = await admin.get("/admin/courses/crs_a1");
  assert.match(r.text, /Required videos without reviewed captions/);
  assert.ok(blocked(await publish(admin)));
  await admin.post(`/admin/videos/${one}/captions`, { locale: "en", status: "reviewed", vtt: TEST_VTT });

  // An approved video always needs a playable URL.
  r = await admin.post(`/admin/videos/${one}`, { title: "x", provider: "r2", status: "approved", mp4_url: "", hls_url: "" });
  assert.match(decodeURIComponent(r.location), /needs an HLS or MP4 URL/);
  // Retiring a required video blocks publication again.
  await env.DB.prepare("UPDATE video_assets SET status = 'retired' WHERE id = ?").bind(one).run();
  assert.ok(blocked(await publish(admin)));
  await env.DB.prepare("UPDATE video_assets SET status = 'approved' WHERE id = ?").bind(one).run();
  assert.ok(!blocked(await publish(admin)));
});

test("an optional video policy needs a recorded reason and is audited", async () => {
  const { env, admin } = await setup();
  await approveReviews(admin, "crs_a1");
  let r = await admin.post("/admin/courses/crs_a1", await courseForm(env, "crs_a1", { video_requirement: "optional", video_waiver_reason: "" }));
  assert.match(decodeURIComponent(r.location), /Record why instructor video is optional/);
  assert.equal((await env.DB.prepare("SELECT video_requirement FROM courses WHERE id='crs_a1'").first()).video_requirement, "required");

  const reason = "Text-first launch on 29 Oct; Joshua videos follow after approval.";
  r = await admin.post("/admin/courses/crs_a1", await courseForm(env, "crs_a1", { video_requirement: "optional", video_waiver_reason: reason }));
  assert.match(r.location, /ok=saved/);
  r = await admin.get("/admin/courses/crs_a1");
  assert.match(r.text, /Instructor video optional for this course: Text-first launch/);
  assert.match(r.text, /14 lesson video\(s\) still in production/);
  const a = await env.DB.prepare("SELECT detail FROM audit_log WHERE action = 'course.video_policy'").first();
  assert.match(a.detail, /Text-first launch/);
  // Saving the course form changed no reviewed content, so approvals still apply.
  assert.ok(!blocked(await publish(admin)));
  assert.equal(await status(env), "published");
  // Learners see an honest notice instead of a video.
  const learner = await registeredLearner(env);
  await learner.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  r = await learner.get("/learn/introduction-to-ai-in-agriculture/welcome");
  assert.doesNotMatch(r.text, /<video/);
  assert.match(r.text, /in production/i);
});

test("scheduled publication re-checks readiness and returns unready courses to review", async () => {
  const { env, admin } = await setup();
  await approveA1Videos(env, admin);
  await approveReviews(admin, "crs_a1");
  let r = await admin.post("/admin/courses/crs_a1/status", { status: "scheduled", scheduled_at: "2026-10-29T15:00" });
  assert.equal(await status(env), "scheduled");
  // Content changes after scheduling; the schedule arrives.
  await env.DB.prepare("UPDATE lessons SET body_md = body_md || '\n\nEdited.' WHERE id = 'les_a1_welcome'").run();
  await env.DB.prepare("UPDATE courses SET scheduled_at = ? WHERE id = 'crs_a1'").bind(new Date(Date.now() - 60000).toISOString()).run();
  const report = await runScheduled(env, "*/15 * * * *");
  assert.equal(report.published, 0);
  assert.equal(report.publicationBlocked, 1);
  assert.equal(await status(env), "review", "back to review, still shown as upcoming");
  const audit = await env.DB.prepare("SELECT detail FROM audit_log WHERE action = 'course.schedule.blocked'").first();
  assert.match(audit.detail, /no longer applies/);
  const note = await env.DB.prepare("SELECT n.* FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = 'founder@academy.test' AND n.kind = 'admin'").first();
  assert.match(note.title, /Scheduled publication stopped/);
  r = await new Client(env).get("/courses/introduction-to-ai-in-agriculture");
  assert.match(r.text, /Opens Oct 29, 2026/);
  assert.doesNotMatch(r.text, /action="\/courses\/[^"]+\/enroll"/);
});

test("draft courses stay hidden and review courses stay upcoming", async () => {
  const { env } = await setup();
  const anon = new Client(env);
  let r = await anon.get("/courses");
  assert.match(r.text, /Introduction to Artificial Intelligence in Agriculture/);
  const draft = await env.DB.prepare("SELECT slug, title FROM courses WHERE status = 'draft' LIMIT 1").first();
  assert.doesNotMatch(r.text, new RegExp(draft.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  r = await anon.get(`/courses/${draft.slug}`);
  assert.equal(r.status, 404);
});

test("review and publish permissions are separate", async () => {
  const { env, admin } = await setup();
  const editor = await grant(env, "editor@academy.test", "content_editor");
  let r = await editor.post("/admin/courses/crs_a1/reviews", { review_type: "academic", decision: "approved", confirm: "1" });
  assert.equal(r.status, 403, "content editors cannot record reviews");
  r = await editor.get("/admin/courses/crs_a1");
  assert.match(r.text, /requires the reviewer permission/);

  const instructor = await grant(env, "faculty@academy.test", "instructor");
  r = await instructor.post("/admin/courses/crs_a1/reviews", { review_type: "academic", decision: "approved", confirm: "1" });
  assert.match(r.location, /ok=saved/);
  const rev = await env.DB.prepare("SELECT r.*, u.email FROM course_reviews r JOIN users u ON u.id = r.reviewer_id").first();
  assert.equal(rev.email, "faculty@academy.test");
  assert.match(rev.content_hash, /^[0-9a-f]{64}$/);
  await approveA1Videos(env, admin);
  await approveReviews(instructor, "crs_a1");
  r = await instructor.post("/admin/courses/crs_a1/status", { status: "published" });
  assert.equal(r.status, 403, "instructors review but cannot publish");
  assert.equal(await status(env), "review");
});
