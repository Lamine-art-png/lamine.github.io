// Publication readiness: the checks a course must pass before it can be
// published or scheduled, including mandatory reviews and approved media.
import { newId, nowIso, parseJson, sha256Hex } from "../lib/util.js";
import { auditStmt } from "../lib/security.js";
import { draftCourse, draftVersion } from "./drafts.js";
import { hasMedia, isStreamVideo } from "./stream.js";

/** Reviews every course needs, each recorded against the exact content reviewed. */
export const MANDATORY_REVIEWS = [
  { type: "academic", label: "Academic review of lesson content and learning objectives" },
  { type: "assessment", label: "Assessment review of quizzes, the exam bank and the passing standard" },
  { type: "accessibility", label: "Accessibility review (reading level, alternatives, captions)" },
];
export const REVIEW_TYPES = MANDATORY_REVIEWS.map((r) => r.type);
export const REVIEW_DECISIONS = ["approved", "changes_requested"];

const strip = (row, drop = ["created_at", "updated_at"]) => Object.fromEntries(Object.entries(row).filter(([k]) => !drop.includes(k)));

/**
 * Fingerprint of everything reviewers sign off on in the course draft (the
 * content that the next publication would make live): every course field,
 * instructors, prerequisites, modules, lessons, resources, assessments, draw
 * rules, questions, and the linked video assets and captions. Any edit after
 * an approval changes the fingerprint and voids that approval.
 */
/**
 * Why an assessment cannot draw its questions (no rules, or too few active
 * questions), or null. Rules draw in order and a question is drawn at most
 * once (drawQuestions), so earlier rules may use up questions a later rule
 * could also draw: each rule must still have enough left in the worst case.
 */
async function drawProblem(env, assessmentId) {
  const rules = (await env.DB.prepare("SELECT * FROM draft_assessment_rules WHERE assessment_id = ? ORDER BY sort_order").bind(assessmentId).all()).results;
  if (!rules.length) return "no question draw rules";
  let short = 0;
  const earlier = []; // { pool: Set, draw } of the rules already drawn
  for (const r of rules) {
    const pool = (await env.DB.prepare(`SELECT id FROM draft_questions WHERE bank_id = ? AND status = 'active' ${r.difficulty ? "AND difficulty = ?" : ""}`).bind(...(r.difficulty ? [r.bank_id, r.difficulty] : [r.bank_id])).all()).results.map((q) => q.id);
    // An earlier rule can take at most its own draw count, and only from the questions it shares with this pool.
    const shared = new Set(pool.filter((id) => earlier.some((e) => e.pool.has(id))));
    const taken = Math.min(shared.size, earlier.reduce((n, e) => n + Math.min(e.draw, pool.filter((id) => e.pool.has(id)).length), 0));
    if (pool.length - taken < r.draw_count) short++;
    earlier.push({ pool: new Set(pool), draw: r.draw_count });
  }
  return short ? `${short} draw rule(s) need more active questions (rules drawing from the same questions share them)` : null;
}

export async function courseContentHash(env, courseId) {
  const all = async (sql, ...args) => (await env.DB.prepare(sql).bind(...args).all()).results.map((r) => strip(r));
  // Every draft field and relation that publication copies live is included,
  // with the linked instructor profiles.
  const courseRow = await env.DB.prepare("SELECT * FROM draft_courses WHERE id = ?").bind(courseId).first();
  const course = courseRow ? strip(courseRow, ["updated_at", "updated_by"]) : null;
  const assessments = await all("SELECT * FROM draft_assessments WHERE course_id = ? ORDER BY id", courseId);
  const ids = assessments.map((a) => a.id);
  const rules = ids.length ? await all(`SELECT * FROM draft_assessment_rules WHERE assessment_id IN (${ids.map(() => "?").join(",")}) ORDER BY id`, ...ids) : [];
  const bankIds = [...new Set(rules.map((r) => r.bank_id))];
  const inBanks = (table, order = "id") =>
    bankIds.length ? all(`SELECT * FROM draft_${table} WHERE bank_id IN (${bankIds.map(() => "?").join(",")}) ORDER BY ${order}`, ...bankIds) : [];
  const lessons = await all("SELECT * FROM draft_lessons WHERE course_id = ? ORDER BY id", courseId);
  // Media the lessons link to: the asset record and its captions (content
  // fingerprinted). Replacing a video or caption voids earlier approvals.
  const videoIds = [...new Set(lessons.map((l) => l.video_id).filter(Boolean))];
  const inVideos = (sql) => (videoIds.length ? all(sql.replace("(?)", `(${videoIds.map(() => "?").join(",")})`), ...videoIds) : []);
  const videos = await inVideos("SELECT id, status, provider, provider_ref, hls_url, mp4_url, duration_seconds, poster_url, script_md FROM video_assets WHERE id IN (?) ORDER BY id");
  const captions = [];
  for (const { vtt, ...cap } of await inVideos("SELECT id, video_id, locale, label, status, vtt FROM video_captions WHERE video_id IN (?) ORDER BY id")) {
    captions.push({ ...cap, vtt: await sha256Hex(vtt || "") });
  }
  const doc = {
    course,
    instructors: await all(
      `SELECT ci.instructor_id, ci.sort_order, i.name, i.title, i.bio, i.avatar_url, i.is_ai_avatar, i.disclosure, i.status
         FROM draft_course_instructors ci LEFT JOIN instructors i ON i.id = ci.instructor_id WHERE ci.course_id = ? ORDER BY ci.instructor_id`,
      courseId,
    ),
    prerequisites: await all("SELECT prerequisite_course_id, is_required FROM draft_course_prerequisites WHERE course_id = ? ORDER BY prerequisite_course_id", courseId),
    videos,
    captions,
    modules: await all("SELECT * FROM draft_modules WHERE course_id = ? ORDER BY id", courseId),
    lessons,
    resources: await all("SELECT r.* FROM draft_lesson_resources r JOIN draft_lessons l ON l.id = r.lesson_id WHERE l.course_id = ? ORDER BY r.id", courseId),
    assessments,
    rules,
    cases: await inBanks("question_cases"),
    questions: await inBanks("questions"),
  };
  return sha256Hex(JSON.stringify(doc));
}

/** Latest decision per mandatory review type, and whether it still applies. */
export async function reviewState(env, courseId, hash = null) {
  const current = hash ?? (await courseContentHash(env, courseId));
  const rows = (
    await env.DB.prepare(
      `SELECT r.*, u.display_name AS reviewer_display FROM course_reviews r LEFT JOIN users u ON u.id = r.reviewer_id
        WHERE r.course_id = ? ORDER BY r.created_at DESC, r.rowid DESC`,
    )
      .bind(courseId)
      .all()
  ).results;
  return MANDATORY_REVIEWS.map((m) => {
    const latest = rows.find((r) => r.review_type === m.type) || null;
    let state = "pending";
    if (latest?.decision === "changes_requested") state = "changes_requested";
    else if (latest?.decision === "approved") state = latest.content_hash === current ? "approved" : "outdated";
    return { ...m, state, latest, history: rows.filter((r) => r.review_type === m.type) };
  });
}

export async function recordReview(env, { courseId, type, decision, notes, reviewerId, reviewerName }) {
  if (!REVIEW_TYPES.includes(type) || !REVIEW_DECISIONS.includes(decision)) throw new Error("invalid review");
  const hash = await courseContentHash(env, courseId);
  const id = newId("rev_");
  const now = nowIso();
  await env.DB.batch([
    env.DB.prepare(
      "INSERT INTO course_reviews (id, course_id, review_type, decision, reviewer_id, reviewer_name, notes, content_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
    ).bind(id, courseId, type, decision, reviewerId, reviewerName || null, notes || "", hash, now),
    auditStmt(env, reviewerId, `course.review.${decision}`, "course", courseId, { review_type: type, content_hash: hash, reviewer_name: reviewerName || null }),
  ]);
  return { id, hash };
}

const streamProtected = (l) =>
  l.stream_signed === 1 && Number(l.stream_anonymous) >= 400 && l.stream_downloads === "none" && Date.now() - Date.parse(l.stream_checked_at || 0) < 8 * 86400_000;
const playable = (v, env) => v.video_status === "approved" && hasMedia(v, env) && v.video_duration > 0;

/**
 * Checks that must pass before the course draft can be published or
 * scheduled. Content comes from the draft; status and video policy from the
 * live course record.
 */
export async function publishReadiness(env, liveCourse) {
  // The version is read before the fingerprint: publication binds to both.
  const version = await draftVersion(env);
  const course = (await draftCourse(env, liveCourse.id)) || liveCourse;
  const checks = [];
  const hash = await courseContentHash(env, course.id);
  const lessons = (
    await env.DB.prepare(
      `SELECT l.*, v.status AS video_status, v.provider, v.provider_ref, v.hls_url, v.mp4_url, v.duration_seconds AS video_duration, v.title AS video_title,
              sp.signed_required AS stream_signed, sp.anonymous_status AS stream_anonymous, sp.downloads AS stream_downloads, sp.checked_at AS stream_checked_at,
              (SELECT COUNT(*) FROM video_captions vc WHERE vc.video_id = l.video_id AND vc.status = 'reviewed'
                  AND (vc.locale = ? OR vc.locale LIKE ? || '-%')) AS reviewed_captions
         FROM draft_lessons l LEFT JOIN video_assets v ON v.id = l.video_id LEFT JOIN stream_protection sp ON sp.uid = v.provider_ref WHERE l.course_id = ?`,
    )
      .bind(course.source_locale || "en", (course.source_locale || "en").split("-")[0], course.id)
      .all()
  ).results;
  const ready = lessons.filter((l) => l.status === "ready");
  checks.push({ ok: ready.length > 0, label: `At least one ready lesson (${ready.length} ready of ${lessons.length})` });
  const emptyLessons = ready.filter((l) => !l.body_md.trim() && !(l.video_id && playable(l, env)) && l.type !== "quiz");
  checks.push({ ok: emptyLessons.length === 0, label: emptyLessons.length ? `Lessons without content: ${emptyLessons.map((l) => l.title).join(", ")}` : "Every ready lesson has instructional content" });

  // Instructional video. Video lessons always need their approved video. When
  // the course requires instructor video, every planned lesson video must be
  // approved, playable and captioned (reviewed captions in the source language).
  const videoRequired = course.video_requirement !== "optional";
  const needsVideo = ready.filter((l) => l.type === "video" || (videoRequired && l.video_id && l.is_required));
  const missingVideo = needsVideo.filter((l) => !l.video_id || !playable(l, env));
  const missingCaptions = needsVideo.filter((l) => l.video_id && playable(l, env) && !l.reviewed_captions);
  checks.push({
    ok: missingVideo.length === 0,
    label: missingVideo.length
      ? `${missingVideo.length} required lesson video(s) not approved and playable (URL and duration): ${missingVideo.map((l) => l.title).join(", ")}`
      : needsVideo.length
        ? `All ${needsVideo.length} required lesson videos are approved and playable`
        : "No lesson requires a video",
  });
  // Stream uploads must be verified private by the deploy pipeline: signed URLs
  // required, anonymous playback refused and no downloadable rendition.
  const exposed = needsVideo.filter((l) => l.video_id && playable(l, env) && isStreamVideo(l) && !streamProtected(l));
  checks.push({
    ok: exposed.length === 0,
    label: exposed.length
      ? `Videos without verified Stream protection (signed URLs, anonymous playback refused, no downloads): ${exposed.map((l) => l.title).join(", ")}`
      : "Stream videos verified private (signed URLs required, anonymous playback refused, downloads off)",
  });
  checks.push({
    ok: missingCaptions.length === 0,
    label: missingCaptions.length ? `Required videos without reviewed captions: ${missingCaptions.map((l) => l.title).join(", ")}` : "Required videos have reviewed captions",
  });
  if (!videoRequired) {
    const reason = String(course.video_waiver_reason || "").trim();
    checks.push({ ok: Boolean(reason), warn: true, label: reason ? `Instructor video optional for this course: ${reason}` : "Instructor video is marked optional but no reason is recorded" });
    const pending = ready.filter((l) => l.video_id && !playable(l, env));
    if (pending.length) checks.push({ ok: true, warn: true, label: `${pending.length} lesson video(s) still in production — learners see an “in production” notice` });
  }

  const brokenQuiz = ready.filter((l) => l.type === "quiz" && !l.assessment_id);
  checks.push({ ok: brokenQuiz.length === 0, label: brokenQuiz.length ? `Quiz lessons without an assessment: ${brokenQuiz.map((l) => l.title).join(", ")}` : "Quiz lessons are linked to assessments" });
  // Every linked assessment must be this course's, active, and able to draw its questions.
  const unusable = [];
  for (const l of ready.filter((x) => x.type === "quiz" && x.assessment_id)) {
    const a = await env.DB.prepare("SELECT * FROM draft_assessments WHERE id = ? AND course_id = ?").bind(l.assessment_id, course.id).first();
    const problem = !a ? "missing" : a.status !== "active" ? `assessment is ${a.status}` : await drawProblem(env, a.id);
    if (problem) unusable.push(`${l.title} (${problem})`);
  }
  checks.push({ ok: unusable.length === 0, label: unusable.length ? `Quiz lessons whose assessment learners cannot take: ${unusable.join(", ")}` : "Every linked quiz is active and can draw its questions" });
  // A bank is published with the course that owns it, so draws from another
  // course's (or an unassigned) bank would let one publication change another.
  const foreign = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM draft_assessment_rules r JOIN draft_assessments a ON a.id = r.assessment_id
       LEFT JOIN draft_question_banks b ON b.id = r.bank_id WHERE a.course_id = ? AND (b.course_id IS NULL OR b.course_id <> a.course_id)`,
  )
    .bind(course.id)
    .first();
  checks.push({ ok: !foreign.n, label: foreign.n ? `${foreign.n} draw rule(s) use a question bank that belongs to another course` : "Every draw rule uses this course's own question banks" });
  if (course.certificate_enabled) {
    const exam = await env.DB.prepare("SELECT * FROM draft_assessments WHERE course_id = ? AND kind = 'exam' AND is_certification = 1 AND status = 'active'").bind(course.id).first();
    checks.push({ ok: Boolean(exam), label: exam ? "Active certification exam" : "Certificates are enabled but there is no active certification exam" });
    if (exam) {
      const problem = await drawProblem(env, exam.id);
      checks.push({ ok: !problem, label: problem ? `Exam: ${problem}` : "Question banks can satisfy every draw rule" });
    }
  }
  checks.push({ ok: Boolean(course.description?.trim() && parseJson(course.objectives_json, []).length), label: "Description and learning objectives present" });

  const reviews = await reviewState(env, course.id, hash);
  for (const r of reviews) {
    const who = r.latest ? r.latest.reviewer_name || r.latest.reviewer_display || "a reviewer" : "";
    const label = {
      approved: `${r.label}: approved by ${who} on ${r.latest?.created_at.slice(0, 10)}`,
      outdated: `${r.label}: approval by ${who} no longer applies — the content changed afterwards`,
      changes_requested: `${r.label}: changes requested by ${who}`,
      pending: `${r.label}: not yet recorded`,
    }[r.state];
    checks.push({ ok: r.state === "approved", label, review: r.type });
  }
  checks.push({ ok: true, warn: Boolean(course.content_review_note), label: course.content_review_note ? `Review note: ${course.content_review_note}` : "No outstanding review note" });
  // The video policy the checks used: publication requires it to be unchanged.
  return { checks, ok: checks.every((x) => x.ok), reviews, hash, version, videoRequirement: course.video_requirement || "required" };
}
