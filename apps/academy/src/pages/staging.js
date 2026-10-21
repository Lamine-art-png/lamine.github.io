// Staging-only endpoints for the automated staging test and one-off
// maintenance. Every handler answers 404 unless the Worker runs as staging
// with a strong STAGING_TEST_TOKEN and the caller presents that token, so none
// of this exists in production.
import { json, HttpError } from "../lib/http.js";
import { nowIso, safeEqual } from "../lib/util.js";
import { isStagingTestAddress } from "../services/email.js";
import { ensureProbeCourse } from "../services/staging-probe.js";
import { cleanup } from "../services/staging-cleanup.js";

function requireStagingToken(c) {
  const token = String(c.env.STAGING_TEST_TOKEN || "");
  const given = (c.req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (c.cfg.environment !== "staging" || token.length < 32 || !safeEqual(given, token)) throw new HttpError(404, "not_found");
}

/** The latest message for a synthetic @academy-staging-test.invalid address. */
export async function inbox(c) {
  requireStagingToken(c);
  const to = String(c.url.searchParams.get("to") || "").toLowerCase();
  if (!isStagingTestAddress(to)) throw new HttpError(404, "not_found");
  const row = await c.env.DB.prepare("SELECT template, subject, text, status, created_at FROM email_outbox WHERE to_email = ? ORDER BY created_at DESC, rowid DESC LIMIT 1").bind(to).first();
  return json(row ? { ok: true, message: row } : { ok: false }, row ? 200 : 404);
}

/** Ensure the synthetic probe course exists (staging integration test). */
export async function probeCourse(c) {
  requireStagingToken(c);
  return json({ ok: true, probe: await ensureProbeCourse(c.env) });
}

/**
 * Give a verified synthetic staging test account a staff role (never
 * super_admin), so the staging test can check admin access, role
 * restrictions, publication controls and R2.
 */
export async function staff(c) {
  requireStagingToken(c);
  const b = await c.readBody();
  const email = String(b.email || "").toLowerCase();
  const role = ["academy_admin", "content_editor"].includes(b.role) ? b.role : null;
  if (!role || !isStagingTestAddress(email)) throw new HttpError(400, "invalid_request");
  const user = await c.env.DB.prepare("SELECT id FROM users WHERE email = ? AND email_verified_at IS NOT NULL AND status = 'active'").bind(email).first();
  if (!user) throw new HttpError(404, "not_found");
  await c.env.DB.prepare("INSERT OR IGNORE INTO user_roles (user_id, role, granted_by, granted_at) VALUES (?, ?, 'staging-test', ?)").bind(user.id, role, nowIso()).run();
  return json({ ok: true, user_id: user.id, role });
}

/**
 * One-off removal of synthetic accounts left by failed staging runs (manual,
 * via .github/workflows/academy-staging-cleanup.yml). Accounts are named
 * explicitly; "check" reports, "delete" deletes only if every account passes
 * every check.
 */
export async function cleanupAccounts(c) {
  requireStagingToken(c);
  const b = await c.readBody();
  const ids = [...new Set((Array.isArray(b.ids) ? b.ids : []).map(String))];
  const iso = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$/;
  const mode = b.mode === "delete" ? "delete" : b.mode === "check" ? "check" : null;
  if (!mode || ids.length < 1 || ids.length > 10 || !ids.every((id) => /^usr_[A-Za-z0-9_-]{8,40}$/.test(id)) || !iso.test(b.from || "") || !iso.test(b.to || "") || b.from > b.to) {
    throw new HttpError(400, "invalid_request");
  }
  const report = await cleanup(c.env, { ids, from: b.from, to: b.to, mode });
  return json(report, report.refused ? 409 : 200);
}
