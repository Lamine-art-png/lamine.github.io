// Assessment engine. Question selection, option order, timing and scoring all
// happen on the server. Answer keys (questions.answer_json) never leave this
// module except in post-submission feedback permitted by the policy.
import { newId, nowIso, addSeconds, parseJson, shuffle } from "../lib/util.js";
import { HttpError } from "../lib/http.js";
import { localize } from "./content.js";
import { eventStmt, grantAchievement } from "./activity.js";
import { getEnrollment, markQuizLessonComplete, recomputeCourse } from "./progress.js";
import { lessonCompletion } from "./certificates.js";
import { queueEmail, deliverById } from "./email.js";

const GRACE_SECONDS = 30;

// ───────────── Attempt snapshots ─────────────
// An attempt stores the policy and every question exactly as it started, so
// edits to the assessment, its questions or their translations never change
// what a learner saw, how they are scored, or the threshold they must reach.

const POLICY_FIELDS = ["kind", "passing_score", "time_limit_seconds", "feedback_policy", "is_certification"];

/** The assessment policy an attempt is held to (its snapshot, or live for legacy attempts). */
export function attemptPolicy(attempt, assessment) {
  const snap = parseJson(attempt?.policy_json, null);
  return snap ? { ...assessment, ...snap } : assessment;
}

async function snapshotQuestions(env, ids, locale, certification) {
  const rows = (
    await env.DB.prepare(
      `SELECT q.id, q.type, q.prompt, q.data_json, q.answer_json, q.explanation, q.rubric, q.grading, q.points, q.lesson_id,
              qc.title AS case_title, qc.body_md AS case_body
         FROM questions q LEFT JOIN question_cases qc ON qc.id = q.case_id WHERE q.id IN (${ids.map(() => "?").join(",")})`,
    )
      .bind(...ids)
      .all()
  ).results;
  // Learner-visible text in the attempt's language (reviewed translations only for certification).
  await localize(env, "question", rows, ["prompt", "data_json", "explanation"], locale, { requireReviewed: Boolean(certification) });
  return new Map(rows.map(({ _tr, id, ...q }) => [id, { ...q, translation: _tr || null }]));
}

/** Map question id → question as frozen in the attempt (falls back to live rows for legacy attempts). */
async function attemptSnapshot(env, attempt, extraLive = []) {
  const rows = (await env.DB.prepare("SELECT question_id, question_json FROM attempt_answers WHERE attempt_id = ?").bind(attempt.id).all()).results;
  const out = new Map();
  const missing = [];
  for (const r of rows) {
    const q = parseJson(r.question_json, null);
    if (q) out.set(r.question_id, q);
    else missing.push(r.question_id);
  }
  for (const id of extraLive) if (!out.has(id)) missing.push(id);
  if (missing.length) {
    const certification = parseJson(attempt.policy_json, null)?.is_certification ?? (await env.DB.prepare("SELECT is_certification FROM assessments WHERE id = ?").bind(attempt.assessment_id).first())?.is_certification;
    for (const [id, q] of await snapshotQuestions(env, missing, attempt.locale, certification)) out.set(id, q);
  }
  return out;
}
export const QUESTION_TYPES = ["single", "multiple", "true_false", "matching", "ordering", "short_answer"];

export async function getAssessment(env, id) {
  const a = await env.DB.prepare("SELECT * FROM assessments WHERE id = ?").bind(id).first();
  if (!a) throw new HttpError(404, "not_found");
  return a;
}

export async function attemptHistory(env, userId, assessmentId) {
  return (await env.DB.prepare("SELECT * FROM attempts WHERE user_id = ? AND assessment_id = ? ORDER BY attempt_no DESC").bind(userId, assessmentId).all()).results;
}

/** Whether the learner may start a new attempt now, and why not. */
export async function attemptGate(env, user, assessment, course) {
  const enr = await getEnrollment(env, user.id, assessment.course_id);
  if (!enr || enr.status === "withdrawn") return { ok: false, reason: "assess.gate.enroll" };
  if (assessment.status !== "active") return { ok: false, reason: "assess.gate.inactive" };
  const history = await attemptHistory(env, user.id, assessment.id);
  const open = history.find((h) => h.status === "in_progress");
  if (open) return { ok: true, resume: open, history };
  if (assessment.kind === "exam" && assessment.is_certification && course.require_all_lessons) {
    const l = await lessonCompletion(env, user.id, course.id);
    if (l.done < l.required) return { ok: false, reason: "assess.gate.lessons", history, lessons: l };
  }
  const used = history.length;
  if (assessment.max_attempts && used >= assessment.max_attempts) return { ok: false, reason: "assess.gate.max_attempts", history };
  const last = history.find((h) => h.submitted_at);
  if (last && assessment.cooldown_minutes) {
    const readyAt = addSeconds(last.submitted_at, assessment.cooldown_minutes * 60);
    if (readyAt > nowIso()) return { ok: false, reason: "assess.gate.cooldown", readyAt, history };
  }
  if (assessment.kind === "exam" && assessment.is_certification && history.some((h) => h.status === "graded" && h.passed)) {
    return { ok: true, alreadyPassed: true, history };
  }
  return { ok: true, history };
}

async function drawQuestions(env, assessmentId) {
  const rules = (await env.DB.prepare("SELECT * FROM assessment_rules WHERE assessment_id = ? ORDER BY sort_order").bind(assessmentId).all()).results;
  if (!rules.length) throw new HttpError(409, "assessment_empty");
  const chosen = [];
  const seen = new Set();
  for (const r of rules) {
    const pool = (
      await env.DB.prepare(`SELECT id, type, case_id, data_json FROM questions WHERE bank_id = ? AND status = 'active' ${r.difficulty ? "AND difficulty = ?" : ""}`)
        .bind(...(r.difficulty ? [r.bank_id, r.difficulty] : [r.bank_id]))
        .all()
    ).results.filter((q) => !seen.has(q.id));
    if (pool.length < r.draw_count) throw new HttpError(409, "question_bank_too_small");
    for (const q of shuffle(pool).slice(0, r.draw_count)) {
      seen.add(q.id);
      chosen.push(q);
    }
  }
  return chosen;
}

function buildLayout(questions, assessment) {
  let ordered = assessment.shuffle_questions ? shuffle(questions) : questions;
  // Keep questions that share a case study together, in first-seen order.
  const groups = new Map();
  for (const q of ordered) {
    const k = q.case_id || q.id;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(q);
  }
  ordered = [...groups.values()].flat();
  return ordered.map((q) => {
    const d = parseJson(q.data_json, {});
    const entry = { q: q.id };
    if (q.type === "single" || q.type === "multiple") {
      const ids = (d.options || []).map((o) => o.id);
      entry.opts = assessment.shuffle_options ? shuffle(ids) : ids;
    } else if (q.type === "matching") {
      entry.right = shuffle((d.right || []).map((o) => o.id));
    } else if (q.type === "ordering") {
      const ids = (d.items || []).map((o) => o.id);
      let s = shuffle(ids);
      for (let i = 0; i < 5 && ids.length > 1 && s.join() === ids.join(); i++) s = shuffle(ids);
      entry.items = s;
    }
    return entry;
  });
}

/** Auto-submit the learner's open attempt if its time ran out. Returns true if one was closed. */
export async function settleExpiredAttempt(c, assessment) {
  const open = await c.env.DB.prepare("SELECT * FROM attempts WHERE user_id = ? AND assessment_id = ? AND status = 'in_progress'").bind(c.user.id, assessment.id).first();
  if (!open || !deadlinePassed(open)) return false;
  await submitAttempt(c, open, { auto: true });
  return true;
}

export async function startAttempt(c, assessment, course) {
  const { env, user } = c;
  // An expired open attempt is graded first, so eligibility below is computed
  // from the updated history and attempt limits and cooldowns still apply.
  await settleExpiredAttempt(c, assessment);
  const gate = await attemptGate(env, user, assessment, course);
  if (gate.resume) return gate.resume;
  if (!gate.ok) throw new HttpError(409, "attempt_not_allowed", gate.reason, { reason: gate.reason });
  const questions = await drawQuestions(env, assessment.id);
  const layout = buildLayout(questions, assessment);
  const snapshot = await snapshotQuestions(env, questions.map((q) => q.id), c.locale, assessment.is_certification);
  const policy = Object.fromEntries(POLICY_FIELDS.map((k) => [k, assessment[k] ?? null]));
  // Which quiz lessons this attempt completes, and the course rule for it, are
  // frozen too: a later revision moving the assessment cannot redirect completion.
  policy.quiz_lesson_ids = (await env.DB.prepare("SELECT id FROM lessons WHERE assessment_id = ? AND course_id = ?").bind(assessment.id, assessment.course_id).all()).results.map((l) => l.id);
  policy.require_quizzes_pass = course.require_quizzes_pass ? 1 : 0;
  const now = nowIso();
  const attempt = {
    policy_json: JSON.stringify(policy),
    id: newId("att_"),
    user_id: user.id,
    assessment_id: assessment.id,
    course_id: assessment.course_id,
    attempt_no: (gate.history?.[0]?.attempt_no || 0) + 1,
    status: "in_progress",
    locale: c.locale,
    layout_json: JSON.stringify(layout),
    started_at: now,
    deadline_at: assessment.time_limit_seconds ? addSeconds(now, assessment.time_limit_seconds) : null,
  };
  try {
    await env.DB.batch([
      env.DB.prepare(
        // user_id is NULL (NOT NULL violation, batch rolled back) unless the enrollment is still current.
        `INSERT INTO attempts (id, user_id, assessment_id, course_id, attempt_no, status, locale, layout_json, started_at, deadline_at, policy_json)
         VALUES (?1, (SELECT ?2 WHERE EXISTS (SELECT 1 FROM enrollments WHERE user_id = ?2 AND course_id = ?4 AND status != 'withdrawn')), ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)`,
      ).bind(attempt.id, attempt.user_id, attempt.assessment_id, attempt.course_id, attempt.attempt_no, attempt.status, attempt.locale, attempt.layout_json, attempt.started_at, attempt.deadline_at, JSON.stringify(policy)),
      ...layout.map((l) =>
        env.DB.prepare("INSERT INTO attempt_answers (attempt_id, question_id, max_points, question_json) VALUES (?,?,?,?)").bind(attempt.id, l.q, snapshot.get(l.q).points || 1, JSON.stringify(snapshot.get(l.q))),
      ),
      eventStmt(env, { userId: user.id, event: `${assessment.kind}_started`, courseId: assessment.course_id, locale: c.locale }),
    ]);
  } catch (e) {
    // A concurrent request already opened an attempt; resume that one.
    if (/UNIQUE/i.test(String(e?.message))) {
      const open = await env.DB.prepare("SELECT * FROM attempts WHERE user_id = ? AND assessment_id = ? AND status = 'in_progress'").bind(user.id, assessment.id).first();
      if (open) return open;
    }
    if (/NOT NULL/i.test(String(e?.message)) && /attempts\.user_id/i.test(String(e?.message))) throw new HttpError(403, "not_enrolled");
    throw e;
  }
  return attempt;
}

/** The learner's own attempt; an attempt still in progress also needs a current (not withdrawn) enrollment. */
export async function getOwnAttempt(env, userId, attemptId) {
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  if (!a || a.user_id !== userId) throw new HttpError(404, "not_found");
  if (a.status === "in_progress") {
    const e = await env.DB.prepare("SELECT status FROM enrollments WHERE user_id = ? AND course_id = ?").bind(userId, a.course_id).first();
    if (!e || e.status === "withdrawn") throw new HttpError(403, "not_enrolled");
  }
  return a;
}

/** Learner-safe question payload for an attempt, in the attempt's layout order (from its snapshot). */
export async function attemptQuestions(env, attempt) {
  const layout = parseJson(attempt.layout_json, []);
  if (!layout.length) return [];
  const snap = await attemptSnapshot(env, attempt);
  const answers = new Map(
    (await env.DB.prepare("SELECT question_id, response_json FROM attempt_answers WHERE attempt_id = ?").bind(attempt.id).all()).results.map((a) => [
      a.question_id,
      parseJson(a.response_json, null),
    ]),
  );
  return layout.map((l, i) => {
    const q = snap.get(l.q);
    const d = parseJson(q.data_json, {});
    const pick = (list, order) => {
      const m = new Map((list || []).map((o) => [o.id, o]));
      return (order || []).map((id) => m.get(id)).filter(Boolean).map((o) => ({ id: o.id, text: o.text }));
    };
    const out = { id: l.q, n: i + 1, type: q.type, prompt: q.prompt, points: q.points, caseTitle: q.case_title, caseBody: q.case_body, response: answers.get(l.q), translation: q.translation };
    if (q.type === "single" || q.type === "multiple") out.options = pick(d.options, l.opts);
    if (q.type === "matching") {
      out.left = (d.left || []).map((o) => ({ id: o.id, text: o.text }));
      out.right = pick(d.right, l.right);
    }
    if (q.type === "ordering") out.items = pick(d.items, l.items);
    if (q.type === "short_answer") out.maxLength = Math.min(Number(d.max_length) || 600, 4000);
    return out;
  });
}

/** Validate and normalize a learner response against the question structure. */
function normalizeResponse(q, raw) {
  const d = parseJson(q.data_json, {});
  if (raw == null || raw === "") return null;
  switch (q.type) {
    case "single": {
      const v = String(Array.isArray(raw) ? raw[0] : raw);
      return (d.options || []).some((o) => o.id === v) ? v : null;
    }
    case "multiple": {
      const valid = new Set((d.options || []).map((o) => o.id));
      const list = [...new Set([].concat(raw).map(String))].filter((v) => valid.has(v));
      return list.length ? list : null;
    }
    case "true_false":
      return raw === true || raw === "true" ? true : raw === false || raw === "false" ? false : null;
    case "matching": {
      if (typeof raw !== "object" || Array.isArray(raw)) return null;
      const left = new Set((d.left || []).map((o) => o.id));
      const right = new Set((d.right || []).map((o) => o.id));
      const out = {};
      for (const [k, v] of Object.entries(raw)) if (left.has(k) && right.has(String(v))) out[k] = String(v);
      return Object.keys(out).length ? out : null;
    }
    case "ordering": {
      const ids = (d.items || []).map((o) => o.id);
      const list = [].concat(raw).map(String);
      return list.length === ids.length && new Set(list).size === ids.length && list.every((x) => ids.includes(x)) ? list : null;
    }
    case "short_answer":
      return String(raw).slice(0, Math.min(Number(d.max_length) || 600, 4000)).trim() || null;
    default:
      return null;
  }
}

const normText = (s) =>
  String(s)
    .normalize("NFKC")
    .toLowerCase()
    .replace(/(?<!\d)\.|\.(?!\d)/g, " ")
    .replace(/[^\p{L}\p{N}\s.%-]/gu, "")
    .replace(/\s+/g, " ")
    .trim();

/** Score one response. Returns { fraction (0..1) | null when manual review is needed }. */
export function scoreResponse(q, response) {
  const key = parseJson(q.answer_json, {});
  if (q.grading === "manual") return { fraction: null, manual: true };
  if (response == null) return { fraction: 0 };
  switch (q.type) {
    case "single":
      return { fraction: (key.correct || []).includes(response) ? 1 : 0 };
    case "multiple": {
      const correct = new Set(key.correct || []);
      const picked = new Set(response);
      let hits = 0;
      let wrong = 0;
      for (const p of picked) correct.has(p) ? hits++ : wrong++;
      const f = correct.size ? Math.max(0, (hits - wrong) / correct.size) : 0;
      return { fraction: Math.round(f * 1000) / 1000 };
    }
    case "true_false":
      return { fraction: response === key.value ? 1 : 0 };
    case "matching": {
      const pairs = key.pairs || {};
      const total = Object.keys(pairs).length || 1;
      const ok = Object.entries(pairs).filter(([l, r]) => response[l] === r).length;
      return { fraction: Math.round((ok / total) * 1000) / 1000 };
    }
    case "ordering": {
      const order = key.order || [];
      const ok = order.filter((id, i) => response[i] === id).length;
      return { fraction: order.length ? Math.round((ok / order.length) * 1000) / 1000 : 0 };
    }
    case "short_answer": {
      const accepted = (key.accepted || []).map(normText);
      const r = normText(response);
      const hit = key.match === "contains" ? accepted.some((a) => a && r.includes(a)) : accepted.includes(r);
      return { fraction: hit ? 1 : 0 };
    }
    default:
      return { fraction: 0 };
  }
}

function deadlinePassed(attempt) {
  return attempt.deadline_at && addSeconds(attempt.deadline_at, GRACE_SECONDS) < nowIso();
}

export async function saveResponses(env, attempt, responses) {
  if (attempt.status !== "in_progress" || attempt.submitted_at) throw new HttpError(409, "attempt_closed");
  if (deadlinePassed(attempt)) throw new HttpError(409, "time_expired");
  const layoutIds = new Set(parseJson(attempt.layout_json, []).map((l) => l.q));
  const entries = Object.entries(responses || {}).filter(([qid]) => layoutIds.has(qid));
  if (!entries.length) return 0;
  const byId = await attemptSnapshot(env, attempt);
  const now = nowIso();
  const stmts = entries.map(([qid, raw]) => {
    const v = normalizeResponse(byId.get(qid), raw);
    return env.DB.prepare(
      `UPDATE attempt_answers SET response_json = ?, saved_at = ? WHERE attempt_id = ? AND question_id = ?
         AND EXISTS (SELECT 1 FROM attempts t JOIN enrollments e ON e.user_id = t.user_id AND e.course_id = t.course_id
                      WHERE t.id = ? AND t.status = 'in_progress' AND t.submitted_at IS NULL AND e.status != 'withdrawn')`,
    ).bind(v == null ? null : JSON.stringify(v), now, attempt.id, qid, attempt.id);
  });
  await env.DB.batch(stmts);
  return stmts.length;
}

/** Grade and close an attempt. Late submissions are graded on autosaved answers only. */
export async function submitAttempt(c, attempt, { responses = null, auto = false } = {}) {
  const { env } = c;
  if (attempt.status !== "in_progress") return attempt;
  if (responses && !deadlinePassed(attempt)) await saveResponses(env, attempt, responses);
  let now = nowIso();
  // An expired attempt closed at its deadline, whenever it is auto-submitted;
  // cooldowns are measured from that moment.
  if (auto && attempt.deadline_at && attempt.deadline_at < now) now = attempt.deadline_at;
  // Close the attempt to writes before reading the answers: an autosave still
  // in flight is rejected by saveResponses' submitted_at guard from here on,
  // so the responses graded below are exactly the final ones.
  // Only while the learner's enrollment is current: a withdrawn learner's attempt is never graded.
  const closed = await env.DB.prepare(
    `UPDATE attempts SET submitted_at = COALESCE(submitted_at, ?) WHERE id = ? AND status = 'in_progress'
       AND EXISTS (SELECT 1 FROM enrollments e WHERE e.user_id = attempts.user_id AND e.course_id = attempts.course_id AND e.status != 'withdrawn')`,
  )
    .bind(now, attempt.id)
    .run();
  if (!closed.meta.changes) {
    const current = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attempt.id).first();
    if (current.status === "in_progress") throw new HttpError(403, "not_enrolled");
    return current;
  }
  const snap = await attemptSnapshot(env, attempt);
  const rows = (await env.DB.prepare("SELECT question_id, response_json, max_points FROM attempt_answers WHERE attempt_id = ?").bind(attempt.id).all()).results.map((r) => {
    const q = snap.get(r.question_id);
    return { ...r, type: q.type, grading: q.grading, answer_json: q.answer_json, data_json: q.data_json };
  });
  let pending = false;
  const stmts = [];
  for (const r of rows) {
    const resp = parseJson(r.response_json, null);
    const s = scoreResponse(r, resp);
    if (s.manual && resp != null) {
      pending = true;
      stmts.push(env.DB.prepare("UPDATE attempt_answers SET needs_review = 1, is_correct = NULL, points_awarded = NULL WHERE attempt_id = ? AND question_id = ?").bind(attempt.id, r.question_id));
    } else {
      const fraction = s.manual ? 0 : s.fraction;
      stmts.push(
        env.DB.prepare("UPDATE attempt_answers SET is_correct = ?, points_awarded = ?, needs_review = 0 WHERE attempt_id = ? AND question_id = ?").bind(
          fraction >= 1 ? 1 : 0,
          Math.round(fraction * r.max_points * 1000) / 1000,
          attempt.id,
          r.question_id,
        ),
      );
    }
  }
  // The status guard makes concurrent submissions harmless: only one wins.
  stmts.push(
    env.DB.prepare("UPDATE attempts SET status = ?, submitted_at = COALESCE(submitted_at, ?) WHERE id = ? AND status = 'in_progress'").bind(pending ? "pending_review" : "in_progress", now, attempt.id),
  );
  await env.DB.batch(stmts);
  if (pending) {
    await eventStmt(env, { userId: attempt.user_id, event: "attempt_pending_review", courseId: attempt.course_id }).run();
    return { ...attempt, status: "pending_review", submitted_at: now };
  }
  return finalizeAttempt(c, attempt.id, { auto });
}

/** Compute the final score once every answer has points, then apply consequences. */
export async function finalizeAttempt(c, attemptId, { auto = false } = {}) {
  const { env } = c;
  const attempt = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  if (attempt.status === "graded") return attempt;
  const agg = await env.DB.prepare(
    "SELECT SUM(COALESCE(points_awarded, 0)) AS pts, SUM(max_points) AS maxp, SUM(needs_review) AS open_reviews FROM attempt_answers WHERE attempt_id = ?",
  )
    .bind(attemptId)
    .first();
  if (agg.open_reviews > 0) return attempt;
  // The threshold is the one in force when the attempt started.
  const assessment = attemptPolicy(attempt, await getAssessment(env, attempt.assessment_id));
  const pct = agg.maxp ? Math.round((agg.pts / agg.maxp) * 10000) / 100 : 0;
  const passed = pct >= assessment.passing_score ? 1 : 0;
  const now = nowIso();
  const res = await env.DB.prepare(
    `UPDATE attempts SET status = 'graded', graded_at = ?, submitted_at = COALESCE(submitted_at, ?), score_points = ?, max_points = ?, score_pct = ?, passed = ?
      WHERE id = ? AND status IN ('in_progress','pending_review')`,
  )
    .bind(now, now, agg.pts, agg.maxp, pct, passed, attemptId)
    .run();
  if (!res.meta.changes) return env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();

  const graded = { ...attempt, status: "graded", graded_at: now, score_points: agg.pts, max_points: agg.maxp, score_pct: pct, passed };
  const learner = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(attempt.user_id).first();
  await eventStmt(env, { userId: learner.id, event: `${assessment.kind}_${passed ? "passed" : "failed"}`, courseId: attempt.course_id, locale: attempt.locale }).run();
  if (passed) await grantAchievement(env, learner.id, "first_quiz_pass");
  if (pct >= 100) await grantAchievement(env, learner.id, "perfect_score");

  const course = await env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(attempt.course_id).first();
  // The lessons and quiz rule frozen when the attempt started (live lookup only for legacy attempts).
  const lessons = Array.isArray(assessment.quiz_lesson_ids)
    ? assessment.quiz_lesson_ids.map((id) => ({ id }))
    : (await env.DB.prepare("SELECT id FROM lessons WHERE assessment_id = ? AND course_id = ?").bind(assessment.id, course.id).all()).results;
  const requirePass = assessment.require_quizzes_pass ?? course.require_quizzes_pass;
  const completesLesson = assessment.kind === "exam" ? Boolean(passed) : Boolean(passed || !requirePass);
  if (completesLesson) for (const l of lessons) await markQuizLessonComplete(env, learner.id, l.id, course.id);
  // Recompute as the learner (the reviewer may be the one finalizing).
  const lc = { ...c, user: learner };
  const summary = await recomputeCourse(lc, course.id);
  graded.certificate = summary.certificate || null;
  if (assessment.kind === "exam") {
    const mailId = await queueEmail(env, c.cfg, {
      user: learner,
      template: passed ? "exam_passed" : "exam_failed",
      vars: { course: course.title, score: String(Math.round(pct)), passing: String(assessment.passing_score), url: `${c.cfg.origin}/attempts/${attempt.id}` },
    });
    c.defer(deliverById(env, c.cfg, mailId));
  }
  if (auto) graded.autoSubmitted = true;
  return graded;
}

/** Post-submission review, filtered by the assessment's feedback policy. */
export async function attemptReview(env, attempt, assessment) {
  const snap = await attemptSnapshot(env, attempt);
  const answers = (await env.DB.prepare("SELECT * FROM attempt_answers WHERE attempt_id = ?").bind(attempt.id).all()).results;
  const lessonIds = [...new Set([...snap.values()].map((q) => q.lesson_id).filter(Boolean))];
  const lessons = new Map(
    lessonIds.length
      ? (await env.DB.prepare(`SELECT id, slug, title FROM lessons WHERE id IN (${lessonIds.map(() => "?").join(",")})`).bind(...lessonIds).all()).results.map((l) => [l.id, l])
      : [],
  );
  const rows = answers.map((a) => {
    const q = snap.get(a.question_id);
    const l = lessons.get(q.lesson_id);
    return { ...a, type: q.type, prompt: q.prompt, data_json: q.data_json, answer_json: q.answer_json, explanation: q.explanation, grading: q.grading, lesson_slug: l?.slug, lesson_title: l?.title };
  });
  const order = parseJson(attempt.layout_json, []).map((l) => l.q);
  rows.sort((a, b) => order.indexOf(a.question_id) - order.indexOf(b.question_id));
  const policy = attemptPolicy(attempt, assessment).feedback_policy;
  const review = rows.map((r, i) => {
    const item = { n: i + 1, status: r.needs_review ? "pending" : r.is_correct ? "correct" : r.points_awarded > 0 ? "partial" : "incorrect", points: r.points_awarded, max: r.max_points };
    if (policy === "score") return item;
    item.prompt = r.prompt;
    item.reviewerComment = r.reviewer_comment;
    item.lesson = r.lesson_slug ? { slug: r.lesson_slug, title: r.lesson_title } : null;
    if (policy === "full") {
      item.explanation = r.explanation;
      item.correctAnswer = describeAnswer(r);
      item.yourAnswer = describeResponse(r);
    }
    return item;
  });
  const reviewLessons = new Map();
  for (const r of rows) if (!r.is_correct && !r.needs_review && r.lesson_slug) reviewLessons.set(r.lesson_slug, r.lesson_title);
  return { items: review, reviewLessons: [...reviewLessons].map(([slug, title]) => ({ slug, title })) };
}

function textMap(list) {
  return new Map((list || []).map((o) => [o.id, o.text]));
}

function describeAnswer(r) {
  const d = parseJson(r.data_json, {});
  const k = parseJson(r.answer_json, {});
  switch (r.type) {
    case "single":
    case "multiple": {
      const m = textMap(d.options);
      return (k.correct || []).map((id) => m.get(id)).join("; ");
    }
    case "true_false":
      return k.value ? "true" : "false";
    case "matching": {
      const L = textMap(d.left);
      const R = textMap(d.right);
      return Object.entries(k.pairs || {})
        .map(([l, rr]) => `${L.get(l)} → ${R.get(rr)}`)
        .join("; ");
    }
    case "ordering": {
      const m = textMap(d.items);
      return (k.order || []).map((id, i) => `${i + 1}. ${m.get(id)}`).join("  ");
    }
    case "short_answer":
      return r.grading === "manual" ? "" : (k.accepted || [])[0] || "";
    default:
      return "";
  }
}

function describeResponse(r) {
  const d = parseJson(r.data_json, {});
  const v = parseJson(r.response_json, null);
  if (v == null) return null;
  switch (r.type) {
    case "single":
      return textMap(d.options).get(v);
    case "multiple": {
      const m = textMap(d.options);
      return v.map((id) => m.get(id)).join("; ");
    }
    case "true_false":
      return v ? "true" : "false";
    case "matching": {
      const L = textMap(d.left);
      const R = textMap(d.right);
      return Object.entries(v)
        .map(([l, rr]) => `${L.get(l)} → ${R.get(rr)}`)
        .join("; ");
    }
    case "ordering": {
      const m = textMap(d.items);
      return v.map((id, i) => `${i + 1}. ${m.get(id)}`).join("  ");
    }
    default:
      return String(v);
  }
}

// Only manually graded answers (awaiting review, or already reviewed) of an
// attempt still awaiting grading; automatically scored answers are never writable.
const GRADABLE = "attempt_id = ? AND question_id = ? AND (needs_review = 1 OR reviewer_id IS NOT NULL) AND EXISTS (SELECT 1 FROM attempts WHERE id = attempt_id AND status = 'pending_review')";

/** Reviewer grading for manually scored answers. */
export async function gradeAnswer(c, attemptId, questionId, points, comment) {
  const row = await c.env.DB.prepare(`SELECT max_points FROM attempt_answers WHERE ${GRADABLE}`).bind(attemptId, questionId).first();
  if (!row) throw new HttpError(404, "not_found");
  const p = Math.max(0, Math.min(row.max_points, Number(points) || 0));
  const res = await c.env.DB.prepare(`UPDATE attempt_answers SET points_awarded = ?, is_correct = ?, needs_review = 0, reviewer_id = ?, reviewer_comment = ? WHERE ${GRADABLE}`)
    .bind(p, p >= row.max_points ? 1 : 0, c.user.id, String(comment || "").slice(0, 2000), attemptId, questionId)
    .run();
  if (!res.meta.changes) throw new HttpError(409, "already_graded");
  return finalizeAttempt(c, attemptId);
}

/** Per-question difficulty analytics for administrators. */
/** Item statistics for the draft questions of a bank (answers come from live attempts). */
export async function questionStats(env, bankId) {
  return (
    await env.DB.prepare(
      `SELECT q.id, q.prompt, q.type, q.difficulty, q.status,
              COUNT(aa.attempt_id) AS answered,
              SUM(CASE WHEN aa.is_correct = 1 THEN 1 ELSE 0 END) AS correct
         FROM draft_questions q LEFT JOIN attempt_answers aa ON aa.question_id = q.id AND aa.points_awarded IS NOT NULL
        WHERE q.bank_id = ? GROUP BY q.id ORDER BY q.created_at`,
    )
      .bind(bankId)
      .all()
  ).results;
}
