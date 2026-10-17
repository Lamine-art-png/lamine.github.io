// Administrative analytics computed from recorded events and database rows.
// Nothing here is estimated or synthesized; empty data yields zeros/nulls.

export async function overviewMetrics(env, days = 30) {
  const since = new Date(Date.now() - days * 86400_000).toISOString();
  const one = (sql, ...b) => env.DB.prepare(sql).bind(...b).first();
  const [learners, active, newRegs, enrollments, completions, certs, attempts, feedback, pendingReview, openSupport] = await Promise.all([
    one("SELECT COUNT(*) AS n FROM users WHERE status = 'active'"),
    one("SELECT COUNT(DISTINCT user_id) AS n FROM learning_events WHERE created_at >= ? AND user_id IS NOT NULL AND event IN ('lesson_viewed','lesson_completed','quiz_started','exam_started','enrolled')", since),
    one("SELECT COUNT(*) AS n FROM users WHERE created_at >= ?", since),
    one("SELECT COUNT(*) AS n, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed FROM enrollments WHERE status != 'withdrawn'"),
    one("SELECT COUNT(*) AS n FROM enrollments WHERE completed_at >= ?", since),
    one("SELECT COUNT(*) AS n, SUM(CASE WHEN status='revoked' THEN 1 ELSE 0 END) AS revoked FROM certificates"),
    one(
      `SELECT COUNT(*) AS n, SUM(CASE WHEN t.passed = 1 THEN 1 ELSE 0 END) AS passed, AVG(t.score_pct) AS avg_score
         FROM attempts t JOIN assessments a ON a.id = t.assessment_id WHERE t.status = 'graded' AND a.kind = 'exam'`,
    ),
    one("SELECT COUNT(*) AS n, AVG(rating) AS avg FROM course_feedback"),
    one("SELECT COUNT(*) AS n FROM attempts WHERE status = 'pending_review'"),
    one("SELECT COUNT(*) AS n FROM support_requests WHERE status = 'open'"),
  ]);
  return {
    days,
    learners: learners.n,
    activeLearners: active.n,
    newRegistrations: newRegs.n,
    enrollments: enrollments.n,
    completedEnrollments: enrollments.completed || 0,
    completionRate: enrollments.n ? (enrollments.completed || 0) / enrollments.n : null,
    completionsInWindow: completions.n,
    certificates: certs.n,
    revokedCertificates: certs.revoked || 0,
    examAttempts: attempts.n,
    examPassRate: attempts.n ? (attempts.passed || 0) / attempts.n : null,
    avgExamScore: attempts.avg_score,
    feedbackCount: feedback.n,
    avgRating: feedback.avg,
    pendingReview: pendingReview.n,
    openSupport: openSupport.n,
  };
}

export async function courseMetrics(env) {
  return (
    await env.DB.prepare(
      `SELECT c.id, c.title, c.slug, c.status,
         (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.id AND e.status != 'withdrawn') AS enrolled,
         (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.id AND e.status = 'completed') AS completed,
         (SELECT AVG(progress_pct) FROM enrollments e WHERE e.course_id = c.id AND e.status = 'active') AS avg_progress,
         (SELECT COUNT(*) FROM attempts t JOIN assessments a ON a.id = t.assessment_id WHERE t.course_id = c.id AND a.kind = 'exam' AND t.status = 'graded') AS exam_attempts,
         (SELECT SUM(CASE WHEN t.passed = 1 THEN 1 ELSE 0 END) FROM attempts t JOIN assessments a ON a.id = t.assessment_id WHERE t.course_id = c.id AND a.kind = 'exam' AND t.status = 'graded') AS exam_passed,
         (SELECT AVG(t.score_pct) FROM attempts t JOIN assessments a ON a.id = t.assessment_id WHERE t.course_id = c.id AND a.kind = 'exam' AND t.status = 'graded') AS avg_score,
         (SELECT COUNT(*) FROM certificates x WHERE x.course_id = c.id AND x.status = 'active') AS certificates,
         (SELECT AVG(rating) FROM course_feedback f WHERE f.course_id = c.id) AS rating,
         (SELECT COUNT(*) FROM course_feedback f WHERE f.course_id = c.id) AS ratings
       FROM courses c WHERE c.status != 'draft' OR EXISTS (SELECT 1 FROM enrollments e WHERE e.course_id = c.id)
       ORDER BY enrolled DESC, c.sort_order`,
    ).all()
  ).results;
}

export async function lessonEngagement(env, courseId) {
  return (
    await env.DB.prepare(
      `SELECT l.id, l.title, l.type, l.sort_order, m.sort_order AS module_order,
         (SELECT COUNT(*) FROM lesson_progress p WHERE p.lesson_id = l.id) AS started,
         (SELECT COUNT(*) FROM lesson_progress p WHERE p.lesson_id = l.id AND p.status = 'completed') AS completed,
         (SELECT COUNT(*) FROM lesson_feedback f WHERE f.lesson_id = l.id) AS votes,
         (SELECT SUM(helpful) FROM lesson_feedback f WHERE f.lesson_id = l.id) AS helpful
       FROM lessons l JOIN modules m ON m.id = l.module_id WHERE l.course_id = ? ORDER BY m.sort_order, l.sort_order`,
    )
      .bind(courseId)
      .all()
  ).results;
}

export async function breakdowns(env, days = 90) {
  const since = new Date(Date.now() - days * 86400_000).toISOString();
  const [languages, countries, registrations, roles] = await Promise.all([
    env.DB.prepare("SELECT locale AS k, COUNT(*) AS n FROM users WHERE status = 'active' GROUP BY locale ORDER BY n DESC LIMIT 20").all(),
    // Country only from learners who opted in to sharing it.
    env.DB.prepare(
      `SELECT u.country AS k, COUNT(*) AS n FROM users u JOIN user_preferences p ON p.user_id = u.id
        WHERE u.status = 'active' AND p.share_country_analytics = 1 AND u.country IS NOT NULL GROUP BY u.country ORDER BY n DESC LIMIT 20`,
    ).all(),
    env.DB.prepare("SELECT substr(created_at, 1, 10) AS k, COUNT(*) AS n FROM users WHERE created_at >= ? GROUP BY k ORDER BY k").bind(since).all(),
    env.DB.prepare("SELECT COALESCE(professional_role, 'unspecified') AS k, COUNT(*) AS n FROM users WHERE status = 'active' GROUP BY k ORDER BY n DESC").all(),
  ]);
  return { languages: languages.results, countries: countries.results, registrations: registrations.results, roles: roles.results };
}
