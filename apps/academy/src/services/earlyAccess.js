// Early-access registrants: people who registered interest at
// agroai-pilot.com/academy/early-access before the Academy opened.
//
// * Import never creates accounts, passwords or verified addresses.
// * A registrant is linked to an account only when that person registers and
//   proves the mailbox (email verification, password reset or Google).
// * An invitation goes at most once per registrant, only with recorded
//   consent and only to people without an account, and only when a super
//   administrator sends a batch explicitly.
import { newId, nowIso } from "../lib/util.js";
import { matchLocale } from "../lib/i18n.js";
import { normalizeEmail, validEmail, PROFESSIONAL_ROLES } from "./users.js";
import { queueEmail, deliverById, isStagingTestAddress } from "./email.js";
import { auditStmt } from "../lib/security.js";

export const SOURCE = "agroai-pilot.com/academy/early-access";
const MAX_ROWS = 2000; // keeps one paste under the 256 KB form limit
export const INVITE_BATCH = 100;

// Internal verification submissions made by deployment workflows, never real people.
const INTERNAL = new Set(["contact@agroai-pilot.com"]);

// The early-access form's roles, mapped to Academy profile roles.
const ROLE_MAP = { grower: "grower", operator: "operator", manager: "farm_manager", developer: "developer", student: "student", other: "other" };

const truthy = (v) => ["1", "true", "yes", "y"].includes(String(v ?? "").trim().toLowerCase());

/** Minimal RFC 4180 CSV parser (quoted fields, escaped quotes, CRLF). */
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') (field += '"'), i++;
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") row.push(field), (field = "");
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field), rows.push(row), (row = []), (field = "");
    } else field += ch;
  }
  if (field !== "" || row.length) row.push(field), rows.push(row);
  return rows.filter((r) => r.some((f) => f.trim() !== ""));
}

/**
 * Parse an export (CSV with a header row, or a JSON array) into validated
 * registrant records. Columns: source_id, email, name, language, role,
 * email_opt_in, registered_at. Returns { records, rejected, internal }.
 */
export function parseRegistrants(text) {
  const src = String(text || "").trim();
  let items;
  if (src.startsWith("[")) {
    items = JSON.parse(src);
    if (!Array.isArray(items)) throw new Error("expected a JSON array");
  } else {
    const [header, ...rows] = parseCsv(src);
    if (!header) return { records: [], rejected: [], internal: 0 };
    const cols = header.map((h) => h.trim().toLowerCase());
    if (!cols.includes("email")) throw new Error("the header row must include an email column");
    items = rows.map((r) => Object.fromEntries(cols.map((c, i) => [c, r[i] ?? ""])));
  }
  if (items.length > MAX_ROWS) throw new Error(`at most ${MAX_ROWS} rows per import`);
  const records = [];
  const rejected = [];
  let internal = 0;
  items.forEach((it, i) => {
    const email = normalizeEmail(it.email);
    const line = i + 2;
    if (!validEmail(email)) return rejected.push({ line, reason: "invalid email" });
    if (INTERNAL.has(email)) return internal++;
    const registeredAt = String(it.registered_at || it.created_at || "").trim();
    const when = Date.parse(registeredAt);
    if (!registeredAt || Number.isNaN(when)) return rejected.push({ line, reason: "missing or invalid registered_at" });
    const role = ROLE_MAP[String(it.role || "").trim().toLowerCase()] || (PROFESSIONAL_ROLES.includes(it.role) ? it.role : null);
    records.push({
      source_id: String(it.source_id || it.id || "").trim().slice(0, 120) || null,
      email,
      name: String(it.name || "").trim().slice(0, 120) || null,
      locale: matchLocale(String(it.language || it.locale || "").trim()) || null,
      professional_role: role,
      email_opt_in: truthy(it.email_opt_in) ? 1 : 0,
      registered_at: new Date(when).toISOString(),
    });
  });
  return { records, rejected, internal };
}

/** Counts that show what an import would do, without writing. */
export async function previewImport(env, records) {
  let fresh = 0;
  let known = 0;
  let accounts = 0;
  for (const r of records) {
    if (await env.DB.prepare("SELECT 1 FROM early_access_registrants WHERE email = ?").bind(r.email).first()) known++;
    else fresh++;
    if (await env.DB.prepare("SELECT 1 FROM users WHERE email = ? AND email_verified_at IS NOT NULL AND status = 'active'").bind(r.email).first()) accounts++;
  }
  return { fresh, known, accounts, optedIn: records.filter((r) => r.email_opt_in).length };
}

/**
 * Upsert registrants by email (the earliest registration wins; consent once
 * given is kept; missing details are filled in, never overwritten), then link
 * anyone who already has a verified account. Returns counts.
 */
export async function importRegistrants(env, records, actorId) {
  const now = nowIso();
  const stmts = records.map((r) =>
    env.DB.prepare(
      `INSERT INTO early_access_registrants (id, source, source_id, email, name, locale, professional_role, email_opt_in, registered_at, imported_at, imported_by)
       VALUES (?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(email) DO UPDATE SET
         source_id = COALESCE(early_access_registrants.source_id, excluded.source_id),
         name = COALESCE(early_access_registrants.name, excluded.name),
         locale = COALESCE(early_access_registrants.locale, excluded.locale),
         professional_role = COALESCE(early_access_registrants.professional_role, excluded.professional_role),
         email_opt_in = MAX(early_access_registrants.email_opt_in, excluded.email_opt_in),
         registered_at = MIN(early_access_registrants.registered_at, excluded.registered_at)`,
    ).bind(newId("eva_"), SOURCE, r.source_id, r.email, r.name, r.locale, r.professional_role, r.email_opt_in, r.registered_at, now, actorId),
  );
  for (let i = 0; i < stmts.length; i += 50) await env.DB.batch(stmts.slice(i, i + 50));
  const linked = await env.DB.prepare(
    `UPDATE early_access_registrants SET status = 'activated', activated_at = ?1,
            activated_user_id = (SELECT u.id FROM users u WHERE u.email = early_access_registrants.email AND u.email_verified_at IS NOT NULL AND u.status = 'active')
      WHERE status != 'activated'
        AND EXISTS (SELECT 1 FROM users u WHERE u.email = early_access_registrants.email AND u.email_verified_at IS NOT NULL AND u.status = 'active')`,
  )
    .bind(now)
    .run();
  await auditStmt(env, actorId, "early_access.import", "early_access", null, { rows: records.length, linked: linked.meta.changes }).run();
  return { rows: records.length, linked: linked.meta.changes };
}

/** Called once a user has proved their mailbox: links their early-access registration, if any. */
export async function linkVerifiedUser(env, user) {
  if (!user?.email_verified_at) return;
  await env.DB.prepare(
    "UPDATE early_access_registrants SET status = 'activated', activated_user_id = ?, activated_at = ? WHERE email = ? AND status != 'activated'",
  )
    .bind(user.id, nowIso(), normalizeEmail(user.email))
    .run();
}

export async function summary(env, cfg) {
  const by = (await env.DB.prepare("SELECT status, email_opt_in, COUNT(*) AS n FROM early_access_registrants GROUP BY status, email_opt_in").all()).results;
  const locales = (await env.DB.prepare("SELECT COALESCE(locale, 'unknown') AS locale, COUNT(*) AS n FROM early_access_registrants GROUP BY 1 ORDER BY n DESC").all()).results;
  const count = (pred) => by.filter(pred).reduce((n, r) => n + r.n, 0);
  return {
    total: count(() => true),
    pending: count((r) => r.status === "pending"),
    invited: count((r) => r.status === "invited"),
    activated: count((r) => r.status === "activated"),
    invitable: (await invitable(env, cfg, 1_000_000)).length,
    noConsent: count((r) => r.status === "pending" && !r.email_opt_in),
    locales,
  };
}

/**
 * Pending registrants who consented and have no account (verified or not)
 * yet. Outside production only synthetic staging test addresses qualify, so a
 * staging or local copy can never email real people.
 */
async function invitable(env, cfg, limit) {
  const rows = (
    await env.DB.prepare(
      `SELECT r.* FROM early_access_registrants r
        WHERE r.status = 'pending' AND r.email_opt_in = 1
          AND NOT EXISTS (SELECT 1 FROM users u WHERE u.email = r.email)
        ORDER BY r.registered_at, r.id LIMIT ?`,
    )
      .bind(cfg.environment === "production" ? limit : 1_000_000)
      .all()
  ).results;
  return cfg.environment === "production" ? rows : rows.filter((r) => isStagingTestAddress(r.email)).slice(0, limit);
}

/**
 * Send one batch of invitations. Each registrant is claimed atomically
 * (pending → invited) before its message is queued, so a repeated or
 * concurrent send never invites anyone twice. `expected` is the batch size
 * the administrator confirmed; if it changed meanwhile nothing is sent.
 */
export async function sendInvitations(env, cfg, { actorId, expected, defer = null }) {
  const batch = await invitable(env, cfg, INVITE_BATCH);
  if (expected !== batch.length) return { sent: 0, mismatch: true, available: batch.length };
  let sent = 0;
  for (const r of batch) {
    const claimed = await env.DB.prepare(
      "UPDATE early_access_registrants SET status = 'invited', invited_at = ? WHERE id = ? AND status = 'pending' AND NOT EXISTS (SELECT 1 FROM users u WHERE u.email = early_access_registrants.email) RETURNING id",
    )
      .bind(nowIso(), r.id)
      .first();
    if (!claimed) continue;
    const locale = r.locale || "en";
    const mailId = await queueEmail(env, cfg, {
      user: { id: null, email: r.email, display_name: r.name || "", locale },
      template: "early_access_invite",
      vars: { url: `${cfg.origin}/register?lang=${encodeURIComponent(locale)}` },
    });
    if (mailId) {
      if (defer) defer(deliverById(env, cfg, mailId));
      else await deliverById(env, cfg, mailId);
    }
    sent++;
  }
  await auditStmt(env, actorId, "early_access.invite", "early_access", null, { sent }).run();
  return { sent, mismatch: false };
}
