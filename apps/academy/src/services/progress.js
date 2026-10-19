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
  // Quiz lessons complete only through a graded attempt (see assessments).
  if (lesson.type === "quiz" && lesson.assessment_id) complete = false;

  const prev = await env.DB.prepare("SELECT status, started_at, client_updated_at FROM lesson_progress WHERE user_id = ? AND lesson_id = ?").bind(user.id, lesson.id).first();
  // Video lessons with an approved video complete only by watching, measured
  // by the server from heartbeats (see recordWatchBeat). An explicit
  // "complete" or a reported position alone is never accepted for them.
  if (await watchRequired(env, lesson)) {
    const watch = await recordWatchBeat(env, user.id, lesson, { position, playing: report.playing, now });
    complete = watch.complete;
  }
  // Out-of-order reports are resolved inside the upsert (newest client time
  // wins), so two overlapping requests cannot move the position backwards.
  await env.DB.prepare(
    `INSERT INTO lesson_progress (user_id, lesson_id, course_id, status, position_seconds, duration_seconds, scroll_pct, started_at, completed_at, last_viewed_at, client_updated_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(user_id, lesson_id) DO UPDATE SET
       position_seconds = CASE WHEN client_updated_at > excluded.client_updated_at THEN position_seconds ELSE excluded.position_seconds END,
       duration_seconds = COALESCE(excluded.duration_seconds, duration_seconds),
       scroll_pct = MAX(scroll_pct, excluded.scroll_pct),
       status = CASE WHEN status = 'completed' OR excluded.status = 'completed' THEN 'completed' ELSE 'started' END,
       completed_at = COALESCE(completed_at, excluded.completed_at),
       last_viewed_at = excluded.last_viewed_at,
       client_updated_at = CASE WHEN client_updated_at > excluded.client_updated_at THEN client_updated_at ELSE excluded.client_updated_at END`,
  )
    .bind(user.id, lesson.id, lesson.course_id, complete ? "completed" : "started", position, duration, scroll, now, complete ? now : null, now, clientAt)
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

/** Whether a lesson completes only by watching its approved, playable video. */
export async function watchRequired(env, lesson) {
  if (lesson.type !== "video" || !lesson.video_id) return false;
  lesson.video ??= await env.DB.prepare("SELECT status, hls_url, mp4_url, duration_seconds FROM video_assets WHERE id = ?").bind(lesson.video_id).first();
  const v = lesson.video;
  // Approval requires a duration; without one watching cannot be measured (readiness blocks publication).
  return Boolean(v && v.status === "approved" && (v.hls_url || v.mp4_url) && Number(v.duration_seconds) > 0);
}

// ───────────── Server-measured watching ─────────────
//
// Trust boundary: the browser reports where playback is; the server decides
// how much of that could have been watched. Only the server clock is used.
// A heartbeat credits the span [previous position, this position] when the
// previous heartbeat said playback was running, it arrived 2–120 s earlier,
// and the advance is possible at up to MAX_RATE× speed (plus a margin for
// network latency). Jumps, seeks, rewinds, bursts of queued or replayed
// reports and interleaved sessions are not credited. Credited spans are
// merged; the lesson completes when they cover WATCH_SHARE of the video's
// server-known length. A scripted client that sends plausible heartbeats in
// real time for about a third of the video's length can still pass: the server
// cannot see the screen. That residual risk is accepted and documented.
export const MAX_RATE = 2;
export const WATCH_SHARE = 0.9;
// Network latency can shorten the server-measured interval between two
// heartbeats; honest 2× playback needs a margin of 10% plus one second.
const RATE_MARGIN = 1.1;
const JITTER_SECONDS = 1;
const MAX_GAP_SECONDS = 120;
export const MIN_GAP_SECONDS = 2;

/** Merge [start, end] spans; returns the merged list and its total length. */
export function mergeSegments(segments) {
  const sorted = segments.filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const [a, b] of sorted) {
    const last = out[out.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else out.push([a, b]);
  }
  return { segments: out, total: out.reduce((n, [a, b]) => n + (b - a), 0) };
}

/**
 * Pure credit rule for one heartbeat (exported for tests and documentation).
 * Regular beats (≥ MIN_GAP_SECONDS apart) may advance elapsed × MAX_RATE
 * plus a latency margin (10% + 1 s). A closing beat (pause, seek, end) that
 * arrives sooner gets no margin and ends the run, so rapid or alternating
 * beats can never credit more than 2.7× the server-measured time (beats
 * exactly 2 s apart); with the player's 5 s heartbeats the bound is 2.4×.
 */
export function creditFor(prev, { position, at, playing }) {
  if (!prev || !prev.playing) return null;
  const elapsed = (Date.parse(at) - Date.parse(prev.last_beat_at)) / 1000;
  if (!(elapsed > 0 && elapsed <= MAX_GAP_SECONDS)) return null;
  if (elapsed < MIN_GAP_SECONDS && playing) return null;
  const allowed = elapsed >= MIN_GAP_SECONDS ? elapsed * MAX_RATE * RATE_MARGIN + JITTER_SECONDS : elapsed * MAX_RATE;
  const advance = position - prev.last_position;
  if (advance <= 0 || advance > allowed) return null;
  return [prev.last_position, position];
}

export async function recordWatchBeat(env, userId, lesson, { position, playing, now }) {
  // Only the server-known length counts (approval requires it); a duration
  // reported by the browser is never used, so it cannot shorten the target.
  const total = Number(lesson.video?.duration_seconds) || 0;
  const pos = total ? Math.min(position, total) : position;
  const isPlaying = playing === true || playing === 1 || playing === "1";
  // Read, merge and write as a compare-and-swap on the beat counter: if an
  // overlapping heartbeat for the same learner and lesson wrote in between,
  // this one re-reads and merges again, so no credited span is ever lost.
  for (let attempt = 0; attempt < 5; attempt++) {
    const prev = await env.DB.prepare("SELECT * FROM video_watch WHERE user_id = ? AND lesson_id = ?").bind(userId, lesson.id).first();
    if (prev && Date.parse(now) < Date.parse(prev.last_beat_at)) {
      // An older heartbeat that lost the race to a newer one: dropped, never replaces the newer anchor.
      return { complete: total > 0 && prev.watched_seconds >= total * WATCH_SHARE, watched: prev.watched_seconds, total };
    }
    if (prev && prev.playing && isPlaying && (Date.parse(now) - Date.parse(prev.last_beat_at)) / 1000 < MIN_GAP_SECONDS) {
      // Too soon after the previous heartbeat: ignored; the run stays anchored there.
      return { complete: total > 0 && prev.watched_seconds >= total * WATCH_SHARE, watched: prev.watched_seconds, total };
    }
    const span = creditFor(prev, { position: pos, at: now, playing: isPlaying });
    const merged = mergeSegments([...JSON.parse(prev?.segments_json || "[]"), ...(span ? [span] : [])]);
    const rejected = prev && prev.playing && !span ? 1 : 0;
    const res = prev
      ? await env.DB.prepare(
          `UPDATE video_watch SET last_position = ?3, last_beat_at = ?4, playing = ?5, segments_json = ?6, watched_seconds = ?7, beats = beats + 1, rejected = rejected + ?8
            WHERE user_id = ?1 AND lesson_id = ?2 AND beats = ?9 AND last_beat_at <= ?4`,
        )
          .bind(userId, lesson.id, pos, now, isPlaying ? 1 : 0, JSON.stringify(merged.segments), merged.total, rejected, prev.beats)
          .run()
      : await env.DB.prepare(
          `INSERT INTO video_watch (user_id, lesson_id, last_position, last_beat_at, playing, segments_json, watched_seconds, beats, rejected, created_at)
           VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 1, 0, ?4) ON CONFLICT(user_id, lesson_id) DO NOTHING`,
        )
          .bind(userId, lesson.id, pos, now, isPlaying ? 1 : 0, JSON.stringify(merged.segments), merged.total)
          .run();
    if (res.meta.changes) return { complete: total > 0 && merged.total >= total * WATCH_SHARE, watched: merged.total, total };
  }
  // Persistent contention: this heartbeat is dropped (the next one continues the run).
  const cur = await env.DB.prepare("SELECT watched_seconds FROM video_watch WHERE user_id = ? AND lesson_id = ?").bind(userId, lesson.id).first();
  return { complete: total > 0 && (cur?.watched_seconds || 0) >= total * WATCH_SHARE, watched: cur?.watched_seconds || 0, total };
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
