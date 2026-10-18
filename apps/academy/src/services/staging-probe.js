// Staging only: a small synthetic course the staging integration test enrolls
// in, so the complete learner write path (enrollment, progress, lesson
// completion, a certification attempt, certificate issuance and verification)
// runs on every staging deploy, whatever the state of the real courses.
// Created through the normal draft → revision publication path. Never
// reachable outside staging (see pages/public.js stagingProbeCourse).
import { nowIso } from "../lib/util.js";
import { publishDraft } from "./drafts.js";
import { courseContentHash } from "./readiness.js";

export const PROBE = {
  courseId: "crs_staging_probe",
  slug: "staging-write-path-probe",
  lessonSlug: "probe-lesson",
  assessmentId: "asm_staging_probe_exam",
  questionId: "q_staging_probe_1",
  correctOption: "o1",
};

export async function ensureProbeCourse(env) {
  const existing = await env.DB.prepare("SELECT status FROM courses WHERE id = ?").bind(PROBE.courseId).first();
  if (existing?.status === "published") return PROBE;
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
  // The synthetic course is not reviewed; it is published directly as its first revision.
  await publishDraft(env, { id: PROBE.courseId }, { hash: await courseContentHash(env, PROBE.courseId), by: "staging-probe" });
  return PROBE;
}
