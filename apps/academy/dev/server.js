// Local development server: runs the production Worker unchanged on Node 22
// with a D1-compatible SQLite database and a filesystem assets binding.
//
//   node dev/server.js [--port 8787] [--db dev/.data/academy.sqlite] [--fresh]
//
// The development mailbox at /__dev/mail lists queued emails (development only).
import { createServer } from "node:http";
import { readFile, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { D1Shim, applyMigrations } from "./d1-shim.js";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const args = process.argv.slice(2);
const arg = (name, def) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : def;
};
const port = Number(arg("port", process.env.PORT || 8787));
const dbPath = arg("db", process.env.ACADEMY_DB || join(here, ".data", "academy.sqlite"));

const TYPES = { ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webmanifest": "application/manifest+json", ".json": "application/json", ".jpg": "image/jpeg" };

export function assetsBinding(dir = join(root, "public")) {
  return {
    async fetch(req) {
      const url = new URL(req.url);
      const p = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, "");
      const file = join(dir, p);
      if (!file.startsWith(dir)) return new Response("Not found", { status: 404 });
      try {
        const body = await readFile(file);
        return new Response(body, { headers: { "Content-Type": TYPES[extname(file)] || "application/octet-stream" } });
      } catch {
        return new Response("Not found", { status: 404 });
      }
    },
  };
}

export async function createDb(path) {
  if (path !== ":memory:") await mkdir(dirname(path), { recursive: true });
  const fresh = path === ":memory:" || !existsSync(path);
  const db = new D1Shim(path);
  if (fresh) applyMigrations(db, join(root, "migrations"));
  return db;
}

async function main() {
  if (args.includes("--fresh") && existsSync(dbPath)) await rm(dbPath);
  const DB = await createDb(dbPath);
  const worker = (await import("../src/index.js")).default;
  const origin = `http://localhost:${port}`;
  const env = {
    DB,
    ASSETS: assetsBinding(),
    APP_ORIGIN: origin,
    ENVIRONMENT: "development",
    DEV_MAILBOX: "1",
    BOOTSTRAP_ADMIN_EMAILS: process.env.BOOTSTRAP_ADMIN_EMAILS || "admin@academy.test",
    CERT_SIGNING_SECRET: process.env.CERT_SIGNING_SECRET || "development-only-certificate-secret",
  };

  createServer(async (req, res) => {
    try {
      const url = new URL(req.url, origin);
      if (url.pathname === "/__dev/mail") {
        const rows = (await DB.prepare("SELECT to_email, template, subject, text, created_at FROM email_outbox ORDER BY created_at DESC LIMIT 50").all()).results;
        res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
        return res.end(JSON.stringify(rows, null, 2));
      }
      if (url.pathname === "/__dev/cron") {
        const out = await worker.scheduled({ cron: url.searchParams.get("cron") || "" }, env, { waitUntil: (p) => p });
        res.writeHead(200);
        return res.end(JSON.stringify(out ?? { ok: true }));
      }
      const chunks = [];
      for await (const ch of req) chunks.push(ch);
      const body = chunks.length ? Buffer.concat(chunks) : undefined;
      const headers = new Headers();
      for (const [k, v] of Object.entries(req.headers)) if (v != null) headers.set(k, Array.isArray(v) ? v.join(", ") : v);
      const request = new Request(url, { method: req.method, headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body });
      const pending = [];
      const response = await worker.fetch(request, env, { waitUntil: (p) => pending.push(p) });
      const outHeaders = {};
      response.headers.forEach((v, k) => {
        if (k === "set-cookie") return;
        outHeaders[k] = v;
      });
      const cookies = response.headers.getSetCookie?.() || [];
      if (cookies.length) outHeaders["set-cookie"] = cookies;
      res.writeHead(response.status, outHeaders);
      res.end(req.method === "HEAD" ? undefined : Buffer.from(await response.arrayBuffer()));
      await Promise.allSettled(pending);
    } catch (e) {
      console.error(e);
      res.writeHead(500);
      res.end("dev server error");
    }
  }).listen(port, () => console.log(`AGRO-AI Academy dev server: ${origin}  (db: ${dbPath})`));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
