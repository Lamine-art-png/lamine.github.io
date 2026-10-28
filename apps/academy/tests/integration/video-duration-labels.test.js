import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, A1_SLUG } from "../helpers.js";
import { getSyllabus } from "../../src/services/content.js";
import { lessonDuration } from "../../src/lib/util.js";

const t = (key, vars) => key === "duration.minutes" ? `${vars.n} min` : key;

test("video runtimes display exact mm:ss; text and quizzes keep editorial estimates", () => {
  assert.equal(lessonDuration({ video_id: "v1", video_duration_seconds: 96, est_minutes: 5 }, t), "1:36");
  assert.equal(lessonDuration({ video_id: "v2", video_duration_seconds: 168, est_minutes: 12 }, t), "2:48");
  assert.equal(lessonDuration({ video_id: "v3", video_duration_seconds: 3601, est_minutes: 65 }, t), "1:00:01");
  assert.equal(lessonDuration({ video_id: null, video_duration_seconds: null, est_minutes: 8 }, t), "8 min");
  assert.equal(lessonDuration({ video_id: "v4", video_duration_seconds: null, est_minutes: 14 }, t), "14 min");
  assert.equal(lessonDuration({ video_id: "v4", video_duration_seconds: -3, est_minutes: 14 }, t), "14 min");
});

test("the public A1 syllabus and the enrolled classroom use actual uploaded runtimes", async () => {
  const env = makeEnv();
  await env.DB.prepare("UPDATE video_assets SET duration_seconds = 96 WHERE id = 'vid_a1_welcome'").run();
  await env.DB.prepare("UPDATE video_assets SET duration_seconds = 168 WHERE id = 'vid_a1_what_is_ai'").run();
  const syllabus = await getSyllabus(env, "crs_a1", "en");
  const welcome = syllabus.lessons.find((l) => l.id === "les_a1_welcome");
  assert.equal(welcome.video_duration_seconds, 96);
  assert.equal(welcome.est_minutes, 5, "the real course study-time estimate is never rewritten");
  assert.equal(lessonDuration(welcome, t), "1:36");

  const anon = new Client(env);
  const catalog = await anon.get(`/courses/${A1_SLUG}`);
  assert.equal(catalog.status, 200);
  assert.match(catalog.text, /1:36/);
  assert.match(catalog.text, /2:48/);
  assert.match(catalog.text, /Module 1 quiz/);

  const admin = await registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
  const classroom = await admin.get(`/learn/${A1_SLUG}/welcome`);
  assert.equal(classroom.status, 200);
  assert.match(classroom.text, /1:36/);
  assert.match(classroom.text, /2:48/);
  assert.doesNotMatch(classroom.text, /Welcome to the course<[^>]*>5 min<\/span>/);
  assert.match(classroom.text, /Module 1 quiz/);
});
