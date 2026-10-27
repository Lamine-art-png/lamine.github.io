// Automated pre-review of Course A1's content and assessments, for the human
// reviewers' packet (docs/A1_APPROVAL_PACKAGE.md). It never approves anything:
// it checks what a machine can check and lists what a person must judge.
//   node scripts/review-a1.mjs            Markdown report on stdout
// Exit code 1 when a check fails (a defect a reviewer should not have to find).
import { A1 } from "../src/content/courses/a1.js";

const words = (s) => String(s || "").split(/\s+/).filter(Boolean).length;

export function reviewA1(course = A1) {
  const fails = [];
  const notes = [];
  const lessons = course.modules.flatMap((m) => m.lessons.map((l) => ({ ...l, module: m.id })));
  const lessonIds = new Set(lessons.map((l) => l.id));
  const banks = Object.fromEntries(course.banks.map((b) => [b.id, b]));
  const questions = course.banks.flatMap((b) => b.questions.map((q) => ({ ...q, bank: b.id })));

  // Questions: structure, single correct answer, explanation, link to a lesson.
  const prompts = new Map();
  for (const q of questions) {
    const kind = q.type === "case" ? q.baseType : q.type;
    if (["single", "multiple"].includes(kind)) {
      const correct = q.options.filter(([, ok]) => ok).length;
      if (q.options.length < 3) fails.push(`${q.id}: only ${q.options.length} options`);
      if (kind === "single" && correct !== 1) fails.push(`${q.id}: ${correct} correct options for a single-answer question`);
      if (kind === "multiple" && (correct < 1 || correct === q.options.length)) fails.push(`${q.id}: ${correct} of ${q.options.length} options correct`);
      if (new Set(q.options.map(([t]) => t.trim().toLowerCase())).size !== q.options.length) fails.push(`${q.id}: duplicate options`);
      if (q.options.some(([t]) => /\b(all|none) of the above\b/i.test(t))) notes.push(`${q.id}: uses "all/none of the above"`);
    } else if (kind === "true_false") {
      if (typeof q.answer !== "boolean") fails.push(`${q.id}: true/false answer missing`);
    } else if (kind === "ordering") {
      if (!(q.order?.length >= 3) || new Set(q.order).size !== q.order.length) fails.push(`${q.id}: ordering needs ≥3 distinct steps`);
    } else if (kind === "matching") {
      if (!(q.pairs?.length >= 3) || new Set(q.pairs.map(([a]) => a)).size !== q.pairs.length || new Set(q.pairs.map(([, b]) => b)).size !== q.pairs.length) fails.push(`${q.id}: matching needs ≥3 pairs, unique on both sides`);
    } else if (kind === "short_answer") {
      if (!q.accepted?.length) fails.push(`${q.id}: no accepted answer`);
      else notes.push(`${q.id}: short answer accepts only ${q.accepted.map((a) => `"${a}"`).join(", ")}; reviewer to check reasonable variants`);
    } else fails.push(`${q.id}: unknown question type ${q.type}`);
    if (q.type === "case" && !q.case) fails.push(`${q.id}: case question without its case`);
    if (words(q.explanation) < 6) fails.push(`${q.id}: explanation missing or too short to teach`);
    if (!["easy", "medium", "hard"].includes(q.difficulty)) fails.push(`${q.id}: difficulty "${q.difficulty}"`);
    if (q.lesson && !lessonIds.has(q.lesson)) fails.push(`${q.id}: refers to unknown lesson ${q.lesson}`);
    if (!q.lesson) notes.push(`${q.id}: not linked to a lesson`);
    const key = q.prompt.trim().toLowerCase();
    if (prompts.has(key)) fails.push(`${q.id}: same prompt as ${prompts.get(key)}`);
    prompts.set(key, q.id);
  }

  // Draw rules: each assessment can always be assembled, with room to vary.
  const rules = [];
  for (const a of course.assessments) {
    for (const r of a.rules) {
      const pool = (banks[r.bank]?.questions || []).filter((q) => !r.difficulty || q.difficulty === r.difficulty);
      rules.push({ assessment: a.id, bank: r.bank, difficulty: r.difficulty || "any", draw: r.count, pool: pool.length });
      if (pool.length < r.count) fails.push(`${a.id}: draws ${r.count} ${r.difficulty || ""} from ${r.bank}, which has ${pool.length}`);
    }
  }

  // Item-writing signals a reviewer should look at (not failures).
  const position = new Map();
  let longest = 0;
  const singleQs = questions.filter((x) => (x.type === "case" ? x.baseType : x.type) === "single");
  for (const q of singleQs) {
    const i = q.options.findIndex(([, ok]) => ok);
    position.set(i, (position.get(i) || 0) + 1);
    const lens = q.options.map(([t]) => t.length);
    if (lens[i] === Math.max(...lens) && lens.filter((n) => n === lens[i]).length === 1) longest++;
  }
  const singles = singleQs.length;

  // Coverage: which lessons the exam and quizzes test.
  const examBank = course.assessments.find((a) => a.kind === "exam")?.rules[0]?.bank;
  const examLessons = new Set((banks[examBank]?.questions || []).map((q) => q.lesson).filter(Boolean));
  const content = lessons.filter((l) => l.type !== "quiz");
  const untested = content.filter((l) => !questions.some((q) => q.lesson === l.id));

  // Lessons: text present, reading time plausible against the estimate.
  const lessonRows = content.map((l) => {
    const w = words(l.body);
    const readMin = Math.round(w / 200);
    if (w < 150) fails.push(`${l.id}: lesson text has only ${w} words`);
    return { id: l.id, title: l.title, minutes: l.minutes, words: w, readMin, video: l.type === "video" || Boolean(l.script) };
  });

  return { fails, notes, rules, position, longest, singles, examLessons, content, untested, lessonRows, questions };
}

export function report(r = reviewA1()) {
  const out = [];
  out.push(`### Automated content and assessment checks (${r.fails.length ? `**${r.fails.length} failure(s)**` : "all passed"})`, "");
  out.push(`- Lessons with text: ${r.content.length}; questions: ${r.questions.length} (${r.singles} single-answer).`);
  const types = {};
  for (const q of r.questions) types[q.type] = (types[q.type] || 0) + 1;
  out.push(`- Question types: ${Object.entries(types).map(([k, n]) => `${k} ${n}`).join(", ")}.`);
  out.push(`- Checked for every question: answer key well formed for its type (exactly one correct option for single-answer, at least one but not all for multiple-answer, boolean for true/false, unique steps and pairs for ordering and matching, accepted answers for short answer), a teaching explanation, a valid difficulty and lesson link, no duplicate prompt.`);
  out.push(`- Exam bank covers ${r.examLessons.size} of ${r.content.length} lessons. Lessons tested by no question: ${r.untested.map((l) => l.title).join("; ") || "none"}.`);
  out.push(`- Correct-answer position (single-answer): ${[...r.position.entries()].sort((a, b) => a[0] - b[0]).map(([i, n]) => `${"ABCDEF"[i]}=${n}`).join(", ")} (options are shuffled for learners, so position bias does not reach them).`);
  out.push(`- Correct answer is the uniquely longest option in ${r.longest} of ${r.singles} questions (${Math.round((100 * r.longest) / r.singles)}%). Above ~40% is a known cue for test-wise learners: reviewer to judge.`);
  out.push("", "| Assessment | Bank | Difficulty | Draw | Pool |", "|---|---|---|---|---|");
  for (const x of r.rules) out.push(`| ${x.assessment} | ${x.bank} | ${x.difficulty} | ${x.draw} | ${x.pool} |`);
  out.push("", "| Lesson | Est. min | Words | Reading min (200 wpm) | Narrated |", "|---|---|---|---|---|");
  for (const l of r.lessonRows) out.push(`| ${l.title} | ${l.minutes} | ${l.words} | ${l.readMin} | ${l.video ? "yes" : "no"} |`);
  if (r.fails.length) out.push("", "**Failures:**", ...r.fails.map((f) => `- ${f}`));
  if (r.notes.length) out.push("", "Notes for reviewers:", ...r.notes.map((n) => `- ${n}`));
  return out.join("\n");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const r = reviewA1();
  console.log(report(r));
  process.exit(r.fails.length ? 1 : 0);
}
