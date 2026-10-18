// Proves a D1 export is restorable before any migration runs: loads the SQL
// dump into a fresh SQLite database, runs integrity and foreign-key checks,
// and compares per-table row counts with the live counts taken just before
// the export. Prints a JSON summary; exits non-zero if anything is wrong.
//   node scripts/backup-verify.mjs backup.sql [--expect live-counts.json] [--tolerance 0.01]
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

const REQUIRED_TABLES = ["users", "courses", "lessons", "enrollments", "attempts", "certificates", "certificate_events", "audit_log"];

export function verifyDump(sql, { expect = null, tolerance = 0.01 } = {}) {
  const problems = [];
  if (!/CREATE TABLE/i.test(sql)) problems.push("dump contains no CREATE TABLE statements");
  // Constraints are checked explicitly below, after the whole dump has loaded.
  const db = new DatabaseSync(":memory:", { enableForeignKeyConstraints: false });
  try {
    db.exec(sql);
  } catch (e) {
    problems.push(`dump does not load: ${e.message}`);
    return { ok: false, problems, tables: {} };
  }
  const integrity = db.prepare("PRAGMA integrity_check").all().map((r) => Object.values(r)[0]);
  if (integrity.join() !== "ok") problems.push(`integrity_check: ${integrity.slice(0, 5).join("; ")}`);
  const fk = db.prepare("PRAGMA foreign_key_check").all();
  if (fk.length) problems.push(`foreign_key_check: ${fk.length} violation(s), first in ${fk[0].table}`);
  const names = db
    .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' ORDER BY name")
    .all()
    .map((r) => r.name);
  const tables = {};
  for (const n of names) tables[n] = db.prepare(`SELECT COUNT(*) AS n FROM "${n.replace(/"/g, '""')}"`).get().n;
  for (const t of REQUIRED_TABLES) if (!(t in tables)) problems.push(`required table missing: ${t}`);
  if (expect) {
    for (const [t, live] of Object.entries(expect)) {
      if (!(t in tables)) {
        problems.push(`table ${t} is live but missing from the backup`);
        continue;
      }
      // Learners keep using the Academy during the export, so allow a small drift.
      const allowed = Math.max(5, Math.ceil(live * tolerance));
      if (Math.abs(tables[t] - live) > allowed) problems.push(`table ${t}: backup has ${tables[t]} rows, live had ${live}`);
    }
  }
  db.close();
  return { ok: problems.length === 0, problems, tables };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2);
  const file = args.find((a) => !a.startsWith("--"));
  const opt = (name) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : null;
  };
  if (!file) {
    console.error("usage: backup-verify.mjs <dump.sql> [--expect counts.json] [--tolerance 0.01]");
    process.exit(2);
  }
  const expectFile = opt("--expect");
  const result = verifyDump(readFileSync(file, "utf8"), {
    expect: expectFile ? JSON.parse(readFileSync(expectFile, "utf8")) : null,
    tolerance: Number(opt("--tolerance") ?? 0.01),
  });
  console.log(JSON.stringify({ ok: result.ok, problems: result.problems, tables: result.tables }));
  process.exit(result.ok ? 0 : 1);
}
