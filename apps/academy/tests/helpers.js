// Test harness: runs the production Worker against an in-memory D1-compatible
// database with all migrations applied, and a cookie-aware HTTP client.
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { D1Shim, applyMigrations } from "../dev/d1-shim.js";
import { assetsBinding } from "../dev/server.js";
import worker from "../src/index.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
export const ORIGIN = "https://academy.test";

export function makeEnv(overrides = {}) {
  const DB = new D1Shim(":memory:");
  applyMigrations(DB, join(root, "migrations"));
  return {
    DB,
    ASSETS: assetsBinding(join(root, "public")),
    APP_ORIGIN: ORIGIN,
    ENVIRONMENT: "test",
    CERT_SIGNING_SECRET: "test-signing-secret",
    BOOTSTRAP_ADMIN_EMAILS: "founder@academy.test",
    ...overrides,
  };
}

export class Client {
  constructor(env) {
    this.env = env;
    this.jar = new Map();
    this.csrf = null;
  }
  cookieHeader() {
    return [...this.jar].map(([k, v]) => `${k}=${v}`).join("; ");
  }
  store(res) {
    for (const sc of res.headers.getSetCookie()) {
      const [pair, ...attrs] = sc.split(";");
      const i = pair.indexOf("=");
      const k = pair.slice(0, i).trim();
      const v = pair.slice(i + 1).trim();
      if (attrs.some((a) => /max-age=0/i.test(a)) || v === "") this.jar.delete(k);
      else this.jar.set(k, v);
    }
  }
  async request(method, path, { body, headers = {}, json } = {}) {
    const h = new Headers(headers);
    if (this.jar.size) h.set("cookie", this.cookieHeader());
    let payload;
    if (json !== undefined) {
      h.set("content-type", "application/json");
      h.set("accept", "application/json");
      if (this.csrf) h.set("x-csrf-token", this.csrf);
      payload = JSON.stringify(json);
    } else if (body !== undefined) {
      h.set("content-type", "application/x-www-form-urlencoded");
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(body)) for (const item of [].concat(v)) params.append(k, item);
      if (this.csrf && !params.has("_csrf")) params.set("_csrf", this.csrf);
      payload = params.toString();
    }
    const pending = [];
    const res = await worker.fetch(new Request(ORIGIN + path, { method, headers: h, body: payload }), this.env, { waitUntil: (p) => pending.push(p) });
    await Promise.allSettled(pending);
    this.store(res);
    const text = res.headers.get("content-type")?.includes("application/pdf") ? null : await res.clone().text();
    const m = text && /<meta name="csrf-token" content="([^"]+)"/.exec(text);
    if (m) this.csrf = m[1];
    return { res, status: res.status, text, location: res.headers.get("location"), headers: res.headers };
  }
  get(path, opts) {
    return this.request("GET", path, opts);
  }
  post(path, body, opts = {}) {
    return this.request("POST", path, { body, ...opts });
  }
  postJson(path, json) {
    return this.request("POST", path, { json });
  }
  /** Follow redirects for GETs (POST/Redirect/GET). */
  async follow(r, max = 5) {
    let cur = r;
    for (let i = 0; i < max && cur.location; i++) cur = await this.get(cur.location.replace(ORIGIN, ""));
    return cur;
  }
}

export async function lastEmail(env, to, template) {
  return env.DB.prepare("SELECT * FROM email_outbox WHERE to_email = ? AND template = ? ORDER BY created_at DESC, rowid DESC LIMIT 1").bind(to, template).first();
}

export function tokenFrom(email, path) {
  const m = new RegExp(`${path}\\?token=([A-Za-z0-9_-]+)`).exec(email.text);
  return m && m[1];
}

/** Register, verify email, and return a signed-in client. */
export async function registeredLearner(env, { email = `learner${Math.random().toString(36).slice(2, 8)}@academy.test`, name = "Ada Learner", verify = true, password = "correct horse battery staple" } = {}) {
  const c = new Client(env);
  await c.get("/register");
  const r = await c.post("/register", { display_name: name, email, password, locale: "en", accept_terms: "1" });
  if (r.status !== 303) throw new Error(`registration failed: ${r.status} ${r.text?.slice(0, 200)}`);
  if (verify) {
    const mail = await lastEmail(env, email, "verify_email");
    const tok = tokenFrom(mail, "/verify-email");
    await c.get(`/verify-email?token=${tok}`);
  }
  return Object.assign(c, { email, password, name });
}

/** Answer every question of an attempt correctly using the server-side key (test-only). */
export async function correctResponses(env, attemptId) {
  const a = await env.DB.prepare("SELECT layout_json FROM attempts WHERE id = ?").bind(attemptId).first();
  const ids = JSON.parse(a.layout_json).map((l) => l.q);
  const body = {};
  for (const id of ids) {
    const q = await env.DB.prepare("SELECT * FROM questions WHERE id = ?").bind(id).first();
    const key = JSON.parse(q.answer_json);
    if (q.type === "single") body[`q[${id}]`] = key.correct[0];
    if (q.type === "multiple") body[`q[${id}]`] = key.correct;
    if (q.type === "true_false") body[`q[${id}]`] = String(key.value);
    if (q.type === "short_answer") body[`q[${id}]`] = key.accepted[0];
    if (q.type === "matching") for (const [l, r] of Object.entries(key.pairs)) body[`m[${id}][${l}]`] = r;
    if (q.type === "ordering") key.order.forEach((itemId, i) => (body[`o[${id}][${itemId}]`] = String(i + 1)));
  }
  return body;
}

export async function publishCourse(env, courseId) {
  await env.DB.prepare("UPDATE courses SET status = 'published', published_at = ? WHERE id = ?").bind(new Date().toISOString(), courseId).run();
}

export const A1_SLUG = "introduction-to-ai-in-agriculture";

/** Drive a verified learner through Course A1 (lessons, quizzes, exam) via HTTP. */
export async function completeA1(env, learner) {
  await learner.post(`/courses/${A1_SLUG}/enroll`, {});
  const lessons = (await env.DB.prepare("SELECT * FROM lessons WHERE course_id = 'crs_a1' AND status = 'ready' ORDER BY sort_order").all()).results;
  for (const l of lessons.filter((x) => x.type !== "quiz" && !x.assessment_id)) {
    const r = await learner.post(`/learn/${A1_SLUG}/${l.slug}/complete`, {});
    if (r.status !== 303) throw new Error(`could not complete ${l.slug}: ${r.status}`);
  }
  for (const id of ["asm_a1_q1", "asm_a1_q2", "asm_a1_q3", "asm_a1_exam"]) {
    const r = await learner.post(`/assessments/${id}/start`, {});
    const attemptId = r.location?.split("/").pop();
    if (!r.location?.includes("/attempts/")) throw new Error(`could not start ${id}: ${r.location}`);
    await learner.post(`/attempts/${attemptId}/submit`, await correctResponses(env, attemptId));
  }
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = ?").bind(learner.email).first();
  const cert = await env.DB.prepare("SELECT * FROM certificates WHERE user_id = ? AND course_id = 'crs_a1'").bind(user.id).first();
  return { user, cert };
}

/** A second env sharing the first env's database, with different settings. */
export function withSettings(env, overrides) {
  const next = { ...env, ...overrides };
  for (const [k, v] of Object.entries(overrides)) if (v === undefined) delete next[k];
  return next;
}

/** Minimal valid WebVTT for synthetic test captions. */
export const TEST_VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:04.000\nSynthetic test caption.\n";

/** Approve every planned A1 video through the admin console (synthetic media URLs). */
export async function approveA1Videos(env, admin, { mediaBase = "https://media.academy.test/a1" } = {}) {
  const videos = (await env.DB.prepare("SELECT v.* FROM video_assets v JOIN lessons l ON l.video_id = v.id WHERE l.course_id = 'crs_a1'").all()).results;
  for (const v of videos) {
    let r = await admin.post(`/admin/videos/${v.id}/captions`, { locale: "en", status: "reviewed", vtt: TEST_VTT });
    if (r.status !== 303) throw new Error(`captions ${v.id}: ${r.status}`);
    r = await admin.post(`/admin/videos/${v.id}`, {
      title: v.title, provider: "r2", status: "approved", instructor_id: v.instructor_id || "", duration_seconds: "12",
      hls_url: "", mp4_url: `${mediaBase}/${v.id}.webm`, poster_url: "", provider_ref: "", script_md: v.script_md,
    });
    if (r.status !== 303 || /err=/.test(r.location || "")) throw new Error(`approve ${v.id}: ${r.status} ${r.location}`);
  }
  return videos.length;
}

/** Record the three mandatory review approvals through the admin console. */
export async function approveReviews(admin, courseId, reviewer = "Synthetic Test Faculty") {
  for (const type of ["academic", "assessment", "accessibility"]) {
    const r = await admin.post(`/admin/courses/${courseId}/reviews`, { review_type: type, decision: "approved", confirm: "1", reviewer_name: reviewer, notes: "" });
    if (r.status !== 303 || /err=/.test(r.location || "")) throw new Error(`review ${type}: ${r.status} ${r.location}`);
  }
}
