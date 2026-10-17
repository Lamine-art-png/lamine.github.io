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
