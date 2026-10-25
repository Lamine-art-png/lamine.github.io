// Staging only: a small synthetic course the staging integration test enrolls
// in, so the complete learner write path (enrollment, progress, lesson
// completion, a certification attempt, certificate issuance and verification)
// runs on every staging deploy, whatever the state of the real courses.
// Created through the normal draft → revision publication path. Never
// reachable outside staging (see pages/staging.js).
import { newId, nowIso } from "../lib/util.js";
import { publishDraft, draftVersion } from "./drafts.js";
import { courseContentHash } from "./readiness.js";

export const PROBE = {
  courseId: "crs_staging_probe",
  slug: "staging-write-path-probe",
  lessonSlug: "probe-lesson",
  videoLessonSlug: "probe-protected-video",
  assessmentId: "asm_staging_probe_exam",
  questionId: "q_staging_probe_1",
  correctOption: "o1",
};

/**
 * Ensure the probe exists, change its draft (a per-run marker in the lesson)
 * and publish that change as a new revision, so every staging run exercises
 * the draft → reviewed-hash → revision publication path end to end.
 */
export async function ensureProbeCourse(env) {
  const now = nowIso();
  const objectives = JSON.stringify(["Exercise the staging write path"]);
  await env.DB.batch(
    [
      [
        `INSERT OR IGNORE INTO courses (id, slug, title, subtitle, description, level, source_locale, objectives_json, status, certificate_enabled, passing_score,
           require_all_lessons, require_quizzes_pass, sort_order, video_requirement, video_waiver_reason, created_at, updated_at)
         VALUES (?1, ?2, 'Staging write-path probe (synthetic)', 'Synthetic course used by automated staging checks.', 'Synthetic course used by automated staging checks.',
           'beginner', 'en', ?3, 'draft', 1, 80, 1, 0, 999, 'optional', 'Synthetic staging probe without video', ?4, ?4)`,
        PROBE.courseId, PROBE.slug, objectives, now,
      ],
      [
        `INSERT OR IGNORE INTO draft_courses (id, slug, title, subtitle, description, level, source_locale, objectives_json, certificate_enabled, passing_score,
           require_all_lessons, require_quizzes_pass, sort_order, updated_at)
         SELECT id, slug, title, subtitle, description, level, source_locale, objectives_json, certificate_enabled, passing_score, require_all_lessons, require_quizzes_pass, sort_order, updated_at
           FROM courses WHERE id = ?1`,
        PROBE.courseId,
      ],
      ["INSERT OR IGNORE INTO draft_modules (id, course_id, title, sort_order, created_at, updated_at) VALUES ('mod_staging_probe', ?1, 'Probe module', 1, ?2, ?2)", PROBE.courseId, now],
      [
        `INSERT OR IGNORE INTO draft_lessons (id, course_id, module_id, slug, title, type, body_md, est_minutes, status, is_required, sort_order, created_at, updated_at)
         VALUES ('les_staging_probe', ?1, 'mod_staging_probe', ?2, 'Probe lesson', 'text', 'Synthetic lesson text for staging checks.', 1, 'ready', 1, 1, ?3, ?3)`,
        PROBE.courseId, PROBE.lessonSlug, now,
      ],
      // Optional lesson playing one of the real, verified-protected A1 uploads
      // through its own staging-only asset record: the protected-playback path
      // is tested end to end without approving anything in Course A1.
      [
        `INSERT OR IGNORE INTO video_assets (id, title, provider, status, created_at, updated_at)
         VALUES ('vid_staging_probe_stream', 'Staging probe: protected Stream playback (synthetic)', 'stream', 'planned', ?1, ?1)`,
        now,
      ],
      [
        `INSERT OR IGNORE INTO draft_lessons (id, course_id, module_id, slug, title, type, body_md, est_minutes, video_id, status, is_required, sort_order, created_at, updated_at)
         VALUES ('les_staging_probe_video', ?1, 'mod_staging_probe', ?2, 'Probe protected video', 'video', 'Synthetic lesson for the protected playback check.', 2, 'vid_staging_probe_stream', 'ready', 0, 2, ?3, ?3)`,
        PROBE.courseId, PROBE.videoLessonSlug, now,
      ],
      ["INSERT OR IGNORE INTO draft_question_banks (id, course_id, title, created_at, updated_at) VALUES ('bnk_staging_probe', ?1, 'Probe bank', ?2, ?2)", PROBE.courseId, now],
      [
        `INSERT OR IGNORE INTO draft_questions (id, bank_id, type, difficulty, prompt, data_json, answer_json, explanation, grading, points, status, created_at, updated_at)
         VALUES (?1, 'bnk_staging_probe', 'single', 'easy', 'Synthetic probe question', ?2, ?3, '', 'auto', 1, 'active', ?4, ?4)`,
        PROBE.questionId,
        JSON.stringify({ options: [{ id: "o1", text: "Correct (synthetic)" }, { id: "o2", text: "Incorrect (synthetic)" }] }),
        JSON.stringify({ correct: [PROBE.correctOption] }),
        now,
      ],
      [
        `INSERT OR IGNORE INTO draft_assessments (id, course_id, kind, title, passing_score, max_attempts, cooldown_minutes, shuffle_questions, shuffle_options, feedback_policy,
           is_certification, is_required, status, created_at, updated_at)
         VALUES (?1, ?2, 'exam', 'Probe exam', 80, NULL, 0, 0, 0, 'full', 1, 1, 'active', ?3, ?3)`,
        PROBE.assessmentId, PROBE.courseId, now,
      ],
      ["INSERT OR IGNORE INTO draft_assessment_rules (id, assessment_id, bank_id, draw_count, sort_order) VALUES ('rul_staging_probe', ?1, 'bnk_staging_probe', 1, 1)", PROBE.assessmentId],
    ].map(([sql, ...args]) => env.DB.prepare(sql).bind(...args)),
  );
  // Point the probe asset at an upload the deploy pipeline verified private
  // within the last day; without one the playback check reports it is skipped.
  const verified = await env.DB.prepare(
    `SELECT uid, duration_seconds FROM stream_protection WHERE signed_required = 1 AND anonymous_status >= 400 AND downloads = 'none'
       AND duration_seconds > 0 AND checked_at > ? ORDER BY title LIMIT 1`,
  )
    .bind(new Date(Date.now() - 86400_000).toISOString())
    .first();
  await env.DB.prepare(
    `UPDATE video_assets SET provider_ref = ?1, duration_seconds = ?2, status = CASE WHEN ?1 IS NULL THEN 'planned' ELSE 'approved' END, updated_at = ?3
      WHERE id = 'vid_staging_probe_stream' AND (COALESCE(provider_ref, '') <> COALESCE(?1, '') OR COALESCE(duration_seconds, 0) <> COALESCE(?2, 0))`,
  )
    .bind(verified?.uid ?? null, verified?.duration_seconds ?? null, now)
    .run();
  const marker = `probe-${newId("").toLowerCase()}`;
  await env.DB.prepare("UPDATE draft_lessons SET body_md = ?, updated_at = ? WHERE id = 'les_staging_probe'")
    .bind(`Synthetic lesson text for staging checks.\n\nRun marker: ${marker}`, now)
    .run();
  // The synthetic course is not reviewed; each run publishes its draft directly as a new revision.
  const version = await draftVersion(env);
  const revision = await publishDraft(env, { id: PROBE.courseId }, { hash: await courseContentHash(env, PROBE.courseId), version, by: "staging-probe" });
  return { ...PROBE, revision, marker, protectedVideo: Boolean(verified) };
}
