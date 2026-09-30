// Production-like release harness for browser tests of release convergence.
//
// Serves one of several built portal releases (directories) from one origin
// with the production cache policy (public/_headers + functions/assets):
//   - "/" and index.html: no-store; SPA deep routes: max-age=0, must-revalidate
//   - /sw.js, /deployment.json: no-store
//   - /assets/*: immutable when present; honest uncached 404 when missing
// and a small mock of the /v1 API. Control endpoints switch the live release
// ("deploy"/"rollback"), emulate partial propagation (deployment.json says
// one release while the shell is still another) and expose what the portal
// reported. Test-only; never deployed.
//
//   node tests/release-harness/server.mjs --port 4400 --release A=dir --release B=dir --live A
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const args = process.argv.slice(2);
const releases = new Map();
let port = 4400;
let live = null;
for (let i = 0; i < args.length; i += 1) {
  if (args[i] === "--port") port = Number(args[++i]);
  else if (args[i] === "--release") {
    const [name, dir] = args[++i].split("=");
    releases.set(name, dir);
  } else if (args[i] === "--live") live = args[++i];
}
if (!live || !releases.has(live)) throw new Error("--live must name a --release");

let shellRelease = live; // partial propagation: shell may lag deployment.json
const events = [];
const clientBuilds = [];

const TYPES = { ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json", ".txt": "text/plain; charset=utf-8", ".woff2": "font/woff2", ".png": "image/png" };

const session = {
  user: { id: "u-release", email: "release@example.com", name: "Release Tester", email_verified: true },
  current_organization: { id: "o-release", name: "Release Farm", role: "owner", plan: "team", subscription_status: "active" },
  organizations: [{ id: "o-release", name: "Release Farm", role: "owner", plan: "team", subscription_status: "active" }],
  workspaces: [{ id: "w-release", name: "Main", organization_id: "o-release" }],
  entitlements: {},
};

function send(res, status, body, headers = {}) {
  res.writeHead(status, { "x-content-type-options": "nosniff", ...headers });
  res.end(body);
}

function fileFrom(release, pathname) {
  const root = releases.get(release);
  const target = normalize(join(root, pathname));
  if (!target.startsWith(normalize(root))) return null;
  return existsSync(target) && statSync(target).isFile() ? target : null;
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (chunk) => { data += chunk; });
    req.on("end", () => resolve(data));
  });
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;

  if (path.startsWith("/__harness/")) {
    if (path === "/__harness/deploy") {
      live = url.searchParams.get("release");
      shellRelease = url.searchParams.get("shell") || live;
      return send(res, 200, JSON.stringify({ live, shellRelease }), { "content-type": "application/json" });
    }
    if (path === "/__harness/events") return send(res, 200, JSON.stringify(events), { "content-type": "application/json" });
    if (path === "/__harness/client-builds") return send(res, 200, JSON.stringify(clientBuilds), { "content-type": "application/json" });
    return send(res, 404, "unknown harness endpoint");
  }

  if (path.startsWith("/v1/")) {
    const build = req.headers["x-agroai-client-build"];
    if (build) clientBuilds.push({ path, build });
    if (path === "/v1/client/release-events") {
      try { events.push(JSON.parse(await readBody(req))); } catch { /* ignore */ }
      return send(res, 202, "{}", { "content-type": "application/json", "cache-control": "no-store" });
    }
    const json = (body, status = 200) => send(res, status, JSON.stringify(body), { "content-type": "application/json", "cache-control": "no-store" });
    if (path === "/v1/auth/bootstrap" || path === "/v1/auth/me") {
      return req.headers.authorization ? json(session) : json({ detail: "Not authenticated" }, 401);
    }
    if (req.method === "GET") return json({});
    await readBody(req);
    return json({ status: "ok" });
  }

  if (path === "/deployment.json") {
    const file = fileFrom(live, "deployment.json");
    return file ? send(res, 200, readFileSync(file), { "content-type": TYPES[".json"], "cache-control": "no-store, max-age=0, must-revalidate" }) : send(res, 404, "missing", { "cache-control": "no-store" });
  }
  if (path === "/sw.js") {
    const file = fileFrom(shellRelease, "sw.js");
    return send(res, 200, readFileSync(file), { "content-type": TYPES[".js"], "cache-control": "no-store, max-age=0, must-revalidate", "service-worker-allowed": "/" });
  }
  if (path.startsWith("/assets/")) {
    // Assets of every release that is live or still propagating are served;
    // anything else was retired by the deployment.
    const file = fileFrom(live, path) || fileFrom(shellRelease, path);
    if (!file) return send(res, 404, "AGRO-AI asset not found in the current release", { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
    return send(res, 200, readFileSync(file), { "content-type": TYPES[extname(file)] || "application/octet-stream", "cache-control": "public, max-age=31536000, immutable" });
  }
  const staticFile = path !== "/" && fileFrom(shellRelease, path);
  if (staticFile && !staticFile.endsWith(".html")) {
    return send(res, 200, readFileSync(staticFile), { "content-type": TYPES[extname(staticFile)] || "application/octet-stream", "cache-control": "no-cache, max-age=0, must-revalidate" });
  }
  const shell = readFileSync(fileFrom(shellRelease, "index.html"));
  const cache = path === "/" ? "no-store, max-age=0, must-revalidate" : "public, max-age=0, must-revalidate";
  return send(res, 200, shell, { "content-type": TYPES[".html"], "cache-control": cache });
}).listen(port, "127.0.0.1", () => console.log(`release harness on ${port} serving ${live}`));
