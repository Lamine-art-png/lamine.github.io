// Admin: assessment policies and draw rules, question banks, the question
// editor (plain-text format, no JSON required), item analytics, and grading.
import { html, raw } from "../../lib/html.js";
import { redirect, HttpError } from "../../lib/http.js";
import { newId, nowIso, parseJson, randomToken } from "../../lib/util.js";
import { auditStmt, audit } from "../../lib/security.js";
import { adminPage, table, statusBadge, hidden, input, textarea, select, checkbox, bool, str, intOrNull, pct } from "./shell.js";
import { QUESTION_TYPES, questionStats, gradeAnswer } from "../../services/assessments.js";

// ───────────── Assessments ─────────────

export async function createAssessment(c) {
  const b = await c.readBody();
  const course = await c.env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(c.params.id).first();
  if (!course) throw new HttpError(404, "not_found");
  const exam = b.kind === "exam";
  const id = newId("asm_");
  const now = nowIso();
  await c.env.DB.batch([
    c.env.DB.prepare(
      `INSERT INTO assessments (id, course_id, kind, title, passing_score, max_attempts, cooldown_minutes, time_limit_seconds, feedback_policy, is_certification, status, created_at, updated_at)
       VALUES (?,?,?,?,?,?,?,?,?,?, 'draft', ?, ?)`,
    ).bind(id, course.id, exam ? "exam" : "quiz", str(b.title, 200) || (exam ? "Final exam" : "Quiz"), course.passing_score, exam ? 3 : null, exam ? 60 : 0, exam ? 1800 : null, exam ? "correctness" : "full", exam ? 1 : 0, now, now),
    auditStmt(c.env, c.user.id, "assessment.create", "assessment", id, { course_id: course.id, kind: exam ? "exam" : "quiz" }),
  ]);
  return redirect(`/admin/assessments/${id}?ok=created`);
}

export async function editAssessment(c) {
  const a = await c.env.DB.prepare("SELECT * FROM assessments WHERE id = ?").bind(c.params.id).first();
  if (!a) throw new HttpError(404, "not_found");
  const [course, rules, banks, attempts] = await Promise.all([
    c.env.DB.prepare("SELECT id, title FROM courses WHERE id = ?").bind(a.course_id).first(),
    c.env.DB.prepare(
      `SELECT r.*, b.title AS bank_title, (SELECT COUNT(*) FROM questions q WHERE q.bank_id = r.bank_id AND q.status = 'active' AND (r.difficulty IS NULL OR q.difficulty = r.difficulty)) AS available
         FROM assessment_rules r JOIN question_banks b ON b.id = r.bank_id WHERE r.assessment_id = ? ORDER BY r.sort_order`,
    )
      .bind(a.id)
      .all(),
    c.env.DB.prepare("SELECT id, title FROM question_banks WHERE course_id = ? OR course_id IS NULL ORDER BY title").bind(a.course_id).all(),
    c.env.DB.prepare("SELECT COUNT(*) AS n, SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed, AVG(score_pct) AS avg FROM attempts WHERE assessment_id = ? AND status = 'graded'").bind(a.id).first(),
  ]);
  const body = html`<p><a href="/admin/courses/${course.id}">← ${course.title}</a></p>
  <p class="small">Graded attempts: <strong>${attempts.n}</strong> · pass rate <strong>${attempts.n ? pct((attempts.passed || 0) / attempts.n) : "—"}</strong> · average <strong>${attempts.avg == null ? "—" : `${Number(attempts.avg).toFixed(1)}%`}</strong></p>
  <form class="form-card" method="post" action="/admin/assessments/${a.id}">${hidden(c)}
    ${input("title", "Title", a.title, { required: true })}
    ${textarea("instructions", "Instructions (Markdown)", a.instructions, { rows: 4 })}
    <div class="grid-2">
      ${select("kind", "Kind", [["quiz", "Quiz"], ["exam", "Exam"]], a.kind)}
      ${select("status", "Status", ["draft", "active", "retired"], a.status)}
      ${input("passing_score", "Passing score (%)", a.passing_score, { type: "number", attrs: 'min="1" max="100"', hint: "Certification default is 80%." })}
      ${input("time_limit_minutes", "Time limit (minutes, empty = none)", a.time_limit_seconds ? Math.round(a.time_limit_seconds / 60) : "", { type: "number", attrs: 'min="1" max="600"' })}
      ${input("max_attempts", "Maximum attempts (empty = unlimited)", a.max_attempts ?? "", { type: "number", attrs: 'min="1" max="100"' })}
      ${input("cooldown_minutes", "Wait between attempts (minutes)", a.cooldown_minutes, { type: "number", attrs: 'min="0" max="10080"' })}
      ${select("feedback_policy", "Feedback after submission", [["score", "Score only"], ["correctness", "Score + which questions were right (no answers)"], ["full", "Full: correct answers and explanations"]], a.feedback_policy, { hint: "For certification exams, “correctness” protects the question bank." })}
    </div>
    ${checkbox("is_certification", "Certification exam (passing issues the course credential)", a.is_certification)}
    ${checkbox("is_required", "Required", a.is_required)}
    ${checkbox("shuffle_questions", "Shuffle question order", a.shuffle_questions)}
    ${checkbox("shuffle_options", "Shuffle answer options", a.shuffle_options)}
    <button class="btn btn-primary">Save policy</button></form>
  <section class="form-card mt-3"><h2 class="h2">Question selection rules</h2>
    <p class="small muted">Each attempt draws randomly from these banks. Questions never repeat within an attempt.</p>
    ${table(
      ["Bank", "Difficulty", "Draw", "Available", ""],
      rules.results.map(
        (r) => html`<tr><td><a href="/admin/banks/${r.bank_id}">${r.bank_title}</a></td><td>${r.difficulty || "any"}</td><td>${r.draw_count}</td>
          <td>${r.available < r.draw_count ? html`<span class="badge badge-danger">${r.available} — too few</span>` : r.available}</td>
          <td><form method="post" action="/admin/rules/${r.id}/delete">${hidden(c)}<button class="link-btn tiny">Remove</button></form></td></tr>`,
      ),
    )}
    <form method="post" action="/admin/assessments/${a.id}/rules" class="row mt-2">${hidden(c)}
      <select name="bank_id" aria-label="Bank" required>${banks.results.map((b) => html`<option value="${b.id}">${b.title}</option>`)}</select>
      <select name="difficulty" aria-label="Difficulty"><option value="">any difficulty</option><option>easy</option><option>medium</option><option>hard</option></select>
      <input name="draw_count" type="number" min="1" max="200" value="5" aria-label="Number of questions" class="w-small">
      <button class="btn btn-sm btn-secondary">Add rule</button></form>
    ${banks.results.length ? "" : html`<p class="small mt-1"><a href="/admin/banks">Create a question bank first.</a></p>`}
  </section>`;
  return adminPage(c, { title: a.title, active: "/admin/courses", body });
}

export async function saveAssessment(c) {
  const b = await c.readBody();
  const a = await c.env.DB.prepare("SELECT * FROM assessments WHERE id = ?").bind(c.params.id).first();
  if (!a) throw new HttpError(404, "not_found");
  const minutes = intOrNull(b.time_limit_minutes);
  const status = ["draft", "active", "retired"].includes(b.status) ? b.status : a.status;
  const isCert = bool(b.is_certification);
  if (status === "active" && isCert) {
    const other = await c.env.DB.prepare("SELECT id FROM assessments WHERE course_id = ? AND is_certification = 1 AND status = 'active' AND id != ?").bind(a.course_id, a.id).first();
    if (other) return redirect(`/admin/assessments/${a.id}?err=${encodeURIComponent("This course already has an active certification exam.")}`);
  }
  await c.env.DB.batch([
    c.env.DB.prepare(
      `UPDATE assessments SET title=?, instructions=?, kind=?, status=?, passing_score=?, time_limit_seconds=?, max_attempts=?, cooldown_minutes=?, feedback_policy=?,
         is_certification=?, is_required=?, shuffle_questions=?, shuffle_options=?, updated_at=? WHERE id=?`,
    ).bind(
      str(b.title, 200) || a.title,
      str(b.instructions, 4000),
      b.kind === "exam" ? "exam" : "quiz",
      status,
      Math.min(100, Math.max(1, intOrNull(b.passing_score) || 80)),
      minutes && minutes > 0 ? minutes * 60 : null,
      intOrNull(b.max_attempts) && intOrNull(b.max_attempts) > 0 ? intOrNull(b.max_attempts) : null,
      Math.max(0, intOrNull(b.cooldown_minutes) || 0),
      ["score", "correctness", "full"].includes(b.feedback_policy) ? b.feedback_policy : "full",
      isCert,
      bool(b.is_required),
      bool(b.shuffle_questions),
      bool(b.shuffle_options),
      nowIso(),
      a.id,
    ),
    auditStmt(c.env, c.user.id, "assessment.update", "assessment", a.id, { status, passing: b.passing_score }),
  ]);
  return redirect(`/admin/assessments/${a.id}?ok=saved`);
}

export async function addRule(c) {
  const b = await c.readBody();
  const max = await c.env.DB.prepare("SELECT COALESCE(MAX(sort_order), 0) AS m FROM assessment_rules WHERE assessment_id = ?").bind(c.params.id).first();
  await c.env.DB.prepare("INSERT INTO assessment_rules (id, assessment_id, bank_id, difficulty, draw_count, sort_order) VALUES (?,?,?,?,?,?)")
    .bind(newId("rul_"), c.params.id, b.bank_id, ["easy", "medium", "hard"].includes(b.difficulty) ? b.difficulty : null, Math.min(200, Math.max(1, intOrNull(b.draw_count) || 1)), max.m + 1)
    .run();
  return redirect(`/admin/assessments/${c.params.id}?ok=saved`);
}

export async function deleteRule(c) {
  const r = await c.env.DB.prepare("SELECT assessment_id FROM assessment_rules WHERE id = ?").bind(c.params.id).first();
  if (!r) throw new HttpError(404, "not_found");
  await c.env.DB.prepare("DELETE FROM assessment_rules WHERE id = ?").bind(c.params.id).run();
  return redirect(`/admin/assessments/${r.assessment_id}?ok=deleted`);
}

// ───────────── Question banks ─────────────

export async function banks(c) {
  const [rows, courses] = await Promise.all([
    c.env.DB.prepare(
      `SELECT b.*, c.title AS course_title, (SELECT COUNT(*) FROM questions q WHERE q.bank_id = b.id) AS total, (SELECT COUNT(*) FROM questions q WHERE q.bank_id = b.id AND q.status = 'active') AS active
         FROM question_banks b LEFT JOIN courses c ON c.id = b.course_id ORDER BY c.title, b.title`,
    ).all(),
    c.env.DB.prepare("SELECT id, title FROM courses ORDER BY title").all(),
  ]);
  const body = html`${table(["Bank", "Course", "Questions", "Active", ""], rows.results.map((b) => html`<tr><td><a href="/admin/banks/${b.id}">${b.title}</a></td><td>${b.course_title || "Shared"}</td><td>${b.total}</td><td>${b.active}</td><td><a href="/admin/banks/${b.id}">Open</a></td></tr>`))}
  <form method="post" action="/admin/banks" class="row mt-2">${hidden(c)}
    <input name="title" placeholder="New bank title" required class="grow" aria-label="Bank title">
    <select name="course_id" aria-label="Course"><option value="">Shared (all courses)</option>${courses.results.map((x) => html`<option value="${x.id}">${x.title}</option>`)}</select>
    <button class="btn btn-sm btn-secondary">Create bank</button></form>`;
  return adminPage(c, { title: "Question banks", active: "/admin/banks", body });
}

export async function createBank(c) {
  const b = await c.readBody();
  const id = newId("bnk_");
  const now = nowIso();
  await c.env.DB.prepare("INSERT INTO question_banks (id, course_id, title, created_at, updated_at) VALUES (?,?,?,?,?)").bind(id, b.course_id || null, str(b.title, 200) || "Untitled bank", now, now).run();
  return redirect(`/admin/banks/${id}?ok=created`);
}

export async function bankDetail(c) {
  const bank = await c.env.DB.prepare("SELECT * FROM question_banks WHERE id = ?").bind(c.params.id).first();
  if (!bank) throw new HttpError(404, "not_found");
  const [stats, cases] = await Promise.all([questionStats(c.env, bank.id), c.env.DB.prepare("SELECT * FROM question_cases WHERE bank_id = ?").bind(bank.id).all()]);
  const body = html`
  ${table(
    ["Question", "Type", "Difficulty", "Status", "Answered", "Correct", ""],
    stats.map(
      (q) => html`<tr><td class="wrap-cell">${q.prompt.slice(0, 140)}</td><td>${q.type}</td><td>${q.difficulty}</td><td>${statusBadge(q.status)}</td><td>${q.answered}</td>
        <td>${q.answered ? pct((q.correct || 0) / q.answered) : "—"}</td><td><a href="/admin/questions/${q.id}">Edit</a></td></tr>`,
    ),
  )}
  <div class="row mt-2"><a class="btn btn-primary btn-sm" href="/admin/banks/${bank.id}/questions/new">Add question</a></div>
  <section class="form-card mt-3"><h2 class="h2">Case studies</h2><p class="small muted">A case study is a shared scenario shown above every question linked to it.</p>
    ${cases.results.map((k) => html`<details class="panel mt-1"><summary><strong>${k.title}</strong></summary><pre>${k.body_md}</pre></details>`)}
    <form method="post" action="/admin/banks/${bank.id}/cases" class="mt-2">${hidden(c)}${input("title", "Case title", "", { required: true })}${textarea("body_md", "Scenario (Markdown)", "", { rows: 5, required: true })}<button class="btn btn-secondary btn-sm">Add case study</button></form>
  </section>`;
  return adminPage(c, { title: bank.title, active: "/admin/banks", body });
}

export async function addCase(c) {
  const b = await c.readBody();
  await c.env.DB.prepare("INSERT INTO question_cases (id, bank_id, title, body_md, created_at) VALUES (?,?,?,?,?)").bind(newId("cas_"), c.params.id, str(b.title, 200), str(b.body_md, 10000), nowIso()).run();
  return redirect(`/admin/banks/${c.params.id}?ok=created`);
}

/** Convert stored question JSON to the editor's line format. */
export function toEditorLines(q) {
  const d = parseJson(q.data_json, {});
  const k = parseJson(q.answer_json, {});
  switch (q.type) {
    case "single":
    case "multiple":
      return (d.options || []).map((o) => `${(k.correct || []).includes(o.id) ? "* " : ""}${o.text}`).join("\n");
    case "matching": {
      const R = new Map((d.right || []).map((o) => [o.id, o.text]));
      const used = new Set(Object.values(k.pairs || {}));
      return [...(d.left || []).map((l) => `${l.text} => ${R.get(k.pairs?.[l.id]) || ""}`), ...(d.right || []).filter((r) => !used.has(r.id)).map((r) => `=> ${r.text}`)].join("\n");
    }
    case "ordering": {
      const m = new Map((d.items || []).map((o) => [o.id, o.text]));
      return (k.order || []).map((id) => m.get(id)).join("\n");
    }
    case "short_answer":
      return (k.accepted || []).join("\n");
    default:
      return "";
  }
}

const shortId = () => randomToken(4).replace(/[-_]/g, "x");

/** Parse the editor's line format into data/answer JSON, reusing IDs for unchanged text. */
export function fromEditorLines(type, text, previous, extra = {}) {
  const lines = String(text || "").split("\n").map((s) => s.trim()).filter(Boolean);
  const prevData = parseJson(previous?.data_json, {});
  const reuse = (list, txt) => (list || []).find((o) => o.text === txt)?.id || shortId();
  switch (type) {
    case "single":
    case "multiple": {
      const options = lines.map((l) => ({ correct: l.startsWith("*"), text: l.replace(/^\*\s*/, "") })).map((o) => ({ ...o, id: reuse(prevData.options, o.text) }));
      const correct = options.filter((o) => o.correct).map((o) => o.id);
      if (options.length < 2) throw new Error("Provide at least two options.");
      if (!correct.length) throw new Error("Mark at least one correct option with *.");
      if (type === "single" && correct.length !== 1) throw new Error("Single-answer questions need exactly one correct option.");
      return { data: { options: options.map(({ id, text: t }) => ({ id, text: t })) }, answer: { correct } };
    }
    case "true_false":
      return { data: {}, answer: { value: extra.tf === "true" } };
    case "matching": {
      const left = [];
      const right = [];
      const pairs = {};
      for (const l of lines) {
        const [a, b2] = l.split("=>").map((s) => s.trim());
        if (!b2) throw new Error("Matching lines use “Left => Right”.");
        let r = right.find((x) => x.text === b2);
        if (!r) right.push((r = { id: reuse(prevData.right, b2), text: b2 }));
        if (a) {
          const lft = { id: reuse(prevData.left, a), text: a };
          left.push(lft);
          pairs[lft.id] = r.id;
        }
      }
      if (left.length < 2) throw new Error("Provide at least two pairs.");
      return { data: { left, right }, answer: { pairs } };
    }
    case "ordering": {
      const items = lines.map((t) => ({ id: reuse(prevData.items, t), text: t }));
      if (items.length < 2) throw new Error("Provide at least two items in the correct order.");
      return { data: { items }, answer: { order: items.map((i) => i.id) } };
    }
    case "short_answer":
      if (extra.grading !== "manual" && !lines.length) throw new Error("Provide accepted answers, or use manual grading.");
      return { data: { max_length: Math.min(4000, Math.max(50, intOrNull(extra.max_length) || 600)) }, answer: { accepted: lines, match: extra.match === "contains" ? "contains" : "exact" } };
    default:
      throw new Error("Unknown question type.");
  }
}

export async function questionForm(c) {
  const editing = c.params.qid ? await c.env.DB.prepare("SELECT * FROM questions WHERE id = ?").bind(c.params.qid).first() : null;
  const bankId = editing?.bank_id || c.params.id;
  const bank = await c.env.DB.prepare("SELECT * FROM question_banks WHERE id = ?").bind(bankId).first();
  if (!bank) throw new HttpError(404, "not_found");
  const [cases, lessons] = await Promise.all([
    c.env.DB.prepare("SELECT id, title FROM question_cases WHERE bank_id = ?").bind(bank.id).all(),
    bank.course_id ? c.env.DB.prepare("SELECT id, title FROM lessons WHERE course_id = ? ORDER BY sort_order").bind(bank.course_id).all() : { results: [] },
  ]);
  const q = editing || { type: "single", difficulty: "medium", points: 1, grading: "auto", status: "active" };
  const k = parseJson(q.answer_json, {});
  const d = parseJson(q.data_json, {});
  const body = html`<p><a href="/admin/banks/${bank.id}">← ${bank.title}</a></p>
  <form class="form-card" method="post" action="${editing ? `/admin/questions/${q.id}` : `/admin/banks/${bank.id}/questions`}">${hidden(c)}
    <div class="grid-2">
      ${select("type", "Type", QUESTION_TYPES.map((t) => [t, t.replace("_", " ")]), q.type)}
      ${select("difficulty", "Difficulty", ["easy", "medium", "hard"], q.difficulty)}
      ${input("points", "Points", q.points, { type: "number", attrs: 'min="1" max="20"' })}
      ${select("status", "Status", ["draft", "active", "retired"], q.status)}
      ${select("case_id", "Case study", [["", "None"], ...cases.results.map((k2) => [k2.id, k2.title])], q.case_id)}
      ${select("lesson_id", "Review lesson (for learner recommendations)", [["", "None"], ...lessons.results.map((l) => [l.id, l.title])], q.lesson_id)}
    </div>
    ${textarea("prompt", "Question prompt", q.prompt, { rows: 3, required: true })}
    ${textarea("lines", "Answer setup", editing ? toEditorLines(q) : "", {
      rows: 8,
      cls: "code",
      hint: "Single/multiple choice: one option per line, prefix correct options with “* ”. Matching: “Left => Right” per line (a line “=> Extra” adds a distractor). Ordering: items in the correct order. Short answer: accepted answers, one per line.",
    })}
    <div class="grid-2">
      ${select("tf", "True/false answer", [["true", "True"], ["false", "False"]], String(k.value ?? true))}
      ${select("grading", "Grading", [["auto", "Automatic"], ["manual", "Manual (rubric)"]], q.grading, { hint: "Manual grading applies to short answers." })}
      ${select("match", "Short answer matching", [["exact", "Exact (case/punctuation-insensitive)"], ["contains", "Contains an accepted phrase"]], k.match || "exact")}
      ${input("max_length", "Short answer max length", d.max_length || 600, { type: "number" })}
    </div>
    ${textarea("rubric", "Rubric (manual grading)", q.rubric, { rows: 3 })}
    ${textarea("explanation", "Explanation shown after submission (per feedback policy)", q.explanation, { rows: 3 })}
    <button class="btn btn-primary">${editing ? "Save question" : "Add question"}</button></form>`;
  return adminPage(c, { title: editing ? "Edit question" : "New question", active: "/admin/banks", body });
}

export async function saveQuestion(c) {
  const b = await c.readBody();
  const editing = c.params.qid ? await c.env.DB.prepare("SELECT * FROM questions WHERE id = ?").bind(c.params.qid).first() : null;
  const bankId = editing?.bank_id || c.params.id;
  const type = QUESTION_TYPES.includes(b.type) ? b.type : "single";
  const back = editing ? `/admin/questions/${editing.id}` : `/admin/banks/${bankId}/questions/new`;
  let built;
  try {
    built = fromEditorLines(type, b.lines, editing, { tf: b.tf, grading: b.grading, match: b.match, max_length: b.max_length });
  } catch (e) {
    return redirect(`${back}?err=${encodeURIComponent(e.message)}`);
  }
  const prompt = str(b.prompt, 4000);
  if (!prompt) return redirect(`${back}?err=${encodeURIComponent("A prompt is required.")}`);
  const now = nowIso();
  const vals = [
    type,
    ["easy", "medium", "hard"].includes(b.difficulty) ? b.difficulty : "medium",
    prompt,
    JSON.stringify(built.data),
    JSON.stringify(built.answer),
    str(b.explanation, 4000),
    str(b.rubric, 4000) || null,
    type === "short_answer" && b.grading === "manual" ? "manual" : "auto",
    Math.min(20, Math.max(1, intOrNull(b.points) || 1)),
    ["draft", "active", "retired"].includes(b.status) ? b.status : "active",
    b.case_id || null,
    b.lesson_id || null,
  ];
  let id = editing?.id;
  if (editing) {
    await c.env.DB.prepare(
      "UPDATE questions SET type=?, difficulty=?, prompt=?, data_json=?, answer_json=?, explanation=?, rubric=?, grading=?, points=?, status=?, case_id=?, lesson_id=?, updated_at=? WHERE id=?",
    )
      .bind(...vals, now, id)
      .run();
  } else {
    id = newId("qst_");
    await c.env.DB.prepare(
      "INSERT INTO questions (type, difficulty, prompt, data_json, answer_json, explanation, rubric, grading, points, status, case_id, lesson_id, id, bank_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    )
      .bind(...vals, id, bankId, now, now)
      .run();
  }
  await audit(c, editing ? "question.update" : "question.create", "question", id, { bank_id: bankId });
  return redirect(`/admin/banks/${bankId}?ok=saved`);
}

// ───────────── Manual grading ─────────────

export async function gradingQueue(c) {
  const rows = (
    await c.env.DB.prepare(
      `SELECT t.id, t.submitted_at, a.title AS assessment, c.title AS course, u.display_name, (SELECT COUNT(*) FROM attempt_answers x WHERE x.attempt_id = t.id AND x.needs_review = 1) AS open_items
         FROM attempts t JOIN assessments a ON a.id = t.assessment_id JOIN courses c ON c.id = t.course_id JOIN users u ON u.id = t.user_id
        WHERE t.status = 'pending_review' ORDER BY t.submitted_at`,
    ).all()
  ).results;
  const body = table(
    ["Submitted", "Learner", "Course", "Assessment", "Items to grade", ""],
    rows.map((r) => html`<tr><td>${r.submitted_at?.slice(0, 16).replace("T", " ")}</td><td>${r.display_name}</td><td>${r.course}</td><td>${r.assessment}</td><td>${r.open_items}</td><td><a href="/admin/grading/${r.id}">Grade</a></td></tr>`),
  );
  return adminPage(c, { title: "Grading queue", active: "/admin/grading", body });
}

export async function gradeAttemptPage(c) {
  const attempt = await c.env.DB.prepare("SELECT t.*, u.display_name FROM attempts t JOIN users u ON u.id = t.user_id WHERE t.id = ?").bind(c.params.id).first();
  if (!attempt) throw new HttpError(404, "not_found");
  const items = (
    await c.env.DB.prepare(
      "SELECT aa.*, q.prompt, q.rubric, q.type FROM attempt_answers aa JOIN questions q ON q.id = aa.question_id WHERE aa.attempt_id = ? AND (aa.needs_review = 1 OR q.grading = 'manual')",
    )
      .bind(attempt.id)
      .all()
  ).results;
  const body = html`<p class="small">Learner: <strong>${attempt.display_name}</strong> · status ${statusBadge(attempt.status)}</p>
  ${items.map(
    (it) => html`<form class="form-card mt-2" method="post" action="/admin/grading/${attempt.id}/${it.question_id}">${hidden(c)}
      <p><strong>${it.prompt}</strong></p>
      ${it.rubric ? html`<div class="panel small"><strong>Rubric:</strong> ${it.rubric}</div>` : ""}
      <p class="mt-2"><strong>Response:</strong></p><blockquote class="panel">${parseJson(it.response_json, "") || html`<em>No answer</em>`}</blockquote>
      <div class="row">${input("points", `Points (max ${it.max_points})`, it.points_awarded ?? "", { type: "number", attrs: `min="0" max="${it.max_points}" step="0.5" required` })}
        ${input("comment", "Comment for the learner", it.reviewer_comment || "")}<button class="btn btn-primary btn-sm">Save grade</button></div></form>`,
  )}`;
  return adminPage(c, { title: "Grade attempt", active: "/admin/grading", body });
}

export async function gradeItem(c) {
  const b = await c.readBody();
  await gradeAnswer(c, c.params.id, c.params.qid, b.points, b.comment);
  await audit(c, "attempt.grade", "attempt", c.params.id, { question_id: c.params.qid, points: b.points });
  return redirect(`/admin/grading/${c.params.id}?ok=graded`);
}

export { raw };
