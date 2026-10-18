// Small JSON helpers for scripts/deploy.sh. Each reads wrangler or Cloudflare
// API output on stdin and prints one value. Never prints secret values.
//   d1-id <name>          → uuid of the D1 database <name> from `wrangler d1 list --json`
//   has-row-name <name>   → "yes"/"no": whether a result row has name = <name>
//   rows                  → JSON array of result rows from `wrangler d1 execute --json`
//   scalar <column>       → first row's <column> from `wrangler d1 execute --json`
//   counts-sql            → SELECT statement counting rows of every table in `rows` output
//   counts-json           → {table: n} from the counts query output
//   has-secret <name>     → "yes"/"no" from `wrangler secret list --format json`
//   has-bucket <name>     → "yes"/"no" from `wrangler r2 bucket list`
//   zone-id               → first zone id from the Cloudflare zones API
//   result-count          → length of `result` from a Cloudflare API list response
//   domain-owned <service>→ "yes"/"no" from the Workers custom domains API
//   set-db-id <name> <id> → wrangler.toml on stdin with only <name>'s database_id replaced
import { readFileSync } from "node:fs";

const [cmd, ...args] = process.argv.slice(2);
const input = readFileSync(0, "utf8");
const jsonFrom = (s) => {
  const start = s.search(/[[{]/);
  if (start < 0) throw new Error("no JSON in input");
  return JSON.parse(s.slice(start));
};
const d1Rows = (s) => {
  const out = jsonFrom(s);
  const first = Array.isArray(out) ? out[0] : out;
  if (first && first.success === false) throw new Error("d1 query failed");
  return first?.results ?? [];
};
const out = (v) => process.stdout.write(typeof v === "string" ? v : JSON.stringify(v));

switch (cmd) {
  case "d1-id": {
    const list = jsonFrom(input);
    out(list.find((d) => d.name === args[0])?.uuid || "");
    break;
  }
  case "has-row-name":
    out(d1Rows(input).some((r) => r.name === args[0]) ? "yes" : "no");
    break;
  case "rows":
    out(d1Rows(input));
    break;
  case "scalar": {
    const row = d1Rows(input)[0];
    out(row && row[args[0]] != null ? String(row[args[0]]) : "");
    break;
  }
  case "counts-sql": {
    const names = d1Rows(input)
      .map((r) => r.name)
      .filter((n) => /^[A-Za-z0-9_]+$/.test(n) && !n.startsWith("_cf_") && !n.startsWith("sqlite_"));
    out(names.map((n) => `SELECT '${n}' AS t, COUNT(*) AS n FROM "${n}"`).join(" UNION ALL ") || "SELECT 'none' AS t, 0 AS n");
    break;
  }
  case "counts-json":
    out(Object.fromEntries(d1Rows(input).filter((r) => r.t !== "none").map((r) => [r.t, Number(r.n)])));
    break;
  case "has-secret": {
    const list = jsonFrom(input);
    out(Array.isArray(list) && list.some((s) => s.name === args[0]) ? "yes" : "no");
    break;
  }
  case "has-bucket": {
    // `wrangler r2 bucket list` prints "name: <bucket>" lines (or JSON in older versions).
    const names = new Set([...input.matchAll(/^\s*name:\s*(\S+)/gm)].map((m) => m[1]));
    try {
      for (const b of jsonFrom(input)) if (b?.name) names.add(b.name);
    } catch {}
    out(names.has(args[0]) ? "yes" : "no");
    break;
  }
  case "zone-id":
    out(jsonFrom(input).result?.[0]?.id || "");
    break;
  case "result-count":
    out(String(jsonFrom(input).result?.length || 0));
    break;
  case "domain-owned":
    out((jsonFrom(input).result || []).some((d) => d.service === args[0]) ? "yes" : "no");
    break;
  case "set-db-id": {
    const [name, id] = args;
    if (!/^[0-9a-f-]{36}$/.test(id)) throw new Error("invalid database id");
    let pending = false;
    let replaced = 0;
    const lines = input.split("\n").map((line) => {
      if (new RegExp(`^\\s*database_name\\s*=\\s*"${name}"\\s*$`).test(line)) pending = true;
      else if (pending && /^\s*database_id\s*=/.test(line)) {
        pending = false;
        replaced++;
        return line.replace(/"[^"]*"/, `"${id}"`);
      }
      return line;
    });
    if (replaced !== 1) throw new Error(`expected exactly one database_id for ${name}, found ${replaced}`);
    out(lines.join("\n"));
    break;
  }
  default:
    console.error(`unknown command ${cmd}`);
    process.exit(2);
}
