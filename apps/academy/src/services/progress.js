// Enrollment, lesson progress and course completion.
import { newId, nowIso, clamp } from "../lib/util.js";
import { HttpError } from "../lib/http.js";
import { eventStmt, grantAchievement, notifyStmt } from "./activity.js";
import { queueEmail, deliverById } from "./email.js";
import { certificationExam, lessonCompletion, bestPassedAttempt, issueIfEligible } from "./certificates.js";

export async function getEnrollment(env, userId, courseId) {
  if (!userId) return null;
  return env.DB.prepare("SELECT * FROM enrollments WHERE user_id = ? AND course_id = ?").bind(userId, courseId).first();
}

export async function unmetRequiredPrerequisites(env, userId, courseId) {
  return (
    await env.DB.prepare(
      `SELECT c.title, c.slug FROM course_prerequisites cp JOIN courses c ON c.id = cp.prerequisite_course_id
        WHERE cp.course_id = ? AND cp.is_required = 1
          AND NOT EXISTS (SELECT 1 FROM enrollments e WHERE e.course_id = c.id AND e.user_id = ? AND e.status = 'completed')`,
    )
      .bind(courseId, userId)
      .all()
  ).results;
}

/** Enroll idempotently. The UNIQUE(user_id, course_id) constraint prevents duplicates. */
export async function enroll(c, course) {
  const { env, user } = c;
  if (course.status !== "published") throw new HttpError(409, "course_not_open");
  const unmet = await unmetRequiredPrerequisites(env, user.id, course.id);
  if (unmet.length) throw new HttpError(409, "prerequisites_unmet", "Prerequisites not completed", { prerequisites: unmet.map((u) => u.slug) });
  const existing = await getEnrollment(env, user.id, course.id);
  const now = nowIso();
  if (existing) {
    if (existing.status === "withdrawn") {
      await env.DB.prepare("UPDATE enrollments SET status = 'active', last_activity_at = ? WHERE id = ?").bind(now, existing.id).run();
      return { ...existing, status: "active", created: false };
    }
    return { ...existing, created: false };
  }
  const id = newId("enr_");
  const res = await env.DB.prepare(
    `INSERT INTO enrollments (id, user_id, course_id, status, progress_pct, enrolled_at, last_activity_at) VALUES (?,?,?,'active',0,?,?)
     ON CONFLICT(user_id, course_id) DO NOTHING`,
  )
    .bind(id, user.id, course.id, now, now)
    .run();
  if (!res.meta.changes) return { ...(await getEnrollment(env, user.id, course.id)), created: false };
  await env.DB.batch([
    eventStmt(env, { userId: user.id, event: "enrolled", courseId: course.id, locale: c.locale }),
    notifyStmt(env, user.id, { kind: "enrollment", title: course.title, url: `/learn/${course.slug}` }),
  ]);
  await grantAchievement(env, user.id, "first_enrollment");
  const mailId = await queueEmail(env, c.cfg, {
    user,
    template: "enrollment",
    vars: { course: course.title, url: `${c.cfg.origin}/learn/${course.slug}` },
  });
  c.defer(deliverById(env, c.cfg, mailId));
  return { id, user_id: user.id, course_id: course.id, status: "active", progress_pct: 0, created: true };
}

export async function withdraw(env, userId, courseId) {
  await env.DB.prepare("UPDATE enrollments SET status = 'withdrawn' WHERE user_id = ? AND course_id = ? AND status = 'active'").bind(userId, courseId).run();
}

export async function progressMap(env, userId, courseId) {
  const rows = (await env.DB.prepare("SELECT * FROM lesson_progress WHERE user_id = ? AND course_id = ?").bind(userId, courseId).all()).results;
  return new Map(rows.map((r) => [r.lesson_id, r]));
}

/**
 * Persist a progress report from the lesson page. Reports carry the client's
 * clock so that out-of-order or offline-queued updates never move a resume
 * position backwards; completion is sticky once reached.
 */
export async function recordProgress(c, lesson, report) {
  const { env, user } = c;
  const enrollment = await getEnrollment(env, user.id, lesson.course_id);
  if (!enrollment || enrollment.status === "withdrawn") throw new HttpError(403, "not_enrolled");
  const now = nowIso();
  const position = clamp(Number(report.position) || 0, 0, 24 * 3600);
  const duration = report.duration != null ? clamp(Number(report.duration) || 0, 0, 24 * 3600) : null;
  const scroll = clamp(Math.round(Number(report.scroll) || 0), 0, 100);
  const clientAt = typeof report.clientAt === "string" && /^\d{4}-\d\d-\d\dT/.test(report.clientAt) ? report.clientAt : now;
  let complete = report.complete === true || report.complete === "1" || report.complete === 1;
  // Video lessons complete automatically after 90% has been watched.
  if (!complete && lesson.type === "video" && duration && position / duration >= 0.9) complete = true;
  // Quiz lessons complete only through a graded attempt (see assessments).
  if (lesson.type === "quiz" && lesson.assessment_id) complete = false;

  const prev = await env.DB.prepare("SELECT status, client_updated_at FROM lesson_progress WHERE user_id = ? AND lesson_id = ?").bind(user.id, lesson.id).first();
  const stale = prev?.client_updated_at && prev.client_updated_at > clientAt;
  await env.DB.prepare(
    `INSERT INTO lesson_progress (user_id, lesson_id, course_id, status, position_seconds, duration_seconds, scroll_pct, started_at, completed_at, last_viewed_at, client_updated_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(user_id, lesson_id) DO UPDATE SET
       position_seconds = CASE WHEN ?12 THEN position_seconds ELSE excluded.position_seconds END,
       duration_seconds = COALESCE(excluded.duration_seconds, duration_seconds),
       scroll_pct = MAX(scroll_pct, excluded.scroll_pct),
       status = CASE WHEN status = 'completed' OR excluded.status = 'completed' THEN 'completed' ELSE 'started' END,
       completed_at = COALESCE(completed_at, excluded.completed_at),
       last_viewed_at = excluded.last_viewed_at,
       client_updated_at = CASE WHEN ?12 THEN client_updated_at ELSE excluded.client_updated_at END`,
  )
    .bind(user.id, lesson.id, lesson.course_id, complete ? "completed" : "started", position, duration, scroll, now, complete ? now : null, now, clientAt, stale ? 1 : 0)
    .run();
  await env.DB.prepare("UPDATE enrollments SET last_lesson_id = ?, last_activity_at = ? WHERE user_id = ? AND course_id = ?").bind(lesson.id, now, user.id, lesson.course_id).run();

  const newlyCompleted = complete && prev?.status !== "completed";
  if (!prev) c.defer(eventStmt(env, { userId: user.id, event: "lesson_started", courseId: lesson.course_id, lessonId: lesson.id, locale: c.locale }).run());
  if (newlyCompleted) {
    await eventStmt(env, { userId: user.id, event: "lesson_completed", courseId: lesson.course_id, lessonId: lesson.id, locale: c.locale }).run();
    await lessonAchievements(env, user.id);
  }
  const summary = await recomputeCourse(c, lesson.course_id);
  return { completed: complete || prev?.status === "completed", newlyCompleted, ...summary };
}

export async function markQuizLessonComplete(env, userId, lessonId, courseId) {
  const now = nowIso();
  await env.DB.prepare(
    `INSERT INTO lesson_progress (user_id, lesson_id, course_id, status, started_at, completed_at, last_viewed_at)
     VALUES (?,?,?,'completed',?,?,?)
     ON CONFLICT(user_id, lesson_id) DO UPDATE SET status='completed', completed_at=COALESCE(completed_at, excluded.completed_at), last_viewed_at=excluded.last_viewed_at`,
  )
    .bind(userId, lessonId, courseId, now, now, now)
    .run();
}

async function lessonAchievements(env, userId) {
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM lesson_progress WHERE user_id = ? AND status = 'completed'").bind(userId).first();
  if (n.n >= 1) await grantAchievement(env, userId, "first_lesson");
  if (n.n >= 10) await grantAchievement(env, userId, "ten_lessons");
}

/**
 * Recalculate a learner's course progress. The certification exam counts as
 * one unit of progress. On first completion the enrollment is closed, the
 * learner is notified, and a credential is issued when eligible.
 */
export async function recomputeCourse(c, courseId) {
  const { env, user } = c;
  const lessons = await lessonCompletion(env, user.id, courseId);
  const exam = await certificationExam(env, courseId);
  const examPassed = exam ? Boolean(await bestPassedAttempt(env, user.id, exam.id)) : false;
  const units = lessons.required + (exam ? 1 : 0);
  const done = lessons.done + (examPassed ? 1 : 0);
  const pct = units ? Math.round((done / units) * 100) : 0;
  const complete = units > 0 && done >= units;
  const enr = await getEnrollment(env, user.id, courseId);
  if (!enr) return { progressPct: pct, courseComplete: false };
  const now = nowIso();
  let certificate = null;
  if (complete && enr.status !== "completed") {
    await env.DB.prepare("UPDATE enrollments SET status='completed', completed_at=COALESCE(completed_at, ?), progress_pct=100, last_activity_at=? WHERE id=?").bind(now, now, enr.id).run();
    const course = await env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(courseId).first();
    await env.DB.batch([
      eventStmt(env, { userId: user.id, event: "course_completed", courseId, locale: c.locale }),
      notifyStmt(env, user.id, { kind: "course_complete", title: course.title, url: `/learn/${course.slug}` }),
    ]);
    await grantAchievement(env, user.id, "first_course", courseId);
    const mailId = await queueEmail(env, c.cfg, { user, template: "course_complete", vars: { course: course.title, url: `${c.cfg.origin}/dashboard` } });
    c.defer(deliverById(env, c.cfg, mailId));
    certificate = (await issueIfEligible(env, c.cfg, user, course, { defer: c.defer })).certificate;
  } else if (enr.progress_pct !== pct && enr.status !== "completed") {
    await env.DB.prepare("UPDATE enrollments SET progress_pct = ? WHERE id = ?").bind(pct, enr.id).run();
  }
  return { progressPct: complete ? 100 : pct, courseComplete: complete, certificate };
}
