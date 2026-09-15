// AGRO-AI Trust Center · isolated /trust* production surface · v2026-09
const RAW_BASE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/trust";

const ROUTES: Record<string, string> = {
  "/trust/": `${RAW_BASE}/index.html`,
  "/trust/privacy/": `${RAW_BASE}/privacy/index.html`,
  "/trust/data-governance/": `${RAW_BASE}/data-governance/index.html`,
  "/trust/ai-data-use/": `${RAW_BASE}/ai-data-use/index.html`,
  "/trust/security/": `${RAW_BASE}/security/index.html`,
  "/trust/subprocessors/": `${RAW_BASE}/subprocessors/index.html`,
  "/trust/farm-data-covenant/": `${RAW_BASE}/farm-data-covenant/index.html`,
};

function canonicalPath(pathname: string): string | null {
  if (ROUTES[pathname]) return pathname;
  if (pathname === "/trust") return "/trust/";
  const withSlash = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return ROUTES[withSlash] ? withSlash : null;
}

function responseHeaders(): Headers {
  const headers = new Headers();
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "public, max-age=60, s-maxage=60, stale-while-revalidate=300");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-frame-options", "DENY");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  headers.set("content-security-policy", [
    "default-src 'none'",
    "style-src 'unsafe-inline' https://fonts.cdnfonts.com",
    "font-src https://fonts.cdnfonts.com data:",
    "img-src 'self' https://agroai-pilot.com data:",
    "script-src 'none'",
    "connect-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "object-src 'none'",
  ].join("; "));
  return headers;
}

function notFound(): Response {
  return new Response("Not found", {
    status: 404,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow",
    },
  });
}

export default {
  async fetch(request: Request): Promise<Response> {
    if (request.method !== "GET" && request.method !== "HEAD") return notFound();

    const url = new URL(request.url);
    const canonical = canonicalPath(url.pathname);
    if (!canonical) return notFound();

    if (url.pathname !== canonical) {
      const destination = new URL(canonical, url.origin);
      destination.search = url.search;
      return Response.redirect(destination.toString(), 308);
    }

    const sourceUrl = ROUTES[canonical];
    const upstream = await fetch(sourceUrl, {
      cf: { cacheEverything: true, cacheTtl: 60 },
      headers: { "user-agent": "AGRO-AI-Trust-Center/1.0" },
    });

    if (!upstream.ok) {
      return new Response("AGRO-AI Trust Center is temporarily unavailable.", {
        status: 503,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store",
          "retry-after": "60",
          "x-content-type-options": "nosniff",
        },
      });
    }

    const headers = responseHeaders();
    if (request.method === "HEAD") return new Response(null, { status: 200, headers });
    return new Response(await upstream.text(), { status: 200, headers });
  },
};