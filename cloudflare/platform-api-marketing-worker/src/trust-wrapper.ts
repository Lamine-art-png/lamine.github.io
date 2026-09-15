import currentHandler from "./emergency";

interface Env {
  ASSETS: Fetcher;
  MARKETING_ORIGIN?: string;
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

const DEFAULT_MARKETING_ORIGIN = "https://agroai-343.pages.dev";
const LEGAL_ROUTES = new Set(["/terms-of-service", "/privacy-policy", "/pilot-agreement"]);
const INTEGRATION_TAGS = '<link rel="stylesheet" href="/trust/legal-integration.css"><script src="/trust/legal-integration.js" defer></script>';

const TRUST_ROUTES: Record<string, string> = {
  "/trust": "/trust/index.html",
  "/trust/": "/trust/index.html",
  "/trust/index.html": "/trust/index.html",
  "/trust/data-governance": "/trust/data-governance.html",
  "/trust/data-governance/": "/trust/data-governance.html",
  "/trust/data-governance.html": "/trust/data-governance.html",
  "/trust/privacy": "/trust/privacy.html",
  "/trust/privacy/": "/trust/privacy.html",
  "/trust/privacy.html": "/trust/privacy.html",
  "/trust/ai-data-use": "/trust/ai-data-use.html",
  "/trust/ai-data-use/": "/trust/ai-data-use.html",
  "/trust/ai-data-use.html": "/trust/ai-data-use.html",
  "/trust/security": "/trust/security.html",
  "/trust/security/": "/trust/security.html",
  "/trust/security.html": "/trust/security.html",
};

function trustHeaders(contentType: string): Headers {
  return new Headers({
    "content-type": contentType,
    "cache-control": contentType.includes("text/html") ? "public, max-age=300, must-revalidate" : "public, max-age=3600, must-revalidate",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "content-security-policy": [
      "default-src 'self'",
      "img-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      "script-src 'none'",
      "connect-src 'self'",
      "font-src 'self' data:",
      "form-action 'self' mailto:",
      "base-uri 'none'",
      "frame-ancestors 'none'",
    ].join("; "),
  });
}

function trustContentType(assetPath: string): string {
  if (assetPath.endsWith(".css")) return "text/css; charset=utf-8";
  if (assetPath.endsWith(".js")) return "application/javascript; charset=utf-8";
  return "text/html; charset=utf-8";
}

async function trustAsset(request: Request, env: Env, assetPath: string): Promise<Response> {
  const contentType = trustContentType(assetPath);
  const assetUrl = new URL(assetPath, "https://agroai-trust-assets.invalid");
  const upstream = await env.ASSETS.fetch(new Request(assetUrl, {
    method: request.method,
    headers: { accept: contentType.includes("javascript") ? "application/javascript,*/*;q=0.1" : contentType.includes("css") ? "text/css,*/*;q=0.1" : "text/html,*/*;q=0.1" },
    redirect: "manual",
  }));
  if (!upstream.ok) return new Response("Trust Center temporarily unavailable", { status: upstream.status === 404 ? 404 : 503, headers: trustHeaders("text/plain; charset=utf-8") });
  return new Response(request.method === "HEAD" ? null : upstream.body, { status: 200, headers: trustHeaders(contentType) });
}

function safeMarketingOrigin(value: string | undefined): URL {
  const origin = new URL(String(value || DEFAULT_MARKETING_ORIGIN));
  if (origin.protocol !== "https:" || origin.username || origin.password || origin.search || origin.hash) throw new Error("Invalid marketing origin");
  return origin;
}

async function withTrustLegalIntegration(upstream: Response, request: Request): Promise<Response> {
  if (request.method === "HEAD" || !upstream.ok || !String(upstream.headers.get("content-type") || "").includes("text/html")) return upstream;
  let html = await upstream.text();
  if (!html.includes("/trust/legal-integration.js")) html = html.includes("</head>") ? html.replace("</head>", `${INTEGRATION_TAGS}</head>`) : `${INTEGRATION_TAGS}${html}`;
  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("x-content-type-options", "nosniff");
  return new Response(html, { status: upstream.status, statusText: upstream.statusText, headers });
}

async function legalPage(request: Request, env: Env): Promise<Response> {
  const incoming = new URL(request.url);
  const origin = safeMarketingOrigin(env.MARKETING_ORIGIN);
  const target = new URL(incoming.pathname + incoming.search, origin);
  const upstream = await fetch(new Request(target, {
    method: request.method,
    headers: { accept: request.headers.get("accept") || "text/html,*/*;q=0.8" },
    redirect: "follow",
  }));
  return withTrustLegalIntegration(upstream, request);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (["GET", "HEAD"].includes(request.method)) {
      const mapped = TRUST_ROUTES[url.pathname];
      if (mapped) return trustAsset(request, env, mapped);
      if (["/trust/trust.css", "/trust/legal-integration.css", "/trust/legal-integration.js"].includes(url.pathname)) return trustAsset(request, env, url.pathname);
      if (url.pathname.startsWith("/trust/")) return new Response("Not found", { status: 404, headers: trustHeaders("text/plain; charset=utf-8") });
      const normalizedPath = url.pathname !== "/" ? url.pathname.replace(/\/+$/, "") : url.pathname;
      if (LEGAL_ROUTES.has(normalizedPath)) return legalPage(request, env);
      if (url.pathname === "/") {
        const upstream = await (currentHandler as ExportedHandler<Env>).fetch!(request, env, ctx);
        return withTrustLegalIntegration(upstream, request);
      }
    }
    return (currentHandler as ExportedHandler<Env>).fetch!(request, env, ctx);
  },
} satisfies ExportedHandler<Env>;
