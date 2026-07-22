interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

type Surface = "marketing" | "docs" | "shared";
type StaticRoute = { asset: string; surface: Surface };

const STATIC_ROUTES: Record<string, StaticRoute> = {
  "/platform-api": { asset: "/platform-api/index.html", surface: "marketing" },
  "/platform-api/": { asset: "/platform-api/index.html", surface: "marketing" },
  "/platform-api/index.html": { asset: "/platform-api/index.html", surface: "marketing" },
  "/platform-api/reference": { asset: "/platform-api/reference.html", surface: "docs" },
  "/platform-api/reference.html": { asset: "/platform-api/reference.html", surface: "docs" },
  "/platform-api/changelog": { asset: "/platform-api/changelog.html", surface: "docs" },
  "/platform-api/changelog.html": { asset: "/platform-api/changelog.html", surface: "docs" },
  "/platform-api/docs": { asset: "/platform-api/docs/index.html", surface: "docs" },
  "/platform-api/docs/": { asset: "/platform-api/docs/index.html", surface: "docs" },
  "/platform-api/docs/index.html": { asset: "/platform-api/docs/index.html", surface: "docs" },
  "/platform-api/docs/authentication": { asset: "/platform-api/docs/authentication.html", surface: "docs" },
  "/platform-api/docs/authentication.html": { asset: "/platform-api/docs/authentication.html", surface: "docs" },
  "/platform-api/docs/pagination": { asset: "/platform-api/docs/pagination.html", surface: "docs" },
  "/platform-api/docs/pagination.html": { asset: "/platform-api/docs/pagination.html", surface: "docs" },
  "/platform-api/docs/errors": { asset: "/platform-api/docs/errors.html", surface: "docs" },
  "/platform-api/docs/errors.html": { asset: "/platform-api/docs/errors.html", surface: "docs" },
  "/platform-api/docs/rate-limits": { asset: "/platform-api/docs/rate-limits.html", surface: "docs" },
  "/platform-api/docs/rate-limits.html": { asset: "/platform-api/docs/rate-limits.html", surface: "docs" },
  "/platform-api/docs/support": { asset: "/platform-api/docs/support.html", surface: "docs" },
  "/platform-api/docs/support.html": { asset: "/platform-api/docs/support.html", surface: "docs" },
};

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

export const onRequest: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);
  const mapping = staticAsset(url.pathname);
  if (!mapping) return notFound();

  const marketingEnabled = enabled(context.env.PLATFORM_API_MARKETING_ENABLED);
  const docsEnabled = enabled(context.env.PLATFORM_API_PUBLIC_DOCS_ENABLED);
  const indexingEnabled = enabled(context.env.PLATFORM_API_INDEXING_ENABLED);
  if (!surfaceEnabled(mapping.surface, { marketing: marketingEnabled, docs: docsEnabled })) return notFound();

  const assetUrl = new URL(context.request.url);
  assetUrl.pathname = mapping.asset;
  const response = await context.env.ASSETS.fetch(new Request(assetUrl, context.request));
  if (!response.ok) return notFound();

  const headers = new Headers(response.headers);
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("x-frame-options", "DENY");
  if (mapping.asset.endsWith(".html")) {
    headers.set("cache-control", "private, no-cache, must-revalidate");
    if (indexingEnabled) headers.delete("x-robots-tag");
    else headers.set("x-robots-tag", "noindex, nofollow");
  } else {
    headers.set("cache-control", "public, max-age=300, must-revalidate");
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
};
