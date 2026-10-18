// Writes a SQL dump of a SQLite database in the shape `wrangler d1 export`
// produces (schema, then INSERT statements, then indexes). Test-only.
import { DatabaseSync } from "node:sqlite";

const quote = (v) => {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "number" || typeof v === "bigint") return String(v);
  if (v instanceof Uint8Array) return `X'${Buffer.from(v).toString("hex")}'`;
  return `'${String(v).replace(/'/g, "''")}'`;
};

export function dumpDatabase(file) {
  const db = new DatabaseSync(file, { readOnly: true });
  const out = ["PRAGMA defer_foreign_keys=TRUE;"];
  const tables = db.prepare("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid").all();
  for (const t of tables) out.push(`${t.sql};`);
  for (const t of tables) {
    for (const row of db.prepare(`SELECT * FROM "${t.name}"`).all()) {
      const cols = Object.keys(row);
      out.push(`INSERT INTO "${t.name}" (${cols.map((c) => `"${c}"`).join(",")}) VALUES(${cols.map((c) => quote(row[c])).join(",")});`);
    }
  }
  for (const i of db.prepare("SELECT sql FROM sqlite_master WHERE type IN ('index','trigger') AND sql IS NOT NULL ORDER BY rowid").all()) out.push(`${i.sql};`);
  db.close();
  return out.join("\n") + "\n";
}
