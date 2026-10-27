// Localization, video lessons, manual grading, scheduling, admin tooling,
// recommendations, analytics, SEO endpoints.
import { test } from "node:test";
import assert from "node:assert/strict";
import manifest from "../../../../shared/supported-locales.json" with { type: "json" };
import worker from "../../src/index.js";
import { makeEnv, Client, registeredLearner, publishCourse, correctResponses, approveA1Videos, approveReviews } from "../helpers.js";

test("language inventory matches the Enterprise Portal and supports RTL", async () => {
  const env = makeEnv();
  const c = new Client(env);
  let r = await c.get("/");
  const options = [...r.text.matchAll(/<option value="([^"]+)" lang=/g)].map((m) => m[1]);
  const expected = manifest.enabledUiLocales.filter((x) => x !== "auto");
  assert.deepEqual([...options].sort(), [...expected].sort(), "selector lists exactly the Portal's enabled locales");
  assert.equal(options.length, 60);
  r = await c.get("/?lang=ar");
  assert.match(r.text, /<html lang="ar" dir="rtl"/);
  assert.ok(r.headers.getSetCookie().some((s) => s.startsWith("aca_lang=ar")));
  r = await c.get("/courses");
  assert.match(r.text, /<html lang="ar" dir="rtl"/, "language choice persists");
  const neg = new Client(env);
  r = await neg.get("/", { headers: { "accept-language": "pt-PT,pt;q=0.9,en;q=0.5" } });
  assert.match(r.text, /<html lang="pt-BR"/);
  r = await neg.get("/?lang=xx-INVALID", { headers: { "accept-language": "pt-PT" } });
  assert.match(r.text, /<html lang="pt-BR"/, "unknown locales are ignored");
});

test("content translations: machine drafts are labelled, exams use reviewed only", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO content_translations (entity_type, entity_id, field, locale, value, status, updated_at) VALUES ('course','crs_a1','title','es','Introducción a la IA en la agricultura','machine',?)").bind(now).run();
  const qid = "q_a1x_e2";
  await env.DB.prepare("INSERT INTO content_translations (entity_type, entity_id, field, locale, value, status, updated_at) VALUES ('question',?,'prompt','es','PREGUNTA SIN REVISAR','machine',?)").bind(qid, now).run();
  const c = new Client(env);
  let r = await c.get("/courses/introduction-to-ai-in-agriculture?lang=es");
  assert.match(r.text, /Introducción a la IA en la agricultura/);
  assert.match(r.text, /Machine-translated|automática|traduc/i);
  // Certification exams never show unreviewed translations, and an open attempt
  // keeps the wording it started with.
  const u = await registeredLearner(env);
  await u.get("/?lang=es");
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  await env.DB.prepare("UPDATE lessons SET is_required = 0 WHERE course_id = 'crs_a1'").run();
  const examQs = (await env.DB.prepare("SELECT DISTINCT q.id FROM questions q JOIN assessment_rules r ON r.bank_id = q.bank_id WHERE r.assessment_id = 'asm_a1_exam'").all()).results.map((x) => x.id);
  for (const id of examQs) await env.DB.prepare("INSERT OR REPLACE INTO content_translations (entity_type, entity_id, field, locale, value, status, updated_at) VALUES ('question',?,'prompt','es','PREGUNTA SIN REVISAR','machine',?)").bind(id, now).run();
  r = await u.post("/assessments/asm_a1_exam/start", {});
  let attemptId = r.location.split("/").pop();
  r = await u.get(`/attempts/${attemptId}`);
  assert.doesNotMatch(r.text, /PREGUNTA SIN REVISAR/);
  await u.post(`/attempts/${attemptId}/submit`, {});
  await env.DB.prepare("UPDATE attempts SET submitted_at = '2026-01-01T00:00:00.000Z' WHERE id = ?").bind(attemptId).run();
  await env.DB.prepare("UPDATE content_translations SET status = 'reviewed', value = 'PREGUNTA REVISADA' WHERE entity_type = 'question'").run();
  r = await u.post("/assessments/asm_a1_exam/start", {});
  attemptId = r.location.split("/").pop();
  r = await u.get(`/attempts/${attemptId}`);
  assert.match(r.text, /PREGUNTA REVISADA/);
  await env.DB.prepare("UPDATE content_translations SET value = 'PREGUNTA CAMBIADA' WHERE entity_type = 'question'").run();
  r = await u.get(`/attempts/${attemptId}`);
  assert.match(r.text, /PREGUNTA REVISADA/, "translation edits during an attempt do not change it");
  assert.doesNotMatch(r.text, /PREGUNTA CAMBIADA/);
});

test("approved videos render a player and auto-complete at 90% watched", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  await env.DB.prepare("UPDATE video_assets SET status='approved', duration_seconds=200, mp4_url='https://media.example/a1.mp4', hls_url='https://media.example/a1.m3u8' WHERE id='vid_a1_data'").run();
  await env.DB.prepare("UPDATE lessons SET type='video' WHERE id='les_a1_data'").run();
  await env.DB.prepare("INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES ('cap1','vid_a1_data','en','English','WEBVTT\n\n00:00.000 --> 00:02.000\nHello','reviewed',?)").bind(new Date().toISOString()).run();
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  let r = await u.get("/learn/introduction-to-ai-in-agriculture/data-the-raw-material");
  assert.match(r.text, /<video controls playsinline/);
  assert.match(r.text, /application\/vnd\.apple\.mpegurl/);
  assert.match(r.text, /<track kind="captions" src="\/captions\/cap1\.vtt"/);
  assert.match(r.text, /data-speed/);
  // Captions are lesson material: enrolled learners only, never shared-cached.
  r = await u.get("/captions/cap1.vtt");
  assert.equal(r.headers.get("content-type"), "text/vtt; charset=utf-8");
  assert.equal(r.headers.get("cache-control"), "private, no-store");
  r = await new Client(env).get("/captions/cap1.vtt");
  assert.notEqual(r.headers.get("content-type"), "text/vtt; charset=utf-8", "anonymous visitors get no captions");
  // Unapproved videos never render a player.
  r = await u.get("/learn/introduction-to-ai-in-agriculture/welcome");
  assert.doesNotMatch(r.text, /<video/);
  assert.match(r.text, /Instructor video in production/);
  // Watch-to-complete lessons offer no "Mark as complete" button.
  r = await u.get("/learn/introduction-to-ai-in-agriculture/data-the-raw-material");
  assert.doesNotMatch(r.text, /data-complete-form/);
  assert.match(r.text, /completes automatically when you(?:'|&#39;)ve watched most of the video/);
  // A forged report of 95%, an explicit completion and the completion form are all refused.
  await u.postJson("/api/progress", { lessonId: "les_a1_data", position: 0, duration: 200, playing: true });
  await u.postJson("/api/progress", { lessonId: "les_a1_data", position: 190, duration: 200, playing: true, complete: true });
  r = await u.post("/learn/introduction-to-ai-in-agriculture/data-the-raw-material/complete", {});
  assert.match(r.location, /\?watch=1$/);
  let p = await env.DB.prepare("SELECT * FROM lesson_progress WHERE lesson_id='les_a1_data'").first();
  assert.equal(p.status, "started", "completion requires server-measured watching");
  r = await u.get(r.location);
  assert.match(r.text, /Watch the video to complete this lesson/);
  // Heartbeats in (server-measured) real time at 2× speed complete it at 90%.
  await u.postJson("/api/progress", { lessonId: "les_a1_data", position: 0, playing: true });
  for (let t = 10; t <= 180; t += 10) {
    await env.DB.prepare("UPDATE video_watch SET last_beat_at = ? WHERE lesson_id = 'les_a1_data'").bind(new Date(Date.now() - 5000).toISOString()).run();
    await u.postJson("/api/progress", { lessonId: "les_a1_data", position: t, playing: true });
  }
  p = await env.DB.prepare("SELECT * FROM lesson_progress WHERE lesson_id='les_a1_data'").first();
  assert.equal(p.status, "completed");
  assert.ok(p.completed_at);
  // Resume position on another device: the page carries the saved start.
  await env.DB.prepare("UPDATE lesson_progress SET status='started', completed_at=NULL, position_seconds=73 WHERE lesson_id='les_a1_data'").run();
  const otherDevice = new Client(env);
  await otherDevice.get("/login");
  await otherDevice.post("/login", { email: u.email, password: u.password });
  r = await otherDevice.get("/learn/introduction-to-ai-in-agriculture/data-the-raw-material");
  assert.match(r.text, /data-start="73"/);
});

test("manual grading: pending review, reviewer grade, then final result", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare("INSERT INTO question_banks (id, course_id, title, created_at, updated_at) VALUES ('bnk_m','crs_a1','manual',?,?)").bind(now, now),
    env.DB.prepare(
      "INSERT INTO questions (id, bank_id, type, difficulty, prompt, data_json, answer_json, grading, points, rubric, status, created_at, updated_at) VALUES ('q_m','bnk_m','short_answer','medium','Explain drift.','{\"max_length\":600}','{\"accepted\":[]}','manual',2,'Mentions changing conditions','active',?,?)",
    ).bind(now, now),
    env.DB.prepare("INSERT INTO assessments (id, course_id, kind, title, passing_score, feedback_policy, status, created_at, updated_at) VALUES ('asm_m','crs_a1','quiz','Manual quiz',50,'full','active',?,?)").bind(now, now),
    env.DB.prepare("INSERT INTO assessment_rules (id, assessment_id, bank_id, draw_count) VALUES ('rul_m','asm_m','bnk_m',1)"),
  ]);
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  let r = await u.post("/assessments/asm_m/start", {});
  const attemptId = r.location.split("/").pop();
  await u.post(`/attempts/${attemptId}/submit`, { "q[q_m]": "Conditions change so past data stops representing the present." });
  let a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a.status, "pending_review");
  r = await u.get(`/attempts/${attemptId}`);
  assert.match(r.text, /Submitted for grading/);

  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  r = await admin.get("/admin/grading");
  assert.match(r.text, new RegExp(attemptId));
  r = await admin.post(`/admin/grading/${attemptId}/q_m`, { points: "2", comment: "Good explanation." });
  assert.equal(r.status, 303);
  a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a.status, "graded");
  assert.equal(a.score_pct, 100);
  r = await u.get(`/attempts/${attemptId}`);
  assert.match(r.text, /Good explanation\./);
});

test("scheduled jobs publish courses and auto-submit expired exams", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  await approveA1Videos(env, admin);
  await approveReviews(admin, "crs_a1");
  const past = new Date(Date.now() - 60_000).toISOString();
  await env.DB.prepare("UPDATE courses SET status='scheduled', scheduled_at=? WHERE id='crs_a1'").bind(past).run();
  await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil: (p) => p });
  assert.equal((await env.DB.prepare("SELECT status FROM courses WHERE id='crs_a1'").first()).status, "published");

  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  await env.DB.prepare("UPDATE lessons SET is_required = 0 WHERE course_id='crs_a1'").run();
  let r = await u.post("/assessments/asm_a1_exam/start", {});
  const attemptId = r.location.split("/").pop();
  const answers = await correctResponses(env, attemptId);
  await u.request("POST", `/api/attempts/${attemptId}/save`, { body: answers, headers: { accept: "application/json", "x-csrf-token": u.csrf } });
  // Time passes beyond the deadline: saving is refused, the cron grades saved answers.
  await env.DB.prepare("UPDATE attempts SET deadline_at = ? WHERE id = ?").bind(new Date(Date.now() - 10 * 60_000).toISOString(), attemptId).run();
  r = await u.request("POST", `/api/attempts/${attemptId}/save`, { body: answers, headers: { accept: "application/json", "x-csrf-token": u.csrf } });
  assert.equal(r.status, 409);
  await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil: (p) => p });
  const a = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a.status, "graded");
  assert.equal(a.passed, 1);
});

test("publishing is blocked until readiness checks pass", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  let r = await admin.post("/admin/courses/crs_b1/status", { status: "published" });
  assert.match(decodeURIComponent(r.location), /Readiness checks must pass/);
  assert.equal((await env.DB.prepare("SELECT status FROM courses WHERE id='crs_b1'").first()).status, "draft");
  r = await admin.post("/admin/courses/crs_a1/status", { status: "scheduled", scheduled_at: "2026-10-29T15:00" });
  assert.match(decodeURIComponent(r.location), /Readiness checks must pass/, "A1 cannot be scheduled before reviews and videos");
  await approveA1Videos(env, admin);
  await approveReviews(admin, "crs_a1");
  r = await admin.post("/admin/courses/crs_a1/status", { status: "scheduled", scheduled_at: "2026-10-29T15:00" });
  const c = await env.DB.prepare("SELECT status, scheduled_at FROM courses WHERE id='crs_a1'").first();
  assert.equal(c.status, "scheduled");
  assert.equal(c.scheduled_at, "2026-10-29T15:00:00.000Z");
});

test("admin question editor round-trips every question type", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  const cases = [
    { type: "single", lines: "Red\n* Near-infrared\nBlue" },
    { type: "multiple", lines: "* Weather\n* Satellites\nRumors" },
    { type: "true_false", tf: "false" },
    { type: "matching", lines: "Regression => Predicts a number\nClassification => Assigns a category\n=> Distractor" },
    { type: "ordering", lines: "Sense\nPredict\nRecommend\nVerify" },
    { type: "short_answer", lines: "NDVI\nnormalized difference vegetation index", match: "exact" },
  ];
  for (const k of cases) {
    const r = await admin.post("/admin/banks/bnk_a1_m1/questions", { prompt: `Prompt ${k.type}`, difficulty: "easy", points: "1", status: "active", grading: "auto", ...k });
    assert.equal(r.status, 303, `${k.type} saved`);
    assert.doesNotMatch(r.location, /err=/, `${k.type}: ${r.location}`);
  }
  const m = await env.DB.prepare("SELECT * FROM questions WHERE prompt = 'Prompt matching'").first();
  const data = JSON.parse(m.data_json);
  assert.equal(data.left.length, 2);
  assert.equal(data.right.length, 3, "distractor kept");
  let r = await admin.post("/admin/banks/bnk_a1_m1/questions", { type: "single", prompt: "bad", lines: "* A\n* B" });
  assert.match(decodeURIComponent(r.location), /exactly one correct/);
});

test("translation overrides change UI copy without a deployment", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  let r = await admin.post("/admin/translations/ui", { locale: "en", key: "nav.courses", value: "Course library", status: "reviewed" });
  assert.equal(r.status, 303);
  r = await new Client(env).get("/");
  assert.match(r.text, />Course library</);
  r = await admin.post("/admin/translations/ui", { locale: "en", key: "dash.hello", value: "Hi there", status: "reviewed" });
  assert.match(decodeURIComponent(r.location), /placeholders/, "placeholders are enforced");
  r = await admin.post("/admin/translations/ui", { locale: "en", key: "home.title_html", value: 'Learn <img src=x onerror="alert(1)">', status: "reviewed" });
  assert.match(decodeURIComponent(r.location), /Only <em>/, "unsafe markup rejected in HTML strings");
});

test("analytics show real recorded figures and empty states", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  let r = await admin.get("/admin");
  assert.equal(r.status, 200);
  assert.match(r.text, /Registered learners/);
  await publishCourse(env, "crs_a1");
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  r = await admin.get("/admin");
  const row = /Introduction to Artificial Intelligence in Agriculture<\/a>[\s\S]*?<\/tr>/.exec(r.text)[0];
  assert.match(row, /<td>1<\/td>/, "one enrollment recorded");
});

test("recommendations follow the learner's role path", async () => {
  const env = makeEnv();
  await env.DB.prepare("UPDATE courses SET status='published' WHERE id IN ('crs_a1','crs_d1','crs_b2')").run();
  const c = new Client(env);
  await c.get("/register");
  await c.post("/register", { display_name: "Op", email: "op@academy.test", password: "operator passphrase", accept_terms: "1", professional_role: "operator" });
  const r = await c.get("/dashboard");
  assert.match(r.text, /Part of the learning path for your role/);
});

test("SEO endpoints: sitemap, robots, structured data, health", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const c = new Client(env);
  let r = await c.get("/sitemap.xml");
  assert.match(r.text, /<loc>https:\/\/academy\.test\/courses\/introduction-to-ai-in-agriculture<\/loc>/);
  assert.match(r.text, /hreflang="ar"/);
  assert.doesNotMatch(r.text, /agricultural-robotics/, "draft courses are not in the sitemap");
  r = await c.get("/robots.txt");
  assert.match(r.text, /Disallow: \//, "non-production environments are not indexed");
  const prod = makeEnv({ ENVIRONMENT: "production" });
  r = await new Client(prod).get("/robots.txt");
  assert.match(r.text, /Sitemap: https:\/\/academy\.test\/sitemap\.xml/);
  r = await c.get("/courses/introduction-to-ai-in-agriculture");
  assert.match(r.text, /"@type":"Course"/);
  assert.match(r.text, /<link rel="canonical" href="https:\/\/academy\.test\/courses\/introduction-to-ai-in-agriculture">/);
  r = await c.get("/healthz");
  const h = JSON.parse(r.text);
  assert.equal(h.ok, true);
  assert.equal(h.languages, 60);
  assert.equal(h.certificate_signing, "configured");
  r = await c.get("/courses/agricultural-robotics");
  assert.equal(r.status, 404, "draft courses are hidden from the public");
});

test("language support is described honestly: selectable, translated, reviewed, fallback", async () => {
  const env = makeEnv();
  const anon = new Client(env);
  // English: no notice. Machine-prepared catalog: marked as unreviewed. No catalog: English fallback, said plainly.
  let r = await anon.get("/?lang=en");
  assert.doesNotMatch(r.text, /class="lang-notice/);
  r = await anon.get("/?lang=es");
  assert.match(r.text, /class="lang-notice[^]*traducido automáticamente|class="lang-notice[^]*tradujo automáticamente/);
  r = await anon.get("/?lang=de");
  assert.match(r.text, /class="lang-notice[^]*German isn(?:'|&#39;)t translated yet, so the Academy is shown in English for now/);
  // The page is written in English, so it is marked and laid out as English; the choice stays selected.
  assert.match(r.text, /<html lang="en" dir="ltr"/);
  assert.match(r.text, /<option value="de" lang="de" dir="ltr" selected>/);
  // The picker separates translated interfaces from English-for-now ones.
  assert.match(r.text, /<optgroup label="Interface translated">/);
  assert.match(r.text, /<optgroup label="Interface in English for now">/);
  // The home page does not claim 60 translated languages.
  r = await anon.get("/?lang=en");
  assert.doesNotMatch(r.text, /Learn in any of \d+ languages|in your language/);
  assert.match(r.text, /interface translated into 6/);
  // The language support page lists every language with its real status.
  r = await anon.get("/languages");
  assert.equal(r.status, 200);
  const rows = r.text.match(/<tr><th scope="row">/g) || [];
  assert.equal(rows.length, 60);
  assert.equal((r.text.match(/">English for now<\/span>/g) || []).length, 54);
  assert.equal((r.text.match(/">Automatic translation, not yet reviewed<\/span>/g) || []).length, 5);
  assert.match(r.text, /Original \(English\)/);
  // A reviewed course translation is counted; machine drafts are not.
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO content_translations (entity_type, entity_id, field, locale, value, status, updated_at) VALUES ('course','crs_a1','title','pt-BR','Introdução à IA na Agricultura','reviewed',?), ('course','crs_a1','title','fr-FR','Introduction à l’IA','machine',?)").bind(now, now).run();
  r = await anon.get("/languages");
  const row = (code) => new RegExp(`<th scope="row"><span lang="${code}"[^]*?</tr>`).exec(r.text)[0];
  assert.match(row("pt-BR"), /English \+ 1 reviewed course translation/);
  assert.doesNotMatch(row("fr-FR"), /reviewed course translation/, "machine drafts are not counted");
  r = await anon.get("/sitemap.xml");
  assert.match(r.text, /\/languages</);
});
