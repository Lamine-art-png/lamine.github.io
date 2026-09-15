import currentHandler from "./emergency";

interface Env {
  ASSETS: Fetcher;
  MARKETING_ORIGIN?: string;
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

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

async function trustAsset(request: Request, env: Env, assetPath: string): Promise<Response> {
  const assetUrl = new URL(assetPath, "https://agroai-trust-assets.invalid");
  const upstream = await env.ASSETS.fetch(new Request(assetUrl, {
    method: request.method,
    headers: { accept: assetPath.endsWith(".css") ? "text/css,*/*;q=0.1" : "text/html,*/*;q=0.1" },
    redirect: "manual",
  }));
  if (!upstream.ok) return new Response("Trust Center temporarily unavailable", { status: upstream.status === 404 ? 404 : 503, headers: trustHeaders("text/plain; charset=utf-8") });
  const contentType = assetPath.endsWith(".css") ? "text/css; charset=utf-8" : "text/html; charset=utf-8";
  const headers = trustHeaders(contentType);
  return new Response(request.method === "HEAD" ? null : upstream.body, { status: 200, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (["GET", "HEAD"].includes(request.method)) {
      const mapped = TRUST_ROUTES[url.pathname];
      if (mapped) return trustAsset(request, env, mapped);
      if (url.pathname === "/trust/trust.css") return trustAsset(request, env, "/trust/trust.css");
      if (url.pathname.startsWith("/trust/")) return new Response("Not found", { status: 404, headers: trustHeaders("text/plain; charset=utf-8") });
    }
    return (currentHandler as ExportedHandler<Env>).fetch!(request, env, ctx);
  },
} satisfies ExportedHandler<Env>;
