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
const MAIN_SITE_LOGO = "/platform-api/assets/logo.svg";

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
      "style-src 'self' 'unsafe-inline' https://fonts.cdnfonts.com",
      "script-src 'none'",
      "connect-src 'self'",
      "font-src 'self' data: https://fonts.cdnfonts.com",
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

function normalizePath(pathname: string): string {
  const clean = pathname === "/" ? pathname : pathname.replace(/\/+$/, "");
  return clean.endsWith(".html") ? clean.slice(0, -5) : clean;
}

function active(pathname: string, target: string): string {
  return normalizePath(pathname) === target ? ' aria-current="page"' : "";
}

function mainSiteHeader(): string {
  return `<header class="top" data-agroai-main-shell="true"><div class="site-nav"><a class="brand" href="/" aria-label="AGRO-AI home"><img src="${MAIN_SITE_LOGO}" alt="AGRO-AI"></a><nav class="mainnav" aria-label="Primary navigation"><a href="/#platform">Platform</a><a href="/integrations">Integrations</a><a href="/#intelligence">Intelligence</a><a href="/docs">Docs</a><a href="/guides/">Guide</a><a href="/news">News</a><a href="/insights">Insights</a><a href="/about">Company</a></nav><div class="navactions"><a class="portalbtn" href="https://app.agroai-pilot.com">Open Portal</a><a class="demobtn" href="/book-a-demo">Book a Demo</a></div></div></header>`;
}

function trustLegalNavigation(pathname: string): string {
  return `<section class="trustnav shell" aria-label="AGRO-AI Trust and Legal"><div class="trustnav-head"><strong>AGRO-AI TRUST &amp; LEGAL</strong><span>Contractual documents and standards explaining how AGRO-AI governs agricultural, operational and personal data.</span></div><div class="trustnav-row"><b>Trust &amp; data governance</b><div class="trustnav-links"><a href="/trust"${active(pathname, "/trust")}>Trust Center</a><a href="/trust/data-governance"${active(pathname, "/trust/data-governance")}>Data Governance</a><a href="/trust/privacy"${active(pathname, "/trust/privacy")}>Privacy Notice</a><a href="/trust/ai-data-use"${active(pathname, "/trust/ai-data-use")}>AI &amp; Model Data Use</a><a href="/trust/security"${active(pathname, "/trust/security")}>Security</a></div></div><div class="trustnav-row"><b>Legal documents</b><div class="trustnav-links"><a href="/terms-of-service">Terms of Service</a><a href="/privacy-policy">Privacy Policy</a><a href="/pilot-agreement">Pilot Agreement</a></div></div></section>`;
}

function themeTrustHtml(html: string, pathname: string): string {
  const shell = `${mainSiteHeader()}${trustLegalNavigation(pathname)}`;
  let themed = html.replace(/<header class="top">[\s\S]*?<\/header>/i, shell);
  if (!themed.includes("fonts.cdnfonts.com/css/glacial-indifference-2")) {
    themed = themed.replace("</head>", '<link rel="preconnect" href="https://fonts.cdnfonts.com"><link rel="stylesheet" href="https://fonts.cdnfonts.com/css/glacial-indifference-2"></head>');
  }
  return themed;
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
  if (request.method === "HEAD") return new Response(null, { status: 200, headers: trustHeaders(contentType) });
  if (contentType.includes("text/html")) {
    const themed = themeTrustHtml(await upstream.text(), new URL(request.url).pathname);
    return new Response(themed, { status: 200, headers: trustHeaders(contentType) });
  }
  return new Response(upstream.body, { status: 200, headers: trustHeaders(contentType) });
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
