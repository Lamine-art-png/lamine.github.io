interface Env {
  MARKETING_ORIGIN?: string;
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

type Surface = "marketing" | "docs" | "shared";
type Route = { upstreamPath: string; surface: Surface; html: boolean };

const DEFAULT_MARKETING_ORIGIN = "https://agroai-343.pages.dev";
const PLATFORM_CONSOLE = "https://platform.agroai-pilot.com";
const PRIVATE_ROBOTS_META = /<meta\b(?=[^>]*\bname=["']robots["'])(?=[^>]*\bcontent=["'][^"']*\bnoindex\b[^"']*["'])[^>]*>\s*/gi;

const STATIC_ROUTES: Record<string, Route> = {
  "/platform-api": { upstreamPath: "/platform-api/index.html", surface: "marketing", html: true },
  "/platform-api/": { upstreamPath: "/platform-api/index.html", surface: "marketing", html: true },
  "/platform-api/index.html": { upstreamPath: "/platform-api/index.html", surface: "marketing", html: true },
  "/platform-api/reference": { upstreamPath: "/platform-api/reference.html", surface: "docs", html: true },
  "/platform-api/reference.html": { upstreamPath: "/platform-api/reference.html", surface: "docs", html: true },
  "/platform-api/changelog": { upstreamPath: "/platform-api/changelog.html", surface: "docs", html: true },
  "/platform-api/changelog.html": { upstreamPath: "/platform-api/changelog.html", surface: "docs", html: true },
  "/platform-api/docs": { upstreamPath: "/platform-api/docs/index.html", surface: "docs", html: true },
  "/platform-api/docs/": { upstreamPath: "/platform-api/docs/index.html", surface: "docs", html: true },
  "/platform-api/docs/index.html": { upstreamPath: "/platform-api/docs/index.html", surface: "docs", html: true },
  "/platform-api/docs/authentication": { upstreamPath: "/platform-api/docs/authentication.html", surface: "docs", html: true },
  "/platform-api/docs/authentication.html": { upstreamPath: "/platform-api/docs/authentication.html", surface: "docs", html: true },
  "/platform-api/docs/pagination": { upstreamPath: "/platform-api/docs/pagination.html", surface: "docs", html: true },
  "/platform-api/docs/pagination.html": { upstreamPath: "/platform-api/docs/pagination.html", surface: "docs", html: true },
  "/platform-api/docs/errors": { upstreamPath: "/platform-api/docs/errors.html", surface: "docs", html: true },
  "/platform-api/docs/errors.html": { upstreamPath: "/platform-api/docs/errors.html", surface: "docs", html: true },
  "/platform-api/docs/rate-limits": { upstreamPath: "/platform-api/docs/rate-limits.html", surface: "docs", html: true },
  "/platform-api/docs/rate-limits.html": { upstreamPath: "/platform-api/docs/rate-limits.html", surface: "docs", html: true },
  "/platform-api/docs/support": { upstreamPath: "/platform-api/docs/support.html", surface: "docs", html: true },
  "/platform-api/docs/support.html": { upstreamPath: "/platform-api/docs/support.html", surface: "docs", html: true },
};

function enabled(value: string | undefined): boolean {
  return String(value || "").trim().toLowerCase() === "true";
}

function routeFor(pathname: string): Route | null {
  const staticRoute = STATIC_ROUTES[pathname];
  if (staticRoute) return staticRoute;
  if (/^\/platform-api\/assets\/[A-Za-z0-9._/-]+$/.test(pathname) && !pathname.includes("..")) {
    return { upstreamPath: pathname, surface: "shared", html: false };
  }
  if (/^\/platform-api\/contract\/(platform_api_openapi\.json|platform_api_openapi\.sha256)$/.test(pathname)) {
    return { upstreamPath: pathname, surface: "docs", html: false };
  }
  return null;
}

function surfaceEnabled(surface: Surface, marketing: boolean, docs: boolean): boolean {
  if (surface === "marketing") return marketing;
  if (surface === "docs") return docs;
  return marketing || docs;
}

function safeOrigin(value: string | undefined): URL {
  const origin = new URL(String(value || DEFAULT_MARKETING_ORIGIN));
  if (origin.protocol !== "https:" || origin.username || origin.password || origin.search || origin.hash) {
    throw new Error("Invalid marketing origin");
  }
  return origin;
}

function notFound(): Response {
  return new Response("Not found", {
    status: 404,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow",
      "x-agroai-platform-api-surface": "closed",
    },
  });
}

function unavailable(): Response {
  return new Response("Platform API surface temporarily unavailable", {
    status: 503,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
      "retry-after": "60",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow",
      "x-agroai-platform-api-surface": "upstream-unavailable",
    },
  });
}

function responseHeaders(upstream: Response, route: Route, indexing: boolean): Headers {
  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("x-frame-options", "DENY");
  headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  headers.set("x-agroai-platform-api-surface", route.surface);
  if (indexing) headers.delete("x-robots-tag");
  else headers.set("x-robots-tag", "noindex, nofollow");
  if (route.html) {
    headers.set("content-type", "text/html; charset=utf-8");
    headers.set("cache-control", "private, no-cache, must-revalidate");
  } else {
    headers.set("cache-control", "public, max-age=300, must-revalidate");
  }
  return headers;
}

function normalizeHtml(html: string, route: Route): string {
  let normalized = html
    .replaceAll("https://app.agroai-pilot.com/developers/api/apply?type=developer_beta", PLATFORM_CONSOLE)
    .replaceAll("https://app.agroai-pilot.com/developers/api/apply?type=strategic_partner", PLATFORM_CONSOLE)
    .replaceAll('href="https://app.agroai-pilot.com"', `href="${PLATFORM_CONSOLE}"`);
  if (route.surface === "marketing" && route.upstreamPath.endsWith("index.html")) {
    normalized = normalized.replace(/<title>[\s\S]*?<\/title>/i, "<title>AGRO-AI Platform API</title>");
  }
  if (route.surface === "docs" && route.upstreamPath === "/platform-api/docs/index.html") {
    normalized = normalized.replace(/<title>[\s\S]*?<\/title>/i, "<title>AGRO-AI Platform API Documentation</title>");
  }
  return normalized;
}

async function proxy(request: Request, env: Env, route: Route, indexing: boolean): Promise<Response> {
  let origin: URL;
  try {
    origin = safeOrigin(env.MARKETING_ORIGIN);
  } catch (_error) {
    return unavailable();
  }

  const incoming = new URL(request.url);
  const upstreamUrl = new URL(route.upstreamPath, origin);
  upstreamUrl.search = incoming.search;
  const upstream = await fetch(upstreamUrl.toString(), {
    method: request.method,
    redirect: "follow",
    headers: {
      accept: request.headers.get("accept") || "*/*",
      "user-agent": "AGRO-AI-Platform-Marketing/1.0",
    },
    cf: { cacheEverything: !route.html, cacheTtl: route.html ? 0 : 300 },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });

  if (upstream.status === 404) return notFound();
  if (!upstream.ok) return unavailable();

  const headers = responseHeaders(upstream, route, indexing);
  if (!route.html || request.method === "HEAD") {
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  }

  let html = normalizeHtml(await upstream.text(), route);
  if (indexing) html = html.replace(PRIVATE_ROBOTS_META, "");
  return new Response(html, { status: upstream.status, statusText: upstream.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method not allowed", {
        status: 405,
        headers: { allow: "GET, HEAD", "cache-control": "no-store", "x-robots-tag": "noindex, nofollow" },
      });
    }

    const url = new URL(request.url);
    const route = routeFor(url.pathname);
    if (!route) return notFound();

    const marketing = enabled(env.PLATFORM_API_MARKETING_ENABLED);
    const docs = enabled(env.PLATFORM_API_PUBLIC_DOCS_ENABLED);
    if (!surfaceEnabled(route.surface, marketing, docs)) return notFound();

    return proxy(request, env, route, enabled(env.PLATFORM_API_INDEXING_ENABLED));
  },
};
