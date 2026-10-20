// Rule-based personalization. Recommendations come only from the learner's own
// recorded activity and profile; no external AI service is involved.
import { listCourses, localize } from "./content.js";

const ROLE_TO_PATH_ROLE = {
  grower: "grower", operator: "operator", farm_manager: "farm_manager", agronomist: "agronomist", advisor: "agronomist",
  student: "student", researcher: "student", developer: "developer", other: "student",
};

/** Courses to take next, with a reason key for each. */
export async function recommendCourses(env, user, locale, limit = 3) {
  const enrolled = new Set(
    (await env.DB.prepare("SELECT course_id FROM enrollments WHERE user_id = ? AND status != 'withdrawn'").bind(user.id).all()).results.map((r) => r.course_id),
  );
  const completed = new Set(
    (await env.DB.prepare("SELECT course_id FROM enrollments WHERE user_id = ? AND status = 'completed'").bind(user.id).all()).results.map((r) => r.course_id),
  );
  const prereqs = (await env.DB.prepare("SELECT course_id, prerequisite_course_id, is_required FROM course_prerequisites").all()).results;
  const courses = await listCourses(env, locale, { includeUpcoming: false });
  const scores = new Map();
  const reasons = new Map();
  const bump = (id, s, reason) => {
    scores.set(id, (scores.get(id) || 0) + s);
    if (!reasons.has(id)) reasons.set(id, reason);
  };
  // 1. Courses that follow ones the learner completed.
  for (const p of prereqs) if (completed.has(p.prerequisite_course_id)) bump(p.course_id, 5, "rec.reason.next_step");
  // 2. The learner's role-based learning path.
  const role = ROLE_TO_PATH_ROLE[user.professional_role];
  if (role) {
    const pathCourses = (
      await env.DB.prepare("SELECT lpc.course_id, lpc.sort_order FROM learning_paths lp JOIN learning_path_courses lpc ON lpc.path_id = lp.id WHERE lp.role = ? AND lp.status = 'published'").bind(role).all()
    ).results;
    for (const pc of pathCourses) bump(pc.course_id, 4 - Math.min(3, pc.sort_order * 0.3), "rec.reason.your_path");
  }
  // 3. Same program as courses in progress.
  const programs = new Set(courses.filter((c) => enrolled.has(c.id)).map((c) => c.program_id));
  for (const c of courses) if (programs.has(c.program_id)) bump(c.id, 2, "rec.reason.same_program");
  // 4. Foundations for newcomers.
  for (const c of courses) if (c.level === "beginner") bump(c.id, enrolled.size ? 0.5 : 1.5, "rec.reason.beginner");

  const blocked = (id) => prereqs.some((p) => p.course_id === id && p.is_required && !completed.has(p.prerequisite_course_id));
  return courses
    .filter((c) => !enrolled.has(c.id) && !blocked(c.id))
    .map((c) => ({ course: c, score: scores.get(c.id) || 0, reason: reasons.get(c.id) || "rec.reason.popular" }))
    .sort((a, b) => b.score - a.score || a.course.sort_order - b.course.sort_order)
    .slice(0, limit);
}

/** Lessons to revisit, derived from incorrect answers in graded attempts. */
export async function reviewSuggestions(env, userId, locale, limit = 5) {
  const rows = (
    await env.DB.prepare(
      `SELECT l.id, l.slug, l.title, c.slug AS course_slug, c.title AS course_title, COUNT(*) AS misses, MAX(t.graded_at) AS last_seen
         FROM attempt_answers aa
         JOIN attempts t ON t.id = aa.attempt_id
         JOIN questions q ON q.id = aa.question_id
         JOIN lessons l ON l.id = q.lesson_id
         JOIN courses c ON c.id = l.course_id
        WHERE t.user_id = ? AND t.status = 'graded' AND aa.is_correct = 0
          AND t.graded_at > ?
        GROUP BY l.id ORDER BY misses DESC, last_seen DESC LIMIT ?`,
    )
      .bind(userId, new Date(Date.now() - 60 * 86400_000).toISOString(), limit)
      .all()
  ).results;
  await localize(env, "lesson", rows, ["title"], locale);
  return rows;
}
