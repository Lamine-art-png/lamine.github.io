interface Env {
  ASSETS: Fetcher;
}

type Route = {
  assetPath: string;
  html: boolean;
  identity?: string;
  indexing: boolean;
};

const STATIC_ROUTES: Record<string, Route> = {
  "/guides": { assetPath: "/index.html", html: true, identity: "<title>AGRO-AI Guides | Enterprise Portal & Platform API</title>", indexing: true },
  "/guides/": { assetPath: "/index.html", html: true, identity: "<title>AGRO-AI Guides | Enterprise Portal & Platform API</title>", indexing: true },
  "/guides/index.html": { assetPath: "/index.html", html: true, identity: "<title>AGRO-AI Guides | Enterprise Portal & Platform API</title>", indexing: true },
  "/guides/enterprise-portal": { assetPath: "/enterprise-portal/index.html", html: true, identity: "<title>AGRO-AI Enterprise Portal Guide</title>", indexing: true },
  "/guides/enterprise-portal/": { assetPath: "/enterprise-portal/index.html", html: true, identity: "<title>AGRO-AI Enterprise Portal Guide</title>", indexing: true },
  "/guides/enterprise-portal/index.html": { assetPath: "/enterprise-portal/index.html", html: true, identity: "<title>AGRO-AI Enterprise Portal Guide</title>", indexing: true },
  "/guides/platform-api": { assetPath: "/platform-api/index.html", html: true, identity: "<title>AGRO-AI Platform API Guide</title>", indexing: false },
  "/guides/platform-api/": { assetPath: "/platform-api/index.html", html: true, identity: "<title>AGRO-AI Platform API Guide</title>", indexing: false },
  "/guides/platform-api/index.html": { assetPath: "/platform-api/index.html", html: true, identity: "<title>AGRO-AI Platform API Guide</title>", indexing: false },
};

function routeFor(pathname: string): Route | null {
  const exact = STATIC_ROUTES[pathname];
  if (exact) return exact;
  if (/^\/guides\/assets\/[A-Za-z0-9._/-]+$/.test(pathname) && !pathname.includes("..")) {
    return {
      assetPath: pathname.slice("/guides".length),
      html: false,
      indexing: false,
    };
  }
  return null;
}

function baseHeaders(route: Route, upstream?: Headers): Headers {
  const headers = new Headers(upstream);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("x-frame-options", "DENY");
  headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  headers.set("x-agroai-guides-surface", route.html ? "guide" : "asset");
  if (route.indexing) headers.delete("x-robots-tag");
  else headers.set("x-robots-tag", "noindex, nofollow");
  if (route.html) {
    headers.set("content-type", "text/html; charset=utf-8");
    headers.set("cache-control", "public, max-age=0, must-revalidate");
  } else {
    headers.set("cache-control", "public, max-age=3600, must-revalidate");
  }
  return headers;
}

function notFound(): Response {
  return new Response("Not found", {
    status: 404,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow",
      "x-agroai-guides-surface": "closed",
    },
  });
}

function unavailable(): Response {
  return new Response("AGRO-AI Guides temporarily unavailable", {
    status: 503,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
      "retry-after": "60",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow",
      "x-agroai-guides-surface": "asset-unavailable",
    },
  });
}

async function serve(request: Request, env: Env, route: Route): Promise<Response> {
  const assetUrl = new URL(route.assetPath, "https://agroai-guides-assets.invalid");
  const upstream = await env.ASSETS.fetch(
    new Request(assetUrl, {
      method: request.method,
      headers: { accept: route.html ? "text/html" : (request.headers.get("accept") || "*/*") },
      redirect: "manual",
    }),
  );

  if (upstream.status === 404) return notFound();
  if (!upstream.ok) return unavailable();

  const headers = baseHeaders(route, upstream.headers);
  if (!route.html || request.method === "HEAD") {
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  }

  const html = await upstream.text();
  if (!route.identity || !html.includes(route.identity)) return unavailable();
  return new Response(html, { status: 200, headers });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method not allowed", {
        status: 405,
        headers: {
          allow: "GET, HEAD",
          "cache-control": "no-store",
          "x-robots-tag": "noindex, nofollow",
        },
      });
    }

    const route = routeFor(new URL(request.url).pathname);
    if (!route) return notFound();
    return serve(request, env, route);
  },
} satisfies ExportedHandler<Env>;
