// Unit tests: escaping, markdown sanitization, passwords, grading, i18n
// catalog integrity, router, credential IDs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { html, raw, safeUrl } from "../../src/lib/html.js";
import { renderMarkdown } from "../../src/lib/markdown.js";
import { hashPassword, verifyPassword, passwordProblem, can } from "../../src/lib/security.js";
import { credentialId, shuffle } from "../../src/lib/util.js";
import { scoreResponse } from "../../src/services/assessments.js";
import { fromEditorLines, toEditorLines } from "../../src/pages/admin/assessments.js";
import { CATALOGS } from "../../src/i18n/index.js";
import { LOCALES, matchLocale, negotiate, makeTranslator } from "../../src/lib/i18n.js";
import { Router } from "../../src/lib/router.js";

const src = join(dirname(fileURLToPath(import.meta.url)), "../../src");

test("html templates escape by default", () => {
  const evil = `<img src=x onerror="alert(1)">'`;
  assert.equal(html`<p>${evil}</p>`.toString(), "<p>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;</p>");
  assert.equal(html`<p>${raw("<b>ok</b>")}</p>`.toString(), "<p><b>ok</b></p>");
  assert.equal(html`${[1, "<", null, false]}`.toString(), "1&lt;");
  assert.equal(safeUrl("javascript:alert(1)"), "#");
  assert.equal(safeUrl("//evil.example/x"), "#");
  assert.equal(safeUrl("/courses"), "/courses");
});

test("markdown renders safely", () => {
  const { html: out, toc } = renderMarkdown(`## Heading <b>x</b>\n\nText with [link](javascript:alert(1)) and [ok](https://example.org) and <script>bad()</script>.\n\n- **bold** item\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n> **Key idea:** callout`);
  assert.doesNotMatch(out, /<script>|<b>x<\/b>|javascript:/);
  assert.match(out, /&lt;script&gt;/);
  assert.match(out, /href="#"/);
  assert.match(out, /href="https:\/\/example\.org" rel="noopener noreferrer" target="_blank"/);
  assert.match(out, /<table>/);
  assert.match(out, /class="callout callout-key-idea"/);
  assert.equal(toc[0].level, 3);
});

test("password hashing and policy", async () => {
  const h = await hashPassword("a strong passphrase");
  assert.match(h, /^pbkdf2_sha256\$100000\$/);
  assert.equal(await verifyPassword("a strong passphrase", h), true);
  assert.equal(await verifyPassword("a strong passphrasf", h), false);
  assert.notEqual(await hashPassword("a strong passphrase"), h, "salted");
  assert.equal(passwordProblem("short"), "auth.error.password_short");
  assert.equal(passwordProblem("aaaaaaaaaaaa"), "auth.error.password_weak");
  assert.equal(passwordProblem("password123456"), "auth.error.password_weak");
  assert.equal(passwordProblem("maria-loves-maize", "maria@x.org"), "auth.error.password_weak");
  assert.equal(passwordProblem("irrigation at dawn"), null);
});

test("role permissions", () => {
  assert.ok(can(["super_admin"], "anything"));
  assert.ok(can(["academy_admin"], "certificates.manage"));
  assert.ok(!can(["instructor"], "certificates.manage"));
  assert.ok(can(["instructor"], "grading"));
  assert.ok(!can(["content_editor"], "courses.publish"));
  assert.ok(!can(["learner"], "admin.access"));
});

test("server-side scoring for every question type", () => {
  const q = (type, answer, extra = {}) => ({ type, grading: "auto", answer_json: JSON.stringify(answer), ...extra });
  assert.equal(scoreResponse(q("single", { correct: ["a"] }), "a").fraction, 1);
  assert.equal(scoreResponse(q("single", { correct: ["a"] }), "b").fraction, 0);
  assert.equal(scoreResponse(q("multiple", { correct: ["a", "b"] }), ["a", "b"]).fraction, 1);
  assert.equal(scoreResponse(q("multiple", { correct: ["a", "b"] }), ["a"]).fraction, 0.5);
  assert.equal(scoreResponse(q("multiple", { correct: ["a", "b"] }), ["a", "c"]).fraction, 0, "wrong picks cancel right ones");
  assert.equal(scoreResponse(q("multiple", { correct: ["a", "b"] }), ["a", "b", "c", "d"]).fraction, 0, "selecting everything is not rewarded");
  assert.equal(scoreResponse(q("true_false", { value: false }), false).fraction, 1);
  assert.equal(scoreResponse(q("matching", { pairs: { l1: "r1", l2: "r2" } }), { l1: "r1", l2: "r1" }).fraction, 0.5);
  assert.equal(scoreResponse(q("ordering", { order: ["a", "b", "c", "d"] }), ["a", "b", "d", "c"]).fraction, 0.5);
  assert.equal(scoreResponse(q("short_answer", { accepted: ["NDVI"], match: "exact" }), "  ndvi. ").fraction, 1);
  assert.equal(scoreResponse(q("short_answer", { accepted: ["drift"], match: "contains" }), "model drift happens").fraction, 1);
  assert.equal(scoreResponse(q("single", { correct: ["a"] }), null).fraction, 0);
  assert.equal(scoreResponse({ type: "short_answer", grading: "manual", answer_json: "{}" }, "x").manual, true);
});

test("admin question line format round-trips", () => {
  const built = fromEditorLines("multiple", "* A\nB\n* C", null);
  assert.equal(built.answer.correct.length, 2);
  const q = { type: "multiple", data_json: JSON.stringify(built.data), answer_json: JSON.stringify(built.answer) };
  assert.equal(toEditorLines(q), "* A\nB\n* C");
  const rebuilt = fromEditorLines("multiple", "* A\nB\n* C\nD", q);
  assert.deepEqual(rebuilt.data.options.slice(0, 3).map((o) => o.id), built.data.options.map((o) => o.id), "existing option ids are reused");
  assert.throws(() => fromEditorLines("single", "A\nB", null), /correct/);
  assert.throws(() => fromEditorLines("matching", "A\nB", null), /=>/);
});

test("credential identifiers and shuffling", () => {
  const ids = new Set(Array.from({ length: 2000 }, credentialId));
  assert.equal(ids.size, 2000);
  for (const id of [...ids].slice(0, 50)) assert.match(id, /^AGA-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/);
  const arr = [1, 2, 3, 4, 5, 6];
  const s = shuffle(arr);
  assert.deepEqual([...s].sort(), arr);
  assert.deepEqual(arr, [1, 2, 3, 4, 5, 6], "input not mutated");
});

test("locale negotiation", () => {
  assert.equal(LOCALES.length, 60);
  assert.deepEqual(LOCALES.filter((l) => l.dir === "rtl").map((l) => l.code).sort(), ["ar", "fa", "ur"]);
  assert.equal(matchLocale("pt"), "pt-BR");
  assert.equal(matchLocale("fr-CA"), "fr-FR");
  assert.equal(matchLocale("nb-NO"), "no");
  assert.equal(matchLocale("zh-Hans"), "zh");
  assert.equal(matchLocale("klingon"), null);
  assert.equal(negotiate("sw-KE,sw;q=0.9"), "sw");
  assert.equal(negotiate(""), "en");
  const t = makeTranslator("en", new Map());
  assert.equal(t("progress.percent_complete", { pct: 40 }), "40% complete");
  assert.equal(t("missing.key"), "missing.key");
});

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? sourceFiles(p) : p.endsWith(".js") ? [p] : [];
  });
}

test("every translation key used in code exists in the English catalog", () => {
  const en = CATALOGS.en;
  const missing = new Set();
  for (const file of sourceFiles(src)) {
    const code = readFileSync(file, "utf8");
    for (const m of code.matchAll(/\bt\(\s*"([a-z0-9_.-]+)"/g)) if (!(m[1] in en)) missing.add(`${m[1]} (${file.split("/src/")[1]})`);
  }
  // Keys built dynamically from known value sets.
  const families = {
    "topic.": ["ai-foundations", "data", "machine-learning", "remote-sensing", "precision-agriculture", "irrigation", "crop-monitoring", "risk", "ethics", "computer-vision", "robotics", "agents", "platform", "api"],
    "role.": ["grower", "agronomist", "farm_manager", "operator", "student", "researcher", "developer", "advisor", "other"],
    "lesson.type.": ["video", "text", "interactive", "reading", "resource", "exercise", "quiz", "case_study", "assignment"],
    "level.": ["beginner", "intermediate", "advanced"],
    "status.": ["draft", "review", "scheduled", "published", "archived"],
    "assess.status.": ["in_progress", "pending_review", "graded", "expired"],
    "assess.item.": ["correct", "incorrect", "partial", "pending"],
    "notify.": ["enrollment", "course_complete", "certificate"],
    "history.": ["registered", "enrolled", "lesson_completed", "course_completed", "quiz_passed", "quiz_failed", "exam_passed", "exam_failed", "certificate_issued"],
    "contact.topic.": ["account", "course", "certificate", "accessibility", "partnership", "privacy", "other"],
  };
  for (const [prefix, vals] of Object.entries(families)) for (const v of vals) if (!(`${prefix}${v}` in en)) missing.add(prefix + v);
  for (const k of ["score", "correctness", "full"]) if (!(`assess.feedback.${k}.short` in en)) missing.add(`assess.feedback.${k}.short`);
  for (const code of ["first_enrollment", "first_lesson", "ten_lessons", "first_quiz_pass", "perfect_score", "first_course", "first_certificate", "three_certificates"])
    for (const s of ["title", "hint"]) if (!(`ach.${code}.${s}` in en)) missing.add(`ach.${code}.${s}`);
  for (const tpl of ["verify_email", "password_reset", "password_changed", "account_deleted", "welcome", "enrollment", "course_complete", "exam_passed", "exam_failed", "certificate_issued", "course_reminder"])
    for (const s of ["subject", "body"]) if (!(`email.${tpl}.${s}` in en)) missing.add(`email.${tpl}.${s}`);
  for (const k of ["bad_request", "auth_required", "forbidden", "not_found", "too_large", "rate_limited", "server_error"])
    for (const s of ["title", "body"]) if (!(`error.${k}.${s}` in en)) missing.add(`error.${k}.${s}`);
  assert.deepEqual([...missing], []);
});

test("translated catalogs keep placeholders and markup intact", () => {
  const en = CATALOGS.en;
  const ph = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
  const tags = (s) => (s.match(/<\/?[a-z]+/g) || []).sort().join();
  for (const [code, cat] of Object.entries(CATALOGS)) {
    if (code === "en") continue;
    assert.ok(LOCALES.some((l) => l.code === code), `${code} is a supported locale`);
    for (const [k, v] of Object.entries(cat)) {
      assert.ok(k in en, `${code}: unknown key ${k}`);
      assert.equal(ph(v), ph(en[k]), `${code}: placeholders differ for ${k}`);
      assert.equal(tags(v), tags(en[k]), `${code}: markup differs for ${k}`);
      assert.ok(v.trim().length > 0, `${code}: empty value for ${k}`);
    }
  }
});

test("router matches params, methods and 405s", () => {
  const r = new Router();
  r.get("/learn/:course/:lesson", () => "lesson");
  r.post("/learn/:course/:lesson/complete", () => "complete");
  const m = r.match("GET", "/learn/a%20b/c");
  assert.deepEqual(m.params, { course: "a b", lesson: "c" });
  assert.equal(r.match("HEAD", "/learn/a/c").route.handler(), "lesson");
  assert.equal(r.match("GET", "/learn/a/c/complete").methodNotAllowed, true);
  assert.equal(r.match("GET", "/nope"), null);
});
