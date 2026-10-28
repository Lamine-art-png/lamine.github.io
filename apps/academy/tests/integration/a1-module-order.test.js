// Regression: the four A1 modules must present all fourteen original videos
// in recording order, including after a live/draft production sort-order drift.
// The one-time repair never changes lesson identity, media or learner progress.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { makeEnv } from "../helpers.js";
import { getSyllabus } from "../../src/services/content.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const repair = readFileSync(join(root, "migrations/0013_a1_module_order.sql"), "utf8");
const expectedModules = ["mod_a1_1", "mod_a1_2", "mod_a1_3", "mod_a1_4"];
const expectedVideos = [
  "vid_a1_welcome", "vid_a1_what_is_ai", "vid_a1_why_now",
  "vid_a1_data", "vid_a1_models", "vid_a1_recommendations",
  "vid_a1_planning", "vid_a1_irrigation", "vid_a1_crop_health", "vid_a1_harvest",
  "vid_a1_limits", "vid_a1_data_rights", "vid_a1_exercise", "vid_a1_summary",
];

const rows = async (env, table) =>
  (await env.DB.prepare(`SELECT id, sort_order FROM ${table} WHERE course_id = 'crs_a1' ORDER BY sort_order, id`).all()).results;
const snapshot = async (env, table) =>
  (await env.DB.prepare(`SELECT * FROM ${table} ORDER BY 1`).all()).results;

async function rotate(env) {
  for (const table of ["modules", "draft_modules"]) {
    await env.DB.prepare(`UPDATE ${table} SET sort_order = CASE id
      WHEN 'mod_a1_1' THEN 4 WHEN 'mod_a1_2' THEN 1
      WHEN 'mod_a1_3' THEN 2 WHEN 'mod_a1_4' THEN 3 END
      WHERE course_id = 'crs_a1'`).run();
  }
}

test("A1 repair restores original videos 1-14 across all four modules without modifying lessons or progress", async () => {
  const env = makeEnv();
  await rotate(env);
  assert.deepEqual((await rows(env, "modules")).map((x) => x.id), [
    "mod_a1_2", "mod_a1_3", "mod_a1_4", "mod_a1_1",
  ], "reproduce the actual production screenshot");
  const before = await Promise.all(["lessons", "draft_lessons", "video_assets", "lesson_progress", "video_watch", "enrollments", "attempts", "certificates", "course_revisions", "course_reviews"]
    .map((table) => snapshot(env, table)));
  await env.DB.exec(repair);

  for (const table of ["modules", "draft_modules"]) {
    assert.deepEqual(await rows(env, table), expectedModules.map((id, i) => ({ id, sort_order: i + 1 })), table);
  }
  const syllabus = await getSyllabus(env, "crs_a1", "en");
  assert.deepEqual(syllabus.modules.map((m) => m.id), expectedModules);
  assert.equal(syllabus.lessons.length, 17);
  assert.deepEqual(syllabus.lessons.filter((l) => l.video_id).map((l) => l.video_id), expectedVideos);
  assert.deepEqual(syllabus.lessons.filter((l) => l.type === "quiz").map((l) => l.title), [
    "Module 1 quiz", "Module 2 quiz", "Module 3 quiz",
  ]);
  const after = await Promise.all(["lessons", "draft_lessons", "video_assets", "lesson_progress", "video_watch", "enrollments", "attempts", "certificates", "course_revisions", "course_reviews"]
    .map((table) => snapshot(env, table)));
  assert.deepEqual(after, before, "lesson/media/learner/review/certificate rows are untouched");

  const audit = (await env.DB.prepare("SELECT * FROM audit_log WHERE action = 'course.module_order_repair' AND entity_id = 'crs_a1'").all()).results;
  assert.equal(audit.length, 1);
  assert.equal(JSON.parse(audit[0].detail).scope, "A1 module positions only; lesson/video/progress rows unchanged");

  await env.DB.exec(repair);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM audit_log WHERE id = 'academy-a1-module-order-0013'").first()).n, 1, "re-running repair is idempotent");
});

test("A1 migration fails closed if the four known A1 modules are incomplete", async () => {
  const env = makeEnv();
  await rotate(env);
  await env.DB.prepare("DELETE FROM draft_modules WHERE id = 'mod_a1_4'").run();
  const liveBefore = await rows(env, "modules");
  await env.DB.exec(repair);
  assert.deepEqual(await rows(env, "modules"), liveBefore, "a partial draft must never silently overwrite the live course");
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM audit_log WHERE id = 'academy-a1-module-order-0013'").first()).n, 0);
});

test("fresh A1 curriculum remains correctly ordered and repair is a no-op", async () => {
  const env = makeEnv();
  const syllabus = await getSyllabus(env, "crs_a1", "en");
  assert.deepEqual(syllabus.modules.map((m) => m.id), expectedModules);
  assert.deepEqual(syllabus.lessons.filter((l) => l.video_id).map((l) => l.video_id), expectedVideos);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM audit_log WHERE id = 'academy-a1-module-order-0013'").first()).n, 0);
});
