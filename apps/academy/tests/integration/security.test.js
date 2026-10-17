// Authentication, sessions, CSRF, RBAC, cross-user isolation, escaping,
// headers, rate limiting, and account deletion.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, lastEmail, tokenFrom, publishCourse, correctResponses } from "../helpers.js";

test("registration validates input and refuses duplicates", async () => {
  const env = makeEnv();
  const c = new Client(env);
  await c.get("/register");
  let r = await c.post("/register", { display_name: "A", email: "not-an-email", password: "short", accept_terms: "" });
  assert.equal(r.status, 422);
  assert.match(r.text, /Please enter a valid email address/);
  assert.match(r.text, /Use at least 10 characters/);
  assert.match(r.text, /accept the Terms/);
  r = await c.post("/register", { display_name: "Pat", email: "patricia@academy.test", password: "Patricia2026!!", accept_terms: "1" });
  assert.equal(r.status, 422, "password containing the email name is rejected");
  r = await c.post("/register", { display_name: "Pat", email: "Pat@Academy.test", password: "a long enough phrase", accept_terms: "1" });
  assert.equal(r.status, 303);
  const c2 = new Client(env);
  await c2.get("/register");
  r = await c2.post("/register", { display_name: "Pat 2", email: "pat@academy.test", password: "another long phrase", accept_terms: "1" });
  assert.equal(r.status, 422);
  assert.match(r.text, /already exists/);
  // Honeypot submissions are silently dropped.
  r = await c2.post("/register", { display_name: "Bot", email: "bot@academy.test", password: "another long phrase", accept_terms: "1", website: "http://spam" });
  assert.equal(r.status, 303);
  assert.equal(await env.DB.prepare("SELECT * FROM users WHERE email = 'bot@academy.test'").first(), null);
});

test("sign-in, lockout, sign-out and session cookie flags", async () => {
  const env = makeEnv();
  const u = await registeredLearner(env, { email: "lock@academy.test" });
  const c = new Client(env);
  await c.get("/login");
  let r = await c.post("/login", { email: "lock@academy.test", password: u.password, next: "/courses" });
  assert.equal(r.status, 303);
  assert.equal(r.location, "/courses");
  const setCookie = r.headers.getSetCookie().find((s) => s.startsWith("__Host-aca_session="));
  assert.match(setCookie, /HttpOnly/);
  assert.match(setCookie, /Secure/);
  assert.match(setCookie, /SameSite=Lax/);
  assert.match(setCookie, /Path=\//);
  // Open redirects are refused.
  const c3 = new Client(env);
  await c3.get("/login");
  r = await c3.post("/login", { email: "lock@academy.test", password: u.password, next: "//evil.example" });
  assert.equal(r.location, "/dashboard");
  // Sign out revokes the server-side session.
  r = await c.post("/logout", {});
  assert.equal(r.status, 303);
  r = await c.get("/dashboard");
  assert.equal(r.status, 303);
  assert.match(r.location, /^\/login\?next=/);

  const bad = new Client(env);
  await bad.get("/login");
  for (let i = 0; i < 5; i++) {
    r = await bad.post("/login", { email: "lock@academy.test", password: "wrong password!" });
    assert.equal(r.status, 401);
  }
  r = await bad.post("/login", { email: "lock@academy.test", password: u.password });
  assert.equal(r.status, 429, "account locked after five failures");
  assert.match(r.text, /Too many unsuccessful attempts/);
});

test("password reset tokens are single-use and revoke other sessions", async () => {
  const env = makeEnv();
  const u = await registeredLearner(env, { email: "reset@academy.test" });
  const c = new Client(env);
  await c.get("/forgot-password");
  let r = await c.post("/forgot-password", { email: "reset@academy.test" });
  assert.equal(r.status, 200);
  assert.match(r.text, /If an account exists/);
  r = await c.post("/forgot-password", { email: "nobody@academy.test" });
  assert.match(r.text, /If an account exists/, "same response for unknown accounts");
  const mail = await lastEmail(env, "reset@academy.test", "password_reset");
  const tok = tokenFrom(mail, "/reset-password");
  r = await c.get(`/reset-password?token=${tok}`);
  assert.match(r.text, /Choose a new password/);
  r = await c.post("/reset-password", { token: tok, password: "a brand new passphrase" });
  assert.equal(r.status, 303);
  assert.equal(r.location, "/login?reset=1");
  r = await c.post("/reset-password", { token: tok, password: "yet another passphrase" });
  assert.match(r.text, /This link has expired/, "token cannot be reused");
  // The learner's existing session was revoked.
  r = await u.get("/dashboard");
  assert.equal(r.status, 303);
  const login = new Client(env);
  await login.get("/login");
  r = await login.post("/login", { email: "reset@academy.test", password: "a brand new passphrase" });
  assert.equal(r.status, 303);
  assert.ok(await lastEmail(env, "reset@academy.test", "password_changed"));
});

test("CSRF protection and origin checks on state-changing requests", async () => {
  const env = makeEnv();
  const u = await registeredLearner(env);
  let r = await u.request("POST", "/dashboard/goals", { body: { title: "x", _csrf: "forged-token-value-1234567890abcdef" } });
  assert.equal(r.status, 403);
  r = await u.request("POST", "/dashboard/goals", { body: { title: "x" }, headers: { origin: "https://evil.example" } });
  assert.equal(r.status, 403);
  r = await u.post("/dashboard/goals", { title: "Finish course A1", weekly_minutes: "60" });
  assert.equal(r.status, 303);
  const goal = await env.DB.prepare("SELECT * FROM learning_goals").first();
  assert.equal(goal.title, "Finish course A1");
  assert.equal(goal.weekly_minutes, 60);
});

test("role-based access control for the admin console", async () => {
  const env = makeEnv();
  const anon = new Client(env);
  let r = await anon.get("/admin");
  assert.equal(r.status, 303);
  const learner = await registeredLearner(env);
  r = await learner.get("/admin");
  assert.equal(r.status, 403);
  r = await learner.post("/admin/courses/crs_a1/status", { status: "published" });
  assert.equal(r.status, 403);
  assert.equal((await env.DB.prepare("SELECT status FROM courses WHERE id='crs_a1'").first()).status, "review");

  const editor = await registeredLearner(env, { email: "editor@academy.test" });
  const editorId = (await env.DB.prepare("SELECT id FROM users WHERE email='editor@academy.test'").first()).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'content_editor', ?)").bind(editorId, new Date().toISOString()).run();
  r = await editor.get("/admin/courses");
  assert.equal(r.status, 200);
  r = await editor.get("/admin/certificates");
  assert.equal(r.status, 403, "content editors cannot manage certificates");
  r = await editor.post("/admin/courses/crs_a1/status", { status: "published" });
  assert.equal(r.status, 403, "content editors cannot publish");

  // Only super admins can change roles.
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  const adminId = (await env.DB.prepare("SELECT id FROM users WHERE email='founder@academy.test'").first()).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'academy_admin', ?)").bind(editorId, new Date().toISOString()).run();
  r = await editor.post(`/admin/learners/${adminId}/roles`, { roles: ["learner"] });
  assert.equal(r.status, 403);
  r = await admin.post(`/admin/learners/${adminId}/roles`, { roles: ["learner"] });
  assert.match(decodeURIComponent(r.location), /only super administrator/, "the last super admin cannot remove their own role");
  r = await admin.get("/admin/audit");
  assert.equal(r.status, 200);
});

test("learners cannot read or modify another learner's records", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const a = await registeredLearner(env, { email: "a@academy.test" });
  const b = await registeredLearner(env, { email: "b@academy.test" });
  await a.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  let r = await a.post("/assessments/asm_a1_q1/start", {});
  const attemptId = r.location.split("/").pop();
  r = await b.get(`/attempts/${attemptId}`);
  assert.equal(r.status, 404);
  r = await b.post(`/attempts/${attemptId}/submit`, await correctResponses(env, attemptId));
  assert.equal(r.status, 404);
  r = await b.request("POST", `/api/attempts/${attemptId}/save`, { body: {}, headers: { accept: "application/json", "x-csrf-token": b.csrf } });
  assert.equal(r.status, 404);
  // Notes
  await a.post("/learn/introduction-to-ai-in-agriculture/welcome/notes", { body: "private thought" });
  const note = await env.DB.prepare("SELECT * FROM notes").first();
  r = await b.post(`/learn/introduction-to-ai-in-agriculture/welcome/notes/${note.id}/delete`, {});
  assert.ok(await env.DB.prepare("SELECT * FROM notes WHERE id = ?").bind(note.id).first(), "other learner cannot delete the note");
  r = await b.get("/learn/introduction-to-ai-in-agriculture/welcome");
  assert.doesNotMatch(r.text, /private thought/);
  // Progress API rejects learners who are not enrolled.
  r = await b.postJson("/api/progress", { lessonId: "les_a1_data", position: 10 });
  assert.equal(JSON.parse(r.text).results[0].error, "not_enrolled");
  // Non-preview lessons require enrollment.
  r = await b.get("/learn/introduction-to-ai-in-agriculture/data-the-raw-material");
  assert.equal(r.status, 303);
});

test("user content is escaped and security headers are present", async () => {
  const env = makeEnv();
  const u = await registeredLearner(env, { name: '<script>alert("x")</script> Eve' });
  const r = await u.get("/dashboard");
  assert.doesNotMatch(r.text, /<script>alert/);
  assert.match(r.text, /&lt;script&gt;alert/);
  const h = r.headers;
  assert.match(h.get("content-security-policy"), /default-src 'self'/);
  assert.match(h.get("content-security-policy"), /frame-ancestors 'none'/);
  assert.doesNotMatch(h.get("content-security-policy"), /unsafe-inline|unsafe-eval/);
  assert.equal(h.get("x-frame-options"), "DENY");
  assert.equal(h.get("x-content-type-options"), "nosniff");
  assert.match(h.get("strict-transport-security"), /max-age=/);
  assert.equal(h.get("cache-control"), "private, no-store");
  // No inline style attributes or inline scripts in rendered pages (CSP-clean).
  for (const path of ["/", "/courses", "/courses/introduction-to-ai-in-agriculture", "/dashboard", "/account", "/verify"]) {
    const page = await u.get(path);
    assert.doesNotMatch(page.text, /\sstyle="/, `${path} has no inline styles`);
    assert.doesNotMatch(page.text, /<script(?![^>]*\bsrc=)(?![^>]*application\/ld\+json)[^>]*>/, `${path} has no inline scripts`);
  }
});

test("rate limiting on sign-in", async () => {
  const env = makeEnv();
  const c = new Client(env);
  await c.get("/login");
  let last;
  for (let i = 0; i < 22; i++) last = await c.post("/login", { email: `x${i}@academy.test`, password: "whatever password" });
  assert.equal(last.status, 429);
  assert.ok(last.headers.get("retry-after"));
});

test("account deletion erases learning data and anonymizes credentials", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const u = await registeredLearner(env, { email: "leave@academy.test", name: "Leaving Learner" });
  const userId = (await env.DB.prepare("SELECT id FROM users WHERE email='leave@academy.test'").first()).id;
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  await u.post("/learn/introduction-to-ai-in-agriculture/welcome/notes", { body: "note" });
  // Give the learner a certificate to observe anonymization.
  await env.DB.prepare(
    "INSERT INTO certificates (id, credential_id, user_id, course_id, credential_name, course_title, issued_at, status, signature, created_at) VALUES ('crt_t', 'AGA-TEST-0000-0001', ?, 'crs_a1', 'Leaving Learner', 'Intro', ?, 'active', 'x', ?)",
  )
    .bind(userId, new Date().toISOString(), new Date().toISOString())
    .run();
  const exp = await u.get("/account/export");
  const data = JSON.parse(exp.text);
  assert.equal(data.profile.email, "leave@academy.test");
  assert.equal(data.profile.password_hash, undefined, "password hash never exported");
  assert.equal(data.enrollments.length, 1);

  let r = await u.post("/account/delete", { password: u.password, confirm: "nope" });
  assert.equal(r.status, 422);
  r = await u.post("/account/delete", { password: u.password, confirm: "DELETE" });
  assert.equal(r.status, 303);
  assert.equal(await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(userId).first(), null);
  for (const t of ["enrollments", "notes", "sessions", "lesson_progress", "user_roles", "user_preferences"]) {
    const n = await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${t} WHERE user_id = ?`).bind(userId).first();
    assert.equal(n.n, 0, `${t} erased`);
  }
  const cert = await env.DB.prepare("SELECT * FROM certificates WHERE id = 'crt_t'").first();
  assert.equal(cert.status, "revoked");
  assert.equal(cert.user_id, null);
  assert.equal(cert.credential_name, "Former learner");
  const pub = await new Client(env).get("/verify/AGA-TEST-0000-0001");
  assert.match(pub.text, /Revoked credential/);
  assert.doesNotMatch(pub.text, /Leaving Learner/);
});
