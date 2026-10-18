// Password hashing, sessions, CSRF, rate limiting and audit logging.
import { b64url, b64urlDecode, randomBytes, randomToken, sha256Hex, safeEqual, nowIso, addSeconds, newId } from "./util.js";
import { HttpError, serializeCookie, clientIp } from "./http.js";

// Cloudflare Workers cap PBKDF2 at 100,000 iterations.
const PBKDF2_ITERATIONS = 100_000;
const enc = new TextEncoder();

async function pbkdf2(password, salt, iterations) {
  const key = await crypto.subtle.importKey("raw", enc.encode(password.normalize("NFKC")), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, key, 256);
  return new Uint8Array(bits);
}

export async function hashPassword(password) {
  const salt = randomBytes(16);
  const hash = await pbkdf2(password, salt, PBKDF2_ITERATIONS);
  return `pbkdf2_sha256$${PBKDF2_ITERATIONS}$${b64url(salt)}$${b64url(hash)}`;
}

export async function verifyPassword(password, stored) {
  if (!stored || typeof password !== "string") return false;
  const [scheme, iter, saltB64, hashB64] = stored.split("$");
  if (scheme !== "pbkdf2_sha256") return false;
  const hash = await pbkdf2(password, b64urlDecode(saltB64), Number(iter));
  return safeEqual(b64url(hash), hashB64);
}

/** Passwords: 10+ characters, not trivially guessable. Returns an i18n key or null. */
export function passwordProblem(password, email = "") {
  if (typeof password !== "string" || password.length < 10) return "auth.error.password_short";
  if (password.length > 200) return "auth.error.password_long";
  const lower = password.toLowerCase();
  const local = String(email).split("@")[0].toLowerCase();
  if (local.length >= 4 && lower.includes(local)) return "auth.error.password_weak";
  if (/^(.)\1+$/.test(password) || /^(password|1234567890|qwertyuiop|agroai|academy)/.test(lower)) return "auth.error.password_weak";
  return null;
}

// ───────────── Sessions ─────────────

const SESSION_DAYS = 30;

export function cookieNames(cfg) {
  const p = cfg.secure ? "__Host-" : "";
  return { session: `${p}aca_session`, csrf: `${p}aca_csrf`, oauth: `${p}aca_oauth` };
}

export async function createSession(c, userId) {
  const token = randomToken(32);
  const now = nowIso();
  await c.env.DB.prepare(
    "INSERT INTO sessions (id_hash, user_id, created_at, expires_at, last_seen_at, user_agent) VALUES (?,?,?,?,?,?)",
  )
    .bind(await sha256Hex(token), userId, now, addSeconds(now, SESSION_DAYS * 86400), now, (c.req.headers.get("user-agent") || "").slice(0, 200))
    .run();
  c.setCookie(serializeCookie(cookieNames(c.cfg).session, token, { maxAge: SESSION_DAYS * 86400, secure: c.cfg.secure }));
  return token;
}

export async function loadSession(c) {
  const token = c.cookies[cookieNames(c.cfg).session];
  if (!token || token.length > 100) return null;
  const idHash = await sha256Hex(token);
  const row = await c.env.DB.prepare(
    `SELECT s.id_hash, s.expires_at, s.last_seen_at, s.revoked_at, u.*
       FROM sessions s JOIN users u ON u.id = s.user_id
      WHERE s.id_hash = ?`,
  )
    .bind(idHash)
    .first();
  const now = nowIso();
  if (!row || row.revoked_at || row.expires_at < now || row.status !== "active") return null;
  // Sliding activity timestamp, written at most every 10 minutes.
  if (Date.parse(now) - Date.parse(row.last_seen_at) > 600_000) {
    c.defer(c.env.DB.prepare("UPDATE sessions SET last_seen_at = ? WHERE id_hash = ?").bind(now, idHash).run());
  }
  const roles = (await c.env.DB.prepare("SELECT role FROM user_roles WHERE user_id = ?").bind(row.id).all()).results.map((r) => r.role);
  const { id_hash, expires_at, last_seen_at, revoked_at, password_hash, ...user } = row;
  return { idHash: id_hash, user: { ...user, has_password: !!password_hash }, roles };
}

export async function destroySession(c) {
  if (c.session) {
    await c.env.DB.prepare("UPDATE sessions SET revoked_at = ? WHERE id_hash = ?").bind(nowIso(), c.session.idHash).run();
  }
  c.setCookie(serializeCookie(cookieNames(c.cfg).session, "", { maxAge: 0, secure: c.cfg.secure }));
}

export async function revokeAllSessions(env, userId, exceptHash = null) {
  await env.DB.prepare("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND id_hash IS NOT ?")
    .bind(nowIso(), userId, exceptHash)
    .run();
}

// ───────────── CSRF (double-submit token + Origin check) ─────────────

export function ensureCsrf(c) {
  const name = cookieNames(c.cfg).csrf;
  let token = c.cookies[name];
  if (!token || !/^[A-Za-z0-9_-]{32,64}$/.test(token)) {
    token = randomToken(24);
    c.cookies[name] = token;
    c.setCookie(serializeCookie(name, token, { maxAge: 60 * 60 * 24 * 30, secure: c.cfg.secure }));
  }
  return token;
}

export function checkCsrf(c, body) {
  const origin = c.req.headers.get("origin");
  if (origin && origin !== c.cfg.origin) throw new HttpError(403, "bad_origin");
  const expected = c.cookies[cookieNames(c.cfg).csrf];
  const provided = c.req.headers.get("x-csrf-token") || body?._csrf;
  if (!expected || !provided || !safeEqual(String(provided), expected)) throw new HttpError(403, "csrf_failed");
}

// ───────────── Rate limiting (fixed window, D1-backed) ─────────────

export async function rateLimit(c, name, { limit, windowSeconds, key }) {
  const k = key ?? (await sha256Hex(`${name}:${clientIp(c.req)}`)).slice(0, 32);
  const bucket = `${name}:${k}`;
  const windowStart = Math.floor(Date.now() / 1000 / windowSeconds) * windowSeconds;
  const row = await c.env.DB.prepare(
    `INSERT INTO rate_limits (bucket, window_start, count) VALUES (?, ?, 1)
     ON CONFLICT(bucket, window_start) DO UPDATE SET count = count + 1
     RETURNING count`,
  )
    .bind(bucket, windowStart)
    .first();
  if (row && row.count > limit) {
    throw new HttpError(429, "rate_limited", "Too many requests", { retryAfter: windowStart + windowSeconds - Math.floor(Date.now() / 1000) });
  }
}

// ───────────── Audit log ─────────────

export function auditStmt(env, actorId, action, entityType, entityId, detail) {
  return env.DB.prepare("INSERT INTO audit_log (id, actor_id, action, entity_type, entity_id, detail, created_at) VALUES (?,?,?,?,?,?,?)").bind(
    newId("aud_"),
    actorId ?? null,
    action,
    entityType ?? null,
    entityId ?? null,
    detail == null ? null : JSON.stringify(detail).slice(0, 4000),
    nowIso(),
  );
}

export async function audit(c, action, entityType, entityId, detail) {
  await auditStmt(c.env, c.user?.id, action, entityType, entityId, detail).run();
}

// ───────────── Roles ─────────────

export const ROLE_PERMISSIONS = {
  super_admin: ["*"],
  academy_admin: [
    "admin.access", "courses.edit", "courses.publish", "courses.review", "assessments.edit", "grading", "learners.view", "learners.manage",
    "certificates.manage", "translations.edit", "analytics.view", "feedback.view", "support.manage", "audit.view", "instructors.edit",
  ],
  instructor: ["admin.access", "courses.edit", "courses.review", "assessments.edit", "grading", "learners.view", "analytics.view", "feedback.view"],
  content_editor: ["admin.access", "courses.edit", "assessments.edit", "translations.edit"],
  learner: [],
};

export function can(roles, permission) {
  return (roles || []).some((r) => {
    const p = ROLE_PERMISSIONS[r] || [];
    return p.includes("*") || p.includes(permission);
  });
}
