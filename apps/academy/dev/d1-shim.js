// A Cloudflare D1-compatible binding backed by node:sqlite, used by the local
// dev server and the test suite so the production Worker code runs unchanged.
import { DatabaseSync } from "node:sqlite";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

function normalize(values) {
  return values.map((v) => {
    if (v === undefined) throw new TypeError("D1_TYPE_ERROR: undefined is not a supported bind value");
    if (typeof v === "boolean") return v ? 1 : 0;
    return v;
  });
}

class Statement {
  constructor(db, sql, params = []) {
    this.db = db;
    this.sql = sql;
    this.params = params;
  }
  bind(...values) {
    return new Statement(this.db, this.sql, normalize(values));
  }
  _stmt() {
    return this.db.sqlite.prepare(this.sql);
  }
  async first(column) {
    const row = this._stmt().get(...this.params);
    if (!row) return null;
    const plain = { ...row };
    return column ? plain[column] ?? null : plain;
  }
  async all() {
    return this._allSync();
  }
  _allSync() {
    const stmt = this._stmt();
    const results = stmt.all(...this.params).map((r) => ({ ...r }));
    return { success: true, results, meta: { changes: 0 } };
  }
  async raw() {
    const stmt = this._stmt();
    stmt.setReturnArrays?.(true);
    return stmt.all(...this.params);
  }
  async run() {
    return this._runSync();
  }
  _runSync() {
    if (/^\s*(select|with)\b/i.test(this.sql) && !/\b(insert|update|delete)\b/i.test(this.sql)) {
      return this._allSync();
    }
    if (/\breturning\b/i.test(this.sql)) {
      const results = this._stmt().all(...this.params).map((r) => ({ ...r }));
      return { success: true, results, meta: { changes: results.length } };
    }
    const info = this._stmt().run(...this.params);
    return { success: true, results: [], meta: { changes: Number(info.changes), last_row_id: Number(info.lastInsertRowid) } };
  }
}

export class D1Shim {
  constructor(filename = ":memory:") {
    this.sqlite = new DatabaseSync(filename);
    this.sqlite.exec("PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 10000;");
    if (filename !== ":memory:") this.sqlite.exec("PRAGMA journal_mode = WAL;");
  }
  prepare(sql) {
    return new Statement(this, sql);
  }
  async batch(statements) {
    // D1 batches run as a single implicit transaction.
    this.sqlite.exec("BEGIN");
    try {
      const out = statements.map((s) => s._runSync());
      this.sqlite.exec("COMMIT");
      return out;
    } catch (err) {
      this.sqlite.exec("ROLLBACK");
      throw err;
    }
  }
  async exec(sql) {
    this.sqlite.exec(sql);
    return { count: 1, duration: 0 };
  }
}

export function applyMigrations(db, dir) {
  const files = readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();
  for (const f of files) db.sqlite.exec(readFileSync(join(dir, f), "utf8"));
  return files;
}
