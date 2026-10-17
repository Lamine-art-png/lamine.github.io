// Account lifecycle: creation, role bootstrap, tokens, and deletion.
import { newId, nowIso, addSeconds, randomToken, sha256Hex } from "../lib/util.js";
import { HttpError } from "../lib/http.js";
import { hashPassword, auditStmt, revokeAllSessions } from "../lib/security.js";
import { eventStmt } from "./activity.js";

export const PROFESSIONAL_ROLES = ["grower", "agronomist", "farm_manager", "operator", "student", "researcher", "developer", "advisor", "other"];

export function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

export function validEmail(email) {
  return /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/.test(email) && email.length <= 254;
}

export async function findUserByEmail(env, email) {
  return env.DB.prepare("SELECT * FROM users WHERE email = ? AND status != 'deleted'").bind(normalizeEmail(email)).first();
}

export async function createUser(env, cfg, { email, password = null, displayName, locale, country = null, professionalRole = null, verified = false, marketing = false }) {
  const now = nowIso();
  const id = newId("usr_");
  const emailNorm = normalizeEmail(email);
  const stmts = [
    env.DB.prepare(
      `INSERT INTO users (id, email, email_verified_at, password_hash, display_name, locale, country, professional_role, status, created_at, updated_at)
       VALUES (?,?,?,?,?,?,?,?, 'active', ?, ?)`,
    ).bind(id, emailNorm, verified ? now : null, password ? await hashPassword(password) : null, displayName.trim().slice(0, 120), locale, country, professionalRole, now, now),
    env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'learner', ?)").bind(id, now),
    env.DB.prepare("INSERT INTO user_preferences (user_id, notify_product_news, updated_at) VALUES (?,?,?)").bind(id, marketing ? 1 : 0, now),
    eventStmt(env, { userId: id, event: "registered", locale }),
    auditStmt(env, id, "user.register", "user", id, { method: password ? "password" : "oauth" }),
  ];
  try {
    await env.DB.batch(stmts);
  } catch (e) {
    if (/UNIQUE/i.test(String(e?.message))) throw new HttpError(409, "email_taken");
    throw e;
  }
  if (verified) await applyBootstrapRoles(env, cfg, { id, email: emailNorm, email_verified_at: now });
  return id;
}

/** Grant super_admin to verified addresses listed in BOOTSTRAP_ADMIN_EMAILS. */
export async function applyBootstrapRoles(env, cfg, user) {
  if (!user.email_verified_at || !cfg.bootstrapAdmins.includes(normalizeEmail(user.email))) return false;
  const res = await env.DB.prepare("INSERT OR IGNORE INTO user_roles (user_id, role, granted_by, granted_at) VALUES (?, 'super_admin', 'bootstrap', ?)").bind(user.id, nowIso()).run();
  if (res.meta.changes) await auditStmt(env, user.id, "role.bootstrap_grant", "user", user.id, { role: "super_admin" }).run();
  return res.meta.changes > 0;
}

const TOKEN_TTL = { verify_email: 3 * 86400, reset_password: 3600 };

export async function issueToken(env, userId, purpose) {
  const token = randomToken(32);
  const now = nowIso();
  // Only the newest token of a purpose stays valid.
  await env.DB.batch([
    env.DB.prepare("UPDATE auth_tokens SET used_at = ? WHERE user_id = ? AND purpose = ? AND used_at IS NULL").bind(now, userId, purpose),
    env.DB.prepare("INSERT INTO auth_tokens (id_hash, user_id, purpose, expires_at, created_at) VALUES (?,?,?,?,?)").bind(
      await sha256Hex(token),
      userId,
      purpose,
      addSeconds(now, TOKEN_TTL[purpose]),
      now,
    ),
  ]);
  return token;
}

/** Atomically consume a token; returns the user id or null. */
export async function consumeToken(env, token, purpose) {
  if (!token || token.length > 100) return null;
  const now = nowIso();
  const row = await env.DB.prepare(
    "UPDATE auth_tokens SET used_at = ? WHERE id_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at > ? RETURNING user_id",
  )
    .bind(now, await sha256Hex(token), purpose, now)
    .first();
  return row?.user_id ?? null;
}

export async function peekToken(env, token, purpose) {
  if (!token || token.length > 100) return null;
  return env.DB.prepare("SELECT user_id FROM auth_tokens WHERE id_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at > ?")
    .bind(await sha256Hex(token), purpose, nowIso())
    .first();
}

/**
 * Delete an account. Personal data and learning records are erased; issued
 * credentials are revoked and anonymized so public verification shows the
 * credential is no longer valid without revealing who held it.
 */
export async function deleteAccount(env, userId, actorId) {
  const now = nowIso();
  const certs = (await env.DB.prepare("SELECT id FROM certificates WHERE user_id = ?").bind(userId).all()).results;
  await env.DB.batch([
    ...certs.flatMap((c) => [
      env.DB.prepare(
        "UPDATE certificates SET status='revoked', revoked_at=COALESCE(revoked_at, ?), revoked_reason='holder_account_deleted', credential_name='Former learner', user_id=NULL WHERE id=?",
      ).bind(now, c.id),
      env.DB.prepare("INSERT INTO certificate_events (id, certificate_id, event, actor_id, detail, created_at) VALUES (?,?,?,?,?,?)").bind(newId("ce_"), c.id, "revoked", actorId, "holder_account_deleted", now),
    ]),
    env.DB.prepare("DELETE FROM sessions WHERE user_id = ?").bind(userId),
    env.DB.prepare("DELETE FROM auth_tokens WHERE user_id = ?").bind(userId),
    env.DB.prepare("DELETE FROM oauth_accounts WHERE user_id = ?").bind(userId),
    env.DB.prepare("DELETE FROM email_outbox WHERE user_id = ?").bind(userId),
    env.DB.prepare("UPDATE learning_events SET user_id = NULL, country = NULL WHERE user_id = ?").bind(userId),
    env.DB.prepare("UPDATE course_feedback SET user_id = NULL WHERE user_id = ?").bind(userId),
    env.DB.prepare("UPDATE support_requests SET user_id = NULL, name = 'Deleted user', email = 'deleted@invalid' WHERE user_id = ?").bind(userId),
    // Cascades remove roles, preferences, goals, enrollments, progress, notes,
    // bookmarks, lesson feedback, achievements, attempts and notifications.
    env.DB.prepare("DELETE FROM users WHERE id = ?").bind(userId),
    auditStmt(env, actorId, "user.delete", "user", userId, { certificates_revoked: certs.length }),
  ]);
}

export async function setPassword(env, userId, password, keepSessionHash = null) {
  await env.DB.prepare("UPDATE users SET password_hash = ?, failed_logins = 0, locked_until = NULL, updated_at = ? WHERE id = ?").bind(await hashPassword(password), nowIso(), userId).run();
  await revokeAllSessions(env, userId, keepSessionHash);
}
