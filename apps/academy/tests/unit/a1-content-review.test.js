// Course A1's content and question bank pass the automated pre-review
// (scripts/review-a1.mjs), and migration 0010 brings databases seeded before
// the corrections up to date without touching a published course.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { reviewA1, report } from "../../scripts/review-a1.mjs";
import { makeEnv } from "../helpers.js";

const migrations = join(dirname(fileURLToPath(import.meta.url)), "../../migrations");
const up = readFileSync(join(migrations, "0010_a1_question_fixes.sql"), "utf8");
const down = readFileSync(join(migrations, "down/0010_a1_question_fixes.down.sql"), "utf8");

test("A1 passes the automated content and assessment review", () => {
  const r = reviewA1();
  assert.deepEqual(r.fails, [], report(r));
});

test("the review catches the defects it was written for", () => {
  const course = { modules: [{ id: "m", lessons: [{ id: "l1", type: "video", body: "word ".repeat(200), minutes: 5, title: "L1" }] }], assessments: [{ id: "a", kind: "exam", rules: [{ bank: "b", count: 2 }] }], banks: [{ id: "b", questions: [
    { id: "q1", type: "multiple", difficulty: "easy", lesson: "l1", prompt: "Pick", options: [["x", true], ["y", true], ["z", true]], explanation: "All of these are right answers here." },
    { id: "q2", type: "single", difficulty: "easy", lesson: "l1", prompt: "Other", options: [["x", true], ["y", false], ["z", false]], explanation: "Short." },
  ] }] };
  const fails = reviewA1(course).fails.join("\n");
  assert.match(fails, /q1: 3 of 3 options correct/);
  assert.match(fails, /q2: explanation missing or too short/);
});

const answer = async (env, table, id) => JSON.parse((await env.DB.prepare(`SELECT answer_json FROM ${table} WHERE id = ?`).bind(id).first()).answer_json);

test("migration 0010 corrects a bank seeded before the fix, live and draft alike", async () => {
  const env = makeEnv();
  await env.DB.exec(down); // the state of a database seeded before the corrections
  for (const table of ["questions", "draft_questions"]) assert.equal((await answer(env, table, "q_a1x_e8")).correct.length, 4, "every option was marked correct");
  await env.DB.exec(up);
  for (const table of ["questions", "draft_questions"]) {
    assert.deepEqual((await answer(env, table, "q_a1x_e8")).correct, ["o1", "o2", "o3", "o4"]);
    const data = JSON.parse((await env.DB.prepare(`SELECT data_json FROM ${table} WHERE id = 'q_a1x_e8'`).first()).data_json);
    assert.equal(data.options.length, 5, "a distractor was added");
    const etc = await env.DB.prepare(`SELECT explanation FROM ${table} WHERE id = 'q_a1m3_3'`).first();
    assert.match(etc.explanation, /crop coefficient \(Kc\) adjusts it/);
  }
});

test("migration 0010 never changes a published course's questions", async () => {
  const env = makeEnv();
  await env.DB.exec(down);
  await env.DB.prepare("UPDATE courses SET published_at = '2026-10-20T00:00:00.000Z' WHERE id = 'crs_a1'").run();
  await env.DB.exec(up);
  assert.equal((await answer(env, "questions", "q_a1x_e8")).correct.length, 4, "unchanged: publication froze it");
});
