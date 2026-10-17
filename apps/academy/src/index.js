// Cloudflare Worker entry point for AGRO-AI Academy.
import { handle } from "./app.js";
import { runScheduled } from "./services/jobs.js";

const STATIC_PREFIXES = ["/static/"];
const STATIC_FILES = new Set(["/favicon.ico", "/favicon.svg", "/apple-touch-icon.png", "/site.webmanifest"]);

async function serveAsset(req, env) {
  const url = new URL(req.url);
  if (!env.ASSETS) return new Response("Not found", { status: 404 });
  const res = await env.ASSETS.fetch(new Request(url.origin + url.pathname, req));
  if (!res.ok) return res;
  const out = new Response(res.body, res);
  // Assets referenced with ?v=<build> are immutable; others revalidate hourly.
  out.headers.set("Cache-Control", url.searchParams.has("v") ? "public, max-age=31536000, immutable" : "public, max-age=3600");
  out.headers.set("X-Content-Type-Options", "nosniff");
  return out;
}

export default {
  async fetch(req, env, ctx) {
    const { pathname } = new URL(req.url);
    if ((req.method === "GET" || req.method === "HEAD") && (STATIC_FILES.has(pathname) || STATIC_PREFIXES.some((p) => pathname.startsWith(p)))) {
      return serveAsset(req, env);
    }
    return handle(req, env, ctx);
  },
  async scheduled(event, env) {
    return runScheduled(env, event.cron);
  },
};
