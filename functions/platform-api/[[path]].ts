interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

type Surface = "marketing" | "docs" | "shared";
type StaticRoute = { asset: string; surface: Surface; html?: boolean; identity?: string };

const OFFICIAL_LOGO = "/platform-api/assets/logo.svg";
const STATIC_ROUTES: Record<string, StaticRoute> = {
  "/platform-api": { asset: "/platform-api/index.html", surface: "marketing", html: true, identity: 'data-agroai-platform-page="landing"' },
  "/platform-api/": { asset: "/platform-api/index.html", surface: "marketing", html: true, identity: 'data-agroai-platform-page="landing"' },
  "/platform-api/index.html": { asset: "/platform-api/index.html", surface: "marketing", html: true, identity: 'data-agroai-platform-page="landing"' },
  "/platform-api/reference": { asset: "/platform-api/reference.html", surface: "docs", html: true, identity: "<title>API reference" },
  "/platform-api/reference.html": { asset: "/platform-api/reference.html", surface: "docs", html: true, identity: "<title>API reference" },
  "/platform-api/changelog": { asset: "/platform-api/changelog.html", surface: "docs", html: true, identity: "<title>Changelog" },
  "/platform-api/changelog.html": { asset: "/platform-api/changelog.html", surface: "docs", html: true, identity: "<title>Changelog" },
  "/platform-api/docs": { asset: "/platform-api/docs/index.html", surface: "docs", html: true, identity: 'data-agroai-platform-page="docs"' },
  "/platform-api/docs/": { asset: "/platform-api/docs/index.html", surface: "docs", html: true, identity: 'data-agroai-platform-page="docs"' },
  "/platform-api/docs/index.html": { asset: "/platform-api/docs/index.html", surface: "docs", html: true, identity: 'data-agroai-platform-page="docs"' },
  "/platform-api/docs/authentication": { asset: "/platform-api/docs/authentication.html", surface: "docs", html: true, identity: "<title>Authentication" },
  "/platform-api/docs/authentication.html": { asset: "/platform-api/docs/authentication.html", surface: "docs", html: true, identity: "<title>Authentication" },
  "/platform-api/docs/pagination": { asset: "/platform-api/docs/pagination.html", surface: "docs", html: true, identity: "<title>Pagination" },
  "/platform-api/docs/pagination.html": { asset: "/platform-api/docs/pagination.html", surface: "docs", html: true, identity: "<title>Pagination" },
  "/platform-api/docs/errors": { asset: "/platform-api/docs/errors.html", surface: "docs", html: true, identity: "<title>Errors" },
  "/platform-api/docs/errors.html": { asset: "/platform-api/docs/errors.html", surface: "docs", html: true, identity: "<title>Errors" },
  "/platform-api/docs/rate-limits": { asset: "/platform-api/docs/rate-limits.html", surface: "docs", html: true, identity: "<title>Rate limits" },
  "/platform-api/docs/rate-limits.html": { asset: "/platform-api/docs/rate-limits.html", surface: "docs", html: true, identity: "<title>Rate limits" },
  "/platform-api/docs/support": { asset: "/platform-api/docs/support.html", surface: "docs", html: true, identity: "<title>Support" },
  "/platform-api/docs/support.html": { asset: "/platform-api/docs/support.html", surface: "docs", html: true, identity: "<title>Support" },
};

const PRIVATE_ROBOTS_META = /<meta\b(?=[^>]*\bname=["']robots["'])(?=[^>]*\bcontent=["'][^"']*\bnoindex\b[^"']*["'])[^>]*>\s*/gi;
const HTML_FAILURE_MARKERS = /This page doesn[’']t exist|>404<|application\/json|"detail"\s*:|"error"\s*:/i;

function enabled(value: string | undefined): boolean {
  return String(value || "").trim().toLowerCase() === "true";
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

function unavailable(reason: string): Response {
  return new Response("Platform API surface temporarily unavailable", {
    status: 503,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
      "retry-after": "60",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow",
      "x-agroai-platform-api-surface": reason,
    },
  });
}

function staticAsset(pathname: string): StaticRoute | null {
  const route = STATIC_ROUTES[pathname];
  if (route) return route;
  if (/^\/platform-api\/assets\/[A-Za-z0-9._/-]+$/.test(pathname) && !pathname.includes("..")) {
    return { asset: pathname, surface: "shared" };
  }
  if (/^\/platform-api\/contract\/(platform_api_openapi\.json|platform_api_openapi\.sha256)$/.test(pathname)) {
    return { asset: pathname, surface: "docs" };
  }
  return null;
}

function surfaceEnabled(surface: Surface, options: { marketing: boolean; docs: boolean }): boolean {
  if (surface === "marketing") return options.marketing;
  if (surface === "docs") return options.docs;
  return options.marketing || options.docs;
}

function applyHeaders(response: Response, mapping: StaticRoute, indexingEnabled: boolean): Headers {
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("x-frame-options", "DENY");
  headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  headers.set("x-agroai-platform-api-surface", mapping.surface);
  if (indexingEnabled) headers.delete("x-robots-tag");
  else headers.set("x-robots-tag", "noindex, nofollow");
  if (mapping.html) {
    headers.set("content-type", "text/html; charset=utf-8");
    headers.set("cache-control", "private, no-cache, must-revalidate");
  } else {
    headers.set("cache-control", "public, max-age=300, must-revalidate");
  }
  return headers;
}

function normalizePlatformHtml(html: string): string {
  return html
    .replaceAll('/attached_assets/Copy of AGRO-AI (1)_1763408301972.png', OFFICIAL_LOGO)
    .replaceAll('href="https://app.agroai-pilot.com"', 'href="https://platform.agroai-pilot.com"');
}

export const onRequest: PagesFunction<Env> = async (context) => {
  if (!["GET", "HEAD"].includes(context.request.method)) {
    return new Response("Method not allowed", { status: 405, headers: { allow: "GET, HEAD", "cache-control": "no-store" } });
  }

  const url = new URL(context.request.url);
  const mapping = staticAsset(url.pathname);
  if (!mapping) return notFound();

  const marketingEnabled = enabled(context.env.PLATFORM_API_MARKETING_ENABLED);
  const docsEnabled = enabled(context.env.PLATFORM_API_PUBLIC_DOCS_ENABLED);
  const indexingEnabled = enabled(context.env.PLATFORM_API_INDEXING_ENABLED);
  if (!surfaceEnabled(mapping.surface, { marketing: marketingEnabled, docs: docsEnabled })) return notFound();

  const assetUrl = new URL(mapping.asset, "https://agroai-assets.invalid");
  const assetRequest = new Request(assetUrl, {
    method: context.request.method,
    headers: { accept: mapping.html ? "text/html" : (context.request.headers.get("accept") || "*/*") },
    redirect: "manual",
  });
  const response = await context.env.ASSETS.fetch(assetRequest);
  if (response.status === 404) return notFound();
  if (!response.ok) return unavailable("asset-unavailable");

  const headers = applyHeaders(response, mapping, indexingEnabled);
  if (!mapping.html || context.request.method === "HEAD") {
    return new Response(context.request.method === "HEAD" ? null : response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  }

  let html = normalizePlatformHtml(await response.text());
  if ((mapping.identity && !html.includes(mapping.identity)) || HTML_FAILURE_MARKERS.test(html)) {
    return unavailable("identity-mismatch");
  }
  if (indexingEnabled) html = html.replace(PRIVATE_ROBOTS_META, "");
  return new Response(html, { status: 200, headers });
};
