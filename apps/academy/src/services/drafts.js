// Course drafts and publication. Editors change draft_* tables; learners read
// only the live tables, which change solely when a reviewed draft is
// published (or, for a course that has never been released, mirrored so its
// "upcoming" page stays current). Publication never deletes content learners
// depend on: removed lessons are hidden, modules, questions and assessments
// are retired, so progress, attempts and certificates keep their references.
import { newId, nowIso } from "../lib/util.js";
import { auditStmt } from "../lib/security.js";

/** Course columns that are content (edited in drafts). Status and policy stay on courses. */
export const COURSE_CONTENT = [
  "slug", "program_id", "title", "subtitle", "description", "level", "duration_minutes", "thumbnail_url", "source_locale", "objectives_json",
  "audience_json", "topics_json", "prerequisites_text", "planned_release_date", "certificate_enabled", "passing_score", "require_all_lessons",
  "require_quizzes_pass", "sort_order",
];
const COLS = {
  modules: ["id", "course_id", "title", "summary", "sort_order", "created_at", "updated_at"],
  lessons: ["id", "course_id", "module_id", "slug", "title", "type", "summary", "body_md", "interactive_json", "est_minutes", "video_id", "assessment_id", "is_required", "is_preview", "sort_order", "status", "created_at", "updated_at"],
  lesson_resources: ["id", "lesson_id", "title", "kind", "url", "file_key", "mime", "size_bytes", "sort_order", "created_at"],
  assessments: ["id", "course_id", "kind", "title", "instructions", "time_limit_seconds", "passing_score", "max_attempts", "cooldown_minutes", "shuffle_questions", "shuffle_options", "feedback_policy", "is_certification", "is_required", "status", "created_at", "updated_at"],
  question_banks: ["id", "course_id", "title", "description", "created_at", "updated_at"],
  question_cases: ["id", "bank_id", "title", "body_md", "created_at"],
  questions: ["id", "bank_id", "case_id", "lesson_id", "type", "difficulty", "prompt", "data_json", "answer_json", "explanation", "rubric", "grading", "points", "status", "created_at", "updated_at"],
  assessment_rules: ["id", "assessment_id", "bank_id", "difficulty", "draw_count", "sort_order"],
};

// Rows belonging to course ?1, in the draft (d) or live (l) tables.
const scope = (p) => ({
  modules: `course_id = ?1`,
  lessons: `course_id = ?1`,
  assessments: `course_id = ?1`,
  lesson_resources: `lesson_id IN (SELECT id FROM ${p}lessons WHERE course_id = ?1)`,
  question_banks: `(course_id = ?1 OR id IN (SELECT bank_id FROM ${p}assessment_rules WHERE assessment_id IN (SELECT id FROM ${p}assessments WHERE course_id = ?1)))`,
  question_cases: `bank_id IN (SELECT id FROM ${p}question_banks WHERE course_id = ?1 OR id IN (SELECT bank_id FROM ${p}assessment_rules WHERE assessment_id IN (SELECT id FROM ${p}assessments WHERE course_id = ?1)))`,
  questions: `bank_id IN (SELECT id FROM ${p}question_banks WHERE course_id = ?1 OR id IN (SELECT bank_id FROM ${p}assessment_rules WHERE assessment_id IN (SELECT id FROM ${p}assessments WHERE course_id = ?1)))`,
  assessment_rules: `assessment_id IN (SELECT id FROM ${p}assessments WHERE course_id = ?1)`,
});

export class DraftChangedError extends Error {
  constructor() {
    super("The draft or the course changed while it was being published; nothing was published.");
    this.code = "draft_changed";
  }
}

// Bind ?1 (course id) and, where used, ?2 (the current time).
const bindAll = (env, sql, courseId) => {
  const now = nowIso();
  return sql.map((s) => env.DB.prepare(s).bind(...(s.includes("?2") ? [courseId, now] : [courseId])));
};

function upsert(table, extraSet = "") {
  const cols = COLS[table];
  const set = cols.filter((c) => c !== "id").map((c) => `${c} = excluded.${c}`).concat(extraSet ? [extraSet] : []).join(", ");
  return `INSERT INTO ${table} (${cols.join(", ")}) SELECT ${cols.join(", ")} FROM draft_${table} WHERE ${scope("draft_")[table]} ON CONFLICT(id) DO UPDATE SET ${set}`;
}

/** Statements that make the live content of a course equal to its draft. */
export function draftToLiveStatements(env, courseId) {
  const d = scope("draft_");
  const sql = [
    `UPDATE courses SET (${COURSE_CONTENT.join(", ")}) = (SELECT ${COURSE_CONTENT.join(", ")} FROM draft_courses WHERE id = ?1), updated_at = ?2 WHERE id = ?1`,
    `DELETE FROM course_instructors WHERE course_id = ?1`,
    `INSERT INTO course_instructors (course_id, instructor_id, sort_order) SELECT course_id, instructor_id, sort_order FROM draft_course_instructors WHERE course_id = ?1`,
    `DELETE FROM course_prerequisites WHERE course_id = ?1`,
    `INSERT INTO course_prerequisites (course_id, prerequisite_course_id, is_required) SELECT course_id, prerequisite_course_id, is_required FROM draft_course_prerequisites WHERE course_id = ?1`,
    upsert("modules", "status = 'active'"),
    `UPDATE modules SET status = 'retired' WHERE course_id = ?1 AND id NOT IN (SELECT id FROM draft_modules WHERE ${d.modules})`,
    // Free every live slug first so renames and swaps cannot collide.
    `UPDATE lessons SET slug = '__rev_' || id WHERE course_id = ?1`,
    upsert("lessons"),
    `UPDATE lessons SET status = 'draft' WHERE course_id = ?1 AND id NOT IN (SELECT id FROM draft_lessons WHERE ${d.lessons})`,
    `DELETE FROM lesson_resources WHERE lesson_id IN (SELECT id FROM lessons WHERE course_id = ?1) AND id NOT IN (SELECT id FROM draft_lesson_resources WHERE ${d.lesson_resources})`,
    upsert("lesson_resources"),
    upsert("question_banks"),
    upsert("question_cases"),
    upsert("questions", "removed_at = NULL"),
    `UPDATE questions SET status = 'retired', removed_at = ?2 WHERE ${scope("")["questions"]} AND removed_at IS NULL AND id NOT IN (SELECT id FROM draft_questions WHERE ${d.questions})`,
    upsert("assessments", "removed_at = NULL"),
    `UPDATE assessments SET status = 'retired', removed_at = ?2 WHERE course_id = ?1 AND removed_at IS NULL AND id NOT IN (SELECT id FROM draft_assessments WHERE ${d.assessments})`,
    `DELETE FROM assessment_rules WHERE assessment_id IN (SELECT id FROM assessments WHERE course_id = ?1)`,
    `INSERT INTO assessment_rules (${COLS.assessment_rules.join(", ")}) SELECT ${COLS.assessment_rules.join(", ")} FROM draft_assessment_rules WHERE ${d.assessment_rules}`,
  ];
  return bindAll(env, sql, courseId);
}

/** Statements that reset a course's draft to its live content (discarding unpublished edits). */
export function liveToDraftStatements(env, courseId) {
  const l = scope("");
  const d = scope("draft_");
  const out = [];
  // Delete draft rows (children first), then copy the visible live content.
  for (const t of ["assessment_rules", "questions", "question_cases", "lesson_resources", "lessons", "modules", "assessments", "question_banks"]) out.push(`DELETE FROM draft_${t} WHERE ${d[t]}`);
  out.push(`DELETE FROM draft_course_instructors WHERE course_id = ?1`, `DELETE FROM draft_course_prerequisites WHERE course_id = ?1`);
  out.push(`UPDATE draft_courses SET (${COURSE_CONTENT.join(", ")}) = (SELECT ${COURSE_CONTENT.join(", ")} FROM courses WHERE id = ?1), updated_at = ?2 WHERE id = ?1`);
  out.push(`INSERT INTO draft_course_instructors SELECT course_id, instructor_id, sort_order FROM course_instructors WHERE course_id = ?1`);
  out.push(`INSERT INTO draft_course_prerequisites SELECT course_id, prerequisite_course_id, is_required FROM course_prerequisites WHERE course_id = ?1`);
  const copy = (t, extra = "") => `INSERT INTO draft_${t} (${COLS[t].join(", ")}) SELECT ${COLS[t].join(", ")} FROM ${t} WHERE ${l[t]}${extra}`;
  out.push(copy("modules", " AND status = 'active'"), copy("lessons", " AND slug NOT LIKE '\\_\\_rev\\_%' ESCAPE '\\'"), copy("lesson_resources"), copy("assessments", " AND removed_at IS NULL"));
  out.push(copy("question_banks"), copy("question_cases"), copy("questions", " AND removed_at IS NULL"), copy("assessment_rules"));
  return bindAll(env, out, courseId);
}

/** The course as editors see it: live status and policy with draft content. */
export async function draftCourse(env, courseId) {
  const live = await env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(courseId).first();
  if (!live) return null;
  const draft = await env.DB.prepare("SELECT * FROM draft_courses WHERE id = ?").bind(courseId).first();
  return { ...live, ...(draft || {}), status: live.status, updated_at: draft?.updated_at || live.updated_at };
}

export async function latestRevision(env, courseId) {
  return env.DB.prepare("SELECT * FROM course_revisions WHERE course_id = ? ORDER BY number DESC LIMIT 1").bind(courseId).first();
}

/**
 * After a draft edit: a course that has never been released has no learners,
 * so its live copy (shown as "upcoming") follows the draft. Released courses
 * change only through publication.
 */
export async function draftChanged(env, courseId) {
  if (!courseId) return;
  const course = await env.DB.prepare("SELECT published_at FROM courses WHERE id = ?").bind(courseId).first();
  if (course && !course.published_at) await env.DB.batch(draftToLiveStatements(env, courseId));
}

/** Delete stored resource files that neither the live course nor any draft references any more. */
export async function pruneFiles(env, keys) {
  if (!env.FILES) return;
  for (const key of new Set(keys.filter(Boolean))) {
    const used = await env.DB.prepare("SELECT 1 FROM lesson_resources WHERE file_key = ?1 UNION ALL SELECT 1 FROM draft_lesson_resources WHERE file_key = ?1").bind(key).first();
    if (!used) await env.FILES.delete(key);
  }
}

/** The global draft version; read it before fingerprinting a draft for publication. */
export async function draftVersion(env) {
  return (await env.DB.prepare("SELECT version FROM draft_state WHERE id = 1").first())?.version ?? 0;
}

/**
 * Publish the draft: copy it live, record the revision and the status,
 * atomically. `hash` must be the fingerprint taken at draft version
 * `version`; with `expect` ({status, scheduled_at}) the course row must also
 * still be in that state (the scheduler's due row). If anything changed, the
 * revision insert (first in the batch) gets a NULL hash, violates NOT NULL
 * and the whole batch rolls back.
 */
export async function publishDraft(env, course, { actorId = null, hash, version, by = "editor", expect = null } = {}) {
  if (!hash || !Number.isInteger(version)) throw new Error("publishDraft needs the reviewed hash and the draft version it was taken at");
  const before = (await env.DB.prepare("SELECT r.file_key FROM lesson_resources r JOIN lessons l ON l.id = r.lesson_id WHERE l.course_id = ? AND r.file_key IS NOT NULL").bind(course.id).all()).results;
  const last = await latestRevision(env, course.id);
  const number = (last?.number || 0) + 1;
  const now = nowIso();
  const counts = await env.DB.prepare(
    `SELECT (SELECT COUNT(*) FROM draft_lessons WHERE course_id = ?1 AND status = 'ready') AS lessons,
            (SELECT COUNT(*) FROM draft_assessments WHERE course_id = ?1 AND status = 'active') AS assessments`,
  )
    .bind(course.id)
    .first();
  try {
    await env.DB.batch([
      env.DB.prepare(
        `INSERT INTO course_revisions (id, course_id, number, content_hash, published_by, published_at, summary_json)
         VALUES (?1, ?2, ?3, (SELECT ?4 FROM draft_state WHERE id = 1 AND version = ?5
                               AND (?8 IS NULL OR EXISTS (SELECT 1 FROM courses WHERE id = ?2 AND status = ?8 AND scheduled_at IS ?9))), ?6, ?7, ?10)`,
      ).bind(newId("rev_"), course.id, number, hash, version, actorId, now, expect?.status ?? null, expect?.scheduled_at ?? null, JSON.stringify({ ...counts, by })),
      ...draftToLiveStatements(env, course.id),
      env.DB.prepare("UPDATE courses SET status = 'published', scheduled_at = NULL, published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?").bind(now, now, course.id),
      auditStmt(env, actorId, "course.revision.published", "course", course.id, { number, content_hash: hash, by }),
    ]);
  } catch (e) {
    if (/NOT NULL/i.test(String(e?.message))) throw new DraftChangedError();
    throw e;
  }
  await pruneFiles(env, before.map((r) => r.file_key));
  return number;
}
