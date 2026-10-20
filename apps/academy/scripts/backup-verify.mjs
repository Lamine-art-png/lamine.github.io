// Proves a D1 export is complete and restorable before any migration runs:
// loads the SQL dump into a fresh SQLite database, runs integrity and
// foreign-key checks, and checks it against the live database.
//
// Critical records (learners, roles, enrollments, progress, attempts and
// answers, certificates and their events, course reviews and revisions) are
// compared record by record with zero tolerance. The deploy fingerprints
// them before and after the export; every record that existed unchanged for
// the whole export window must be in the dump with the same fingerprint.
// Records created, changed or deleted while the export ran are reported but
// cannot hide a loss, and records of append-only tables may never vanish.
// Other tables (sessions, rate limits, the email queue) are compared by row
// count with a small tolerance. With --migrations, the pending migrations are
// rehearsed on the restored copy, so a migration that fails on real data
// stops the deploy before it touches the live database.
//
//   node scripts/backup-verify.mjs backup.sql [--expect live-counts.json]
//        [--before critical-before.json --after critical-after.json]
//        [--migrations dir] [--tolerance 0.01] [--fingerprints out.json]
// Prints a JSON summary (table names and counts only, never row contents);
// exits non-zero if anything is wrong.
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";

const REQUIRED_TABLES = ["users", "courses", "lessons", "enrollments", "attempts", "certificates", "certificate_events", "audit_log"];

/**
 * Critical tables: the record key and the columns whose values must survive.
 * Fingerprints use quote() so NULL, text and numbers stay distinct, and are
 * hashed before they are written anywhere (no personal data in work files).
 */
export const CRITICAL = {
  users: { key: "id", cols: ["email", "status", "created_at", "deleted_at", "length(password_hash)"] },
  user_roles: { key: "user_id || ':' || role", cols: ["granted_at"] },
  enrollments: { key: "id", cols: ["user_id", "course_id", "status", "enrolled_at", "completed_at"] },
  lesson_progress: { key: "user_id || ':' || lesson_id", cols: ["course_id", "status", "started_at", "completed_at"] },
  // Attempts keep everything needed to reproduce them exactly: the frozen
  // policy and question snapshots, the drawn layout, locale and deadline.
  attempts: {
    key: "id",
    cols: ["user_id", "assessment_id", "attempt_no", "status", "locale", "layout_json", "policy_json", "started_at", "deadline_at", "submitted_at", "graded_at", "score_points", "max_points", "score_pct", "passed"],
  },
  attempt_answers: { key: "attempt_id || ':' || question_id", cols: ["question_json", "response_json", "is_correct", "points_awarded", "max_points", "needs_review", "reviewer_comment"] },
  certificates: { key: "id", cols: ["credential_id", "course_id", "credential_name", "course_title", "score_pct", "issued_at", "status", "signature"], appendOnly: true },
  certificate_events: { key: "id", cols: ["certificate_id", "event", "created_at"], appendOnly: true },
  course_reviews: { key: "id", cols: ["course_id", "review_type", "decision", "content_hash", "created_at"], appendOnly: true },
  course_revisions: { key: "id", cols: ["course_id", "number", "content_hash", "published_at"], appendOnly: true },
  early_access_registrants: { key: "id", cols: ["email", "email_opt_in", "registered_at", "status", "invited_at", "activated_user_id"] },
};

/**
 * One query returning (t, k, f) for every critical record in the tables that
 * exist. `tables` are sqlite_master rows ({name, sql}); a fingerprint column
 * is used only if the table has it, so an older schema (before a migration
 * added it) is fingerprinted the same way live and in the dump.
 */
export function criticalSql(tables) {
  const schema = new Map(tables.map((t) => (typeof t === "string" ? [t, null] : [t.name, t.sql || ""])));
  const has = (sql, expr) => sql === null || new RegExp(`\\b${/[a-z_]+(?=\)?$)/.exec(expr)[0]}\\b`).test(sql);
  const parts = Object.entries(CRITICAL)
    .filter(([t]) => schema.has(t))
    .map(([t, c]) => {
      const cols = c.cols.filter((x) => has(schema.get(t), x));
      return `SELECT '${t}' AS t, ${c.key} AS k, ${cols.map((x) => `quote(${x})`).join(" || '|' || ")} AS f FROM "${t}"`;
    });
  return parts.join(" UNION ALL ") || "SELECT 'none' AS t, '' AS k, '' AS f";
}

/** {table: {key: fingerprint-hash}} from (t, k, f) rows. */
export function fingerprints(rows) {
  const out = {};
  for (const r of rows) {
    if (r.t === "none") continue;
    (out[r.t] ||= {})[String(r.k)] = createHash("sha256").update(String(r.f)).digest("hex").slice(0, 32);
  }
  return out;
}

function applyPendingMigrations(db, dir, problems) {
  const hasLedger = db.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'd1_migrations'").get();
  const done = new Set(hasLedger ? db.prepare("SELECT name FROM d1_migrations").all().map((r) => r.name) : []);
  const pending = readdirSync(dir).filter((f) => f.endsWith(".sql")).sort().filter((f) => !done.has(f));
  for (const f of pending) {
    try {
      db.exec(readFileSync(join(dir, f), "utf8"));
    } catch (e) {
      problems.push(`migration ${f} fails on the restored data: ${e.message}`);
      return pending;
    }
  }
  return pending;
}

export function verifyDump(sql, { expect = null, before = null, after = null, migrations = null, tolerance = 0.01, emitFingerprints = false } = {}) {
  const problems = [];
  const notes = [];
  if (!/CREATE TABLE/i.test(sql)) problems.push("dump contains no CREATE TABLE statements");
  // Constraints are checked explicitly below, after the whole dump has loaded.
  const db = new DatabaseSync(":memory:", { enableForeignKeyConstraints: false });
  try {
    db.exec(sql);
  } catch (e) {
    problems.push(`dump does not load: ${e.message}`);
    return { ok: false, problems, notes, tables: {} };
  }
  const integrity = db.prepare("PRAGMA integrity_check").all().map((r) => Object.values(r)[0]);
  if (integrity.join() !== "ok") problems.push(`integrity_check: ${integrity.slice(0, 5).join("; ")}`);
  const fk = db.prepare("PRAGMA foreign_key_check").all();
  if (fk.length) problems.push(`foreign_key_check: ${fk.length} violation(s), first in ${fk[0].table}`);
  const schema = db.prepare("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' ORDER BY name").all();
  const names = schema.map((r) => r.name);
  const tables = {};
  for (const n of names) tables[n] = db.prepare(`SELECT COUNT(*) AS n FROM "${n.replace(/"/g, '""')}"`).get().n;
  for (const t of REQUIRED_TABLES) if (!(t in tables)) problems.push(`required table missing: ${t}`);

  // Critical records: zero tolerance.
  const critical = {};
  if (before || after) {
    if (!before || !after) problems.push("critical record check needs fingerprints from both before and after the export");
    else {
      let dumped = {};
      try {
        dumped = fingerprints(db.prepare(criticalSql(schema)).all());
      } catch (e) {
        problems.push(`critical records cannot be read from the backup: ${e.message}`);
      }
      for (const [t, spec] of Object.entries(CRITICAL)) {
        const b = before[t];
        if (!b) continue;
        if (!(t in tables)) {
          problems.push(`table ${t} is live but missing from the backup`);
          continue;
        }
        const a = after[t] || {};
        const d = dumped[t] || {};
        let stable = 0, missing = 0, altered = 0, vanished = 0, changing = 0;
        for (const [k, h] of Object.entries(b)) {
          if (!(k in a)) {
            if (spec.appendOnly) vanished++;
            else changing++;
            continue;
          }
          if (a[k] !== h) {
            changing++;
            continue;
          }
          stable++;
          if (!(k in d)) missing++;
          else if (d[k] !== h) altered++;
        }
        // Records created during the export may or may not be in it; they are counted, not required.
        const created = Object.keys(a).filter((k) => !(k in b)).length;
        critical[t] = { stable, created, changing };
        if (missing) problems.push(`table ${t}: ${missing} record(s) missing from the backup`);
        if (altered) problems.push(`table ${t}: ${altered} record(s) differ in the backup`);
        if (vanished) problems.push(`table ${t}: ${vanished} append-only record(s) disappeared during the export`);
        if (changing) notes.push(`table ${t}: ${changing} record(s) changed during the export (not compared)`);
      }
    }
  }

  if (expect) {
    for (const [t, live] of Object.entries(expect)) {
      if (!(t in tables)) {
        problems.push(`table ${t} is live but missing from the backup`);
        continue;
      }
      if (critical[t]) continue;
      // Critical tables without fingerprints get no tolerance at all.
      const allowed = t in CRITICAL ? 0 : Math.max(5, Math.ceil(live * tolerance));
      if (Math.abs(tables[t] - live) > allowed) problems.push(`table ${t}: backup has ${tables[t]} rows, live had ${live}`);
    }
  }

  // For restore drills: the dump's own fingerprints, to compare with the restored database.
  let dumpFingerprints = null;
  if (emitFingerprints) {
    try {
      dumpFingerprints = fingerprints(db.prepare(criticalSql(schema)).all());
    } catch (e) {
      problems.push(`critical records cannot be read from the backup: ${e.message}`);
    }
  }

  let rehearsed = null;
  if (migrations && problems.length === 0) {
    rehearsed = applyPendingMigrations(db, migrations, problems);
    const fk2 = db.prepare("PRAGMA foreign_key_check").all();
    if (fk2.length) problems.push(`after rehearsing migrations: ${fk2.length} foreign key violation(s), first in ${fk2[0].table}`);
  }
  db.close();
  return { ok: problems.length === 0, problems, notes, tables, critical, rehearsed, dumpFingerprints };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2);
  const file = args.find((a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--")));
  const opt = (name) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : null;
  };
  if (!file) {
    console.error("usage: backup-verify.mjs <dump.sql> [--expect counts.json] [--before f.json --after f.json] [--migrations dir] [--tolerance 0.01]");
    process.exit(2);
  }
  const load = (name) => (opt(name) ? JSON.parse(readFileSync(opt(name), "utf8")) : null);
  const result = verifyDump(readFileSync(file, "utf8"), {
    expect: load("--expect"),
    before: load("--before"),
    after: load("--after"),
    migrations: opt("--migrations"),
    tolerance: Number(opt("--tolerance") ?? 0.01),
    emitFingerprints: Boolean(opt("--fingerprints")),
  });
  if (opt("--fingerprints")) writeFileSync(opt("--fingerprints"), JSON.stringify(result.dumpFingerprints || {}));
  delete result.dumpFingerprints;
  console.log(JSON.stringify(result));
  process.exit(result.ok ? 0 : 1);
}
