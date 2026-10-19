// The critical learner journey, end to end against persistent data:
// Register → Verify → (admin publishes) → Enroll → Learn → Complete lessons →
// Quizzes → Exam (fail, then pass) → Certificate → PDF → Verify → LinkedIn.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, lastEmail, tokenFrom, correctResponses, ORIGIN, approveA1Videos, approveReviews } from "../helpers.js";

const COURSE = "introduction-to-ai-in-agriculture";

test("critical learner journey with persistent backend data", async () => {
  const env = makeEnv();

  // ── The founder signs up; the bootstrap allow-list grants super_admin after verification.
  const admin = await registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
  const roles = (await env.DB.prepare("SELECT role FROM user_roles ur JOIN users u ON u.id = ur.user_id WHERE u.email = ?").bind("founder@academy.test").all()).results.map((r) => r.role);
  assert.ok(roles.includes("super_admin"), "bootstrap admin role granted after email verification");

  // The course starts in review: visible as upcoming, not enrollable.
  const anon = new Client(env);
  let r = await anon.get(`/courses/${COURSE}`);
  assert.equal(r.status, 200);
  assert.match(r.text, /Opens Oct 29, 2026/);
  assert.doesNotMatch(r.text, /action="\/courses\/[^"]+\/enroll"/);

  // Publication is blocked until mandatory reviews and instructor videos are approved.
  r = await admin.get("/admin/courses/crs_a1");
  assert.equal(r.status, 200);
  assert.match(r.text, /❌/, "A1 is not publishable before reviews and videos");
  r = await admin.post("/admin/courses/crs_a1/status", { status: "published" });
  assert.match(decodeURIComponent(r.location), /Readiness checks must pass/);
  assert.equal(await approveA1Videos(env, admin), 14, "every scripted lesson video approved with reviewed captions");
  await approveReviews(admin, "crs_a1");
  r = await admin.get("/admin/courses/crs_a1");
  assert.doesNotMatch(r.text, /❌/, "all readiness checks pass for A1");
  r = await admin.post("/admin/courses/crs_a1/status", { status: "published" });
  assert.equal(r.status, 303);
  assert.equal((await env.DB.prepare("SELECT status FROM courses WHERE id = 'crs_a1'").first()).status, "published");

  // ── A learner registers (unverified at first).
  const learner = new Client(env);
  await learner.get("/register?lang=pt-BR");
  r = await learner.post("/register", { display_name: "Maria da Silva", email: "maria@academy.test", password: "colheita segura 2026", locale: "pt-BR", accept_terms: "1", country: "BR", professional_role: "grower" });
  assert.equal(r.status, 303);
  assert.equal(r.location, "/dashboard?welcome=1");
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = 'maria@academy.test'").first();
  assert.equal(user.locale, "pt-BR");
  assert.equal(user.email_verified_at, null);
  assert.ok(user.password_hash.startsWith("pbkdf2_sha256$100000$"), "password stored as PBKDF2 hash");
  const verifyMail = await lastEmail(env, "maria@academy.test", "verify_email");
  assert.ok(verifyMail, "verification email queued");

  // ── Enroll.
  r = await learner.get(`/courses/${COURSE}`);
  assert.match(r.text, /action="\/courses\/introduction-to-ai-in-agriculture\/enroll"/);
  r = await learner.post(`/courses/${COURSE}/enroll`, {});
  assert.equal(r.status, 303);
  assert.equal(r.location, `/learn/${COURSE}`);
  r = await learner.post(`/courses/${COURSE}/enroll`, {});
  const enrollCount = await env.DB.prepare("SELECT COUNT(*) AS n FROM enrollments e JOIN users u ON u.id = e.user_id WHERE u.email = 'maria@academy.test'").first();
  assert.equal(enrollCount.n, 1, "double enrollment prevented");

  // ── Learn: resume goes to the first lesson; lessons render.
  r = await learner.get(`/learn/${COURSE}`);
  assert.equal(r.status, 302);
  assert.equal(r.location, `/learn/${COURSE}/welcome`);
  r = await learner.get(`/learn/${COURSE}/welcome`);
  assert.equal(r.status, 200);
  assert.match(r.text, /Introdução|Welcome to the course|Bem-vindo/);

  // Progress beacon (JSON API) saves a resume position, idempotently and monotonically.
  const lessons = (await env.DB.prepare("SELECT * FROM lessons WHERE course_id = 'crs_a1' ORDER BY sort_order").all()).results;
  const first = lessons[0];
  r = await learner.postJson("/api/progress", { lessonId: first.id, position: 42, scroll: 30, clientAt: "2026-10-30T10:00:05Z" });
  assert.equal(r.status, 200);
  r = await learner.postJson("/api/progress", { lessonId: first.id, position: 10, clientAt: "2026-10-30T10:00:01Z" });
  const lp = await env.DB.prepare("SELECT * FROM lesson_progress WHERE lesson_id = ? AND user_id = ?").bind(first.id, user.id).first();
  assert.equal(lp.position_seconds, 42, "stale offline report does not move the resume position backwards");
  assert.equal(lp.scroll_pct, 30);

  // Complete every non-quiz lesson through the form endpoint.
  for (const l of lessons.filter((x) => x.type !== "quiz")) {
    r = await learner.post(`/learn/${COURSE}/${l.slug}/complete`, {});
    assert.equal(r.status, 303, `complete ${l.slug}`);
  }
  let enr = await env.DB.prepare("SELECT * FROM enrollments WHERE user_id = ?").bind(user.id).first();
  assert.ok(enr.progress_pct > 0 && enr.progress_pct < 100, `progress recorded (${enr.progress_pct}%)`);

  // The exam stays locked until quiz lessons are complete.
  const exam = await env.DB.prepare("SELECT * FROM assessments WHERE id = 'asm_a1_exam'").first();
  r = await learner.post(`/assessments/${exam.id}/start`, {});
  assert.match(r.location, /error=assess\.gate\.lessons/);

  // ── Quizzes: take each one (quizzes complete their lesson once graded).
  for (const quizId of ["asm_a1_q1", "asm_a1_q2", "asm_a1_q3"]) {
    r = await learner.post(`/assessments/${quizId}/start`, {});
    assert.equal(r.status, 303);
    const attemptId = r.location.split("/").pop();
    const page = await learner.get(`/attempts/${attemptId}`);
    assert.equal(page.status, 200);
    assert.doesNotMatch(page.text, /answer_json|"correct"/, "answer keys never rendered");
    r = await learner.post(`/attempts/${attemptId}/submit`, await correctResponses(env, attemptId));
    assert.equal(r.status, 303);
    const graded = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
    assert.equal(graded.status, "graded");
    assert.equal(graded.score_pct, 100);
  }
  enr = await env.DB.prepare("SELECT * FROM enrollments WHERE user_id = ?").bind(user.id).first();
  assert.ok(enr.progress_pct >= 90 && enr.status === "active", "all lessons done, exam pending");

  // ── Exam attempt 1: submit nothing → fail, server-side scoring.
  r = await learner.post(`/assessments/${exam.id}/start`, {});
  assert.equal(r.status, 303);
  let attemptId = r.location.split("/").pop();
  const att = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(JSON.parse(att.layout_json).length, 20, "20 questions drawn");
  assert.ok(att.deadline_at, "timed exam has a deadline");
  // A forged score in the request is ignored.
  r = await learner.post(`/attempts/${attemptId}/submit`, { score_pct: "100", passed: "1" });
  let a1 = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a1.status, "graded");
  assert.equal(a1.passed, 0);
  assert.equal(a1.score_pct, 0);
  r = await learner.get(`/attempts/${attemptId}`);
  assert.equal(r.status, 200);
  assert.doesNotMatch(r.text, /Correct answer|Resposta correta/, "exam feedback policy hides correct answers");

  // Cooldown blocks an immediate retake.
  r = await learner.post(`/assessments/${exam.id}/start`, {});
  assert.match(r.location, /error=assess\.gate\.cooldown/);
  await env.DB.prepare("UPDATE attempts SET submitted_at = '2026-01-01T00:00:00.000Z' WHERE id = ?").bind(attemptId).run();

  // Without a verified email, passing does not yet issue a credential.
  r = await learner.post(`/assessments/${exam.id}/start`, {});
  attemptId = r.location.split("/").pop();
  // Autosave via the JSON API, then submit.
  const answers = await correctResponses(env, attemptId);
  r = await learner.request("POST", `/api/attempts/${attemptId}/save`, { body: answers, headers: { accept: "application/json", "x-csrf-token": learner.csrf } });
  assert.equal(r.status, 200);
  assert.equal(JSON.parse(r.text).saved, 20);
  r = await learner.post(`/attempts/${attemptId}/submit`, {});
  a1 = await env.DB.prepare("SELECT * FROM attempts WHERE id = ?").bind(attemptId).first();
  assert.equal(a1.passed, 1, "autosaved answers graded on submit");
  assert.equal(a1.score_pct, 100);
  enr = await env.DB.prepare("SELECT * FROM enrollments WHERE user_id = ?").bind(user.id).first();
  assert.equal(enr.status, "completed");
  assert.equal(enr.progress_pct, 100);
  assert.ok(enr.completed_at);
  let certCount = await env.DB.prepare("SELECT COUNT(*) AS n FROM certificates WHERE user_id = ?").bind(user.id).first();
  assert.equal(certCount.n, 0, "no certificate before email verification");

  // ── Verifying the email issues the pending credential automatically.
  const tok = tokenFrom(verifyMail, "/verify-email");
  // Opening the link (as a mail scanner would) only shows a confirmation button.
  r = await learner.get(`/verify-email?token=${tok}`);
  assert.equal(r.status, 200);
  assert.match(r.text, /<form method="post" action="\/verify-email"/);
  assert.equal((await env.DB.prepare("SELECT email_verified_at FROM users WHERE id = ?").bind(user.id).first()).email_verified_at, null, "a GET never verifies");
  r = await learner.post("/verify-email", { token: tok });
  assert.equal(r.status, 303);
  const cert = await env.DB.prepare("SELECT * FROM certificates WHERE user_id = ?").bind(user.id).first();
  assert.ok(cert, "certificate issued after verification");
  assert.match(cert.credential_id, /^AGA-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$/);
  assert.equal(cert.credential_name, "Maria da Silva");
  assert.ok(await lastEmail(env, "maria@academy.test", "certificate_issued"), "certificate email queued");

  // Claiming again never duplicates.
  r = await learner.post(`/certificates/claim/${COURSE}`, {});
  certCount = await env.DB.prepare("SELECT COUNT(*) AS n FROM certificates WHERE user_id = ?").bind(user.id).first();
  assert.equal(certCount.n, 1, "duplicate credential prevented");

  // ── Certificate page, PDF, verification, LinkedIn.
  r = await learner.get(`/certificates/${cert.credential_id}`);
  assert.equal(r.status, 200);
  const linkedin = /href="(https:\/\/www\.linkedin\.com\/profile\/add\?[^"]+)"/.exec(r.text)[1].replace(/&amp;/g, "&");
  const lq = new URL(linkedin).searchParams;
  assert.equal(lq.get("startTask"), "CERTIFICATION_NAME");
  assert.equal(lq.get("name"), "Introduction to Artificial Intelligence in Agriculture");
  assert.equal(lq.get("organizationName"), "AGRO-AI Academy");
  assert.equal(lq.get("certId"), cert.credential_id);
  assert.equal(lq.get("certUrl"), `${ORIGIN}/verify/${cert.credential_id}`);
  assert.ok(lq.get("issueYear") && lq.get("issueMonth"));
  assert.match(r.text, /linkedin\.com\/sharing\/share-offsite\/\?url=/);
  assert.match(r.text, /facebook\.com\/sharer\/sharer\.php\?u=/);

  const pdf = await learner.get(`/certificates/${cert.credential_id}/pdf`);
  assert.equal(pdf.status, 200);
  assert.equal(pdf.headers.get("content-type"), "application/pdf");
  const bytes = new Uint8Array(await pdf.res.arrayBuffer());
  assert.equal(new TextDecoder().decode(bytes.slice(0, 8)), "%PDF-1.4");
  assert.ok(bytes.length > 5000);

  // Another learner cannot download someone else's PDF.
  const other = await registeredLearner(env, { email: "other@academy.test" });
  r = await other.get(`/certificates/${cert.credential_id}/pdf`);
  assert.equal(r.status, 404);

  // Public verification (anonymous), with no email or score exposed.
  r = await anon.get(`/verify/${cert.credential_id}`);
  assert.equal(r.status, 200);
  assert.match(r.text, /Valid credential/);
  assert.match(r.text, /Maria da Silva/);
  assert.doesNotMatch(r.text, /maria@academy\.test/);
  assert.match(r.text, /noindex/);
  r = await anon.get("/verify/AGA-0000-0000-0000");
  assert.equal(r.status, 404);

  // Revocation is reflected publicly.
  r = await admin.post(`/admin/certificates/${cert.id}/revoke`, { reason: "Issued in error (test)" });
  assert.equal(r.status, 303);
  r = await anon.get(`/verify/${cert.credential_id}`);
  assert.match(r.text, /Revoked credential/);
  const events = (await env.DB.prepare("SELECT event FROM certificate_events WHERE certificate_id = ?").bind(cert.id).all()).results.map((e) => e.event);
  assert.deepEqual(events.filter((e) => e !== "pdf_downloaded").sort(), ["issued", "revoked"]);
  const auditRows = (await env.DB.prepare("SELECT action FROM audit_log WHERE entity_id = ?").bind(cert.id).all()).results.map((a) => a.action);
  assert.ok(auditRows.includes("certificate.revoke"));

  // ── Back to the dashboard: real figures.
  r = await learner.get("/dashboard");
  assert.equal(r.status, 200);
  r = await learner.get("/dashboard/results");
  assert.match(r.text, /100%/);
});
