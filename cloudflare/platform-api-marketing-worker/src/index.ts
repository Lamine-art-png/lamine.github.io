interface Env {
  ASSETS: Fetcher;
  MARKETING_ORIGIN?: string;
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

type Surface = "marketing" | "docs" | "shared";
type Route = { assetPath: string; surface: Surface; html: boolean; identity?: string };

const DEFAULT_MARKETING_ORIGIN = "https://agroai-343.pages.dev";
const PLATFORM_CONSOLE = "https://platform.agroai-pilot.com";
const ENTERPRISE_PORTAL = "https://app.agroai-pilot.com";
const PRIVATE_ROBOTS_META = /<meta\b(?=[^>]*\bname=["']robots["'])(?=[^>]*\bcontent=["'][^"']*\bnoindex\b[^"']*["'])[^>]*>\s*/gi;

const STATIC_ROUTES: Record<string, Route> = {
  "/platform-api": { assetPath: "/index.html", surface: "marketing", html: true, identity: 'data-agroai-platform-page="landing"' },
  "/platform-api/": { assetPath: "/index.html", surface: "marketing", html: true, identity: 'data-agroai-platform-page="landing"' },
  "/platform-api/index.html": { assetPath: "/index.html", surface: "marketing", html: true, identity: 'data-agroai-platform-page="landing"' },
  "/platform-api/reference": { assetPath: "/reference.html", surface: "docs", html: true },
  "/platform-api/reference.html": { assetPath: "/reference.html", surface: "docs", html: true },
  "/platform-api/changelog": { assetPath: "/changelog.html", surface: "docs", html: true },
  "/platform-api/changelog.html": { assetPath: "/changelog.html", surface: "docs", html: true },
  "/platform-api/docs": { assetPath: "/docs/index.html", surface: "docs", html: true, identity: 'data-agroai-platform-page="docs"' },
  "/platform-api/docs/": { assetPath: "/docs/index.html", surface: "docs", html: true, identity: 'data-agroai-platform-page="docs"' },
  "/platform-api/docs/index.html": { assetPath: "/docs/index.html", surface: "docs", html: true, identity: 'data-agroai-platform-page="docs"' },
  "/platform-api/docs/authentication": { assetPath: "/docs/authentication.html", surface: "docs", html: true },
  "/platform-api/docs/authentication.html": { assetPath: "/docs/authentication.html", surface: "docs", html: true },
  "/platform-api/docs/pagination": { assetPath: "/docs/pagination.html", surface: "docs", html: true },
  "/platform-api/docs/pagination.html": { assetPath: "/docs/pagination.html", surface: "docs", html: true },
  "/platform-api/docs/errors": { assetPath: "/docs/errors.html", surface: "docs", html: true },
  "/platform-api/docs/errors.html": { assetPath: "/docs/errors.html", surface: "docs", html: true },
  "/platform-api/docs/rate-limits": { assetPath: "/docs/rate-limits.html", surface: "docs", html: true },
  "/platform-api/docs/rate-limits.html": { assetPath: "/docs/rate-limits.html", surface: "docs", html: true },
  "/platform-api/docs/support": { assetPath: "/docs/support.html", surface: "docs", html: true },
  "/platform-api/docs/support.html": { assetPath: "/docs/support.html", surface: "docs", html: true },
};

function enabled(value: string | undefined): boolean {
  return String(value || "").trim().toLowerCase() === "true";
}

function routeFor(pathname: string): Route | null {
  const staticRoute = STATIC_ROUTES[pathname];
  if (staticRoute) return staticRoute;
  if (/^\/platform-api\/assets\/[A-Za-z0-9._/-]+$/.test(pathname) && !pathname.includes("..")) {
    return { assetPath: pathname.slice("/platform-api".length), surface: "shared", html: false };
  }
  if (/^\/platform-api\/contract\/(platform_api_openapi\.json|platform_api_openapi\.sha256)$/.test(pathname)) {
    return { assetPath: pathname.slice("/platform-api".length), surface: "docs", html: false };
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

function unavailable(reason = "upstream-unavailable"): Response {
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

function normalizePlatformHtml(html: string): string {
  return html
    .replaceAll("https://app.agroai-pilot.com/developers/api/apply?type=developer_beta", PLATFORM_CONSOLE)
    .replaceAll("https://app.agroai-pilot.com/developers/api/apply?type=strategic_partner", PLATFORM_CONSOLE)
    .replaceAll('href="https://app.agroai-pilot.com"', `href="${PLATFORM_CONSOLE}"`);
}

async function platformAsset(request: Request, env: Env, route: Route, indexing: boolean): Promise<Response> {
  const assetUrl = new URL(route.assetPath, request.url);
  const upstream = await env.ASSETS.fetch(new Request(assetUrl, {
    method: request.method,
    headers: { accept: request.headers.get("accept") || "*/*" },
  }));

  if (upstream.status === 404) return notFound();
  if (!upstream.ok) return unavailable("asset-unavailable");

  const headers = responseHeaders(upstream, route, indexing);
  if (!route.html || request.method === "HEAD") {
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  }

  let html = normalizePlatformHtml(await upstream.text());
  if (route.identity && !html.includes(route.identity)) return unavailable("identity-mismatch");
  if (/This page doesn[’']t exist|>404</i.test(html)) return unavailable("identity-mismatch");
  if (indexing) html = html.replace(PRIVATE_ROBOTS_META, "");
  return new Response(html, { status: 200, headers });
}

const HOMEPAGE_STYLE = `<style id="agroai-product-entry-style">
.agroai-login-switcher{position:relative;display:inline-flex;z-index:90}.agroai-login-trigger{display:inline-flex;align-items:center;justify-content:center;cursor:pointer;gap:.45rem}.agroai-login-chevron{width:14px;height:14px;transition:transform .18s ease}.agroai-login-switcher[data-open="true"] .agroai-login-chevron{transform:rotate(180deg)}.agroai-login-menu{position:absolute;right:0;top:calc(100% + 10px);width:min(340px,calc(100vw - 28px));padding:10px;border:1px solid #d7ded7;border-radius:16px;background:#fff;box-shadow:0 24px 70px rgba(8,34,24,.18);opacity:0;visibility:hidden;transform:translateY(-6px);transition:opacity .16s ease,transform .16s ease,visibility .16s;z-index:100}.agroai-login-switcher[data-open="true"] .agroai-login-menu{opacity:1;visibility:visible;transform:translateY(0)}.agroai-login-product{display:flex;align-items:flex-start;gap:12px;padding:14px;border-radius:12px;color:#10231b;text-decoration:none;transition:background .16s ease}.agroai-login-product:hover,.agroai-login-product:focus-visible{background:#f3f6f1;outline:none}.agroai-login-icon{display:flex;width:40px;height:40px;flex:0 0 40px;align-items:center;justify-content:center;border-radius:11px;background:#0d2b1e;color:#dceb8f;font-size:12px;font-weight:800}.agroai-login-copy{display:block;min-width:0}.agroai-login-name{display:block;font-size:14px;font-weight:700;line-height:1.3}.agroai-login-note{display:block;margin-top:4px;font-size:12px;line-height:1.45;color:#66736b}.agroai-api-hero-cta{white-space:nowrap}@media(max-width:760px){.agroai-login-menu{position:fixed;top:76px;right:14px;left:14px;width:auto}}
</style>`;

const HOMEPAGE_SCRIPT = `<script id="agroai-product-entry-script">
(()=>{const PORTAL="${ENTERPRISE_PORTAL}";const API="${PLATFORM_CONSOLE}";const clean=v=>(v||"").replace(/\\s+/g," ").trim().toLowerCase();const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0};function findLogin(){const nodes=[...document.querySelectorAll("a,button")];return nodes.find(e=>{if(!visible(e)||e.closest("[data-agroai-login-switcher]"))return false;const label=clean(e.textContent);const href=e instanceof HTMLAnchorElement?e.href:"";return label==="open portal"||label==="log in"||label==="login"||href===PORTAL||href===PORTAL+"/"})}function installLogin(){if(document.querySelector("[data-agroai-login-switcher]"))return;const target=findLogin();if(!target)return;const wrap=document.createElement("div");wrap.className="agroai-login-switcher";wrap.dataset.agroaiLoginSwitcher="true";wrap.dataset.open="false";const trigger=document.createElement("button");trigger.type="button";trigger.className=(target.className||"")+" agroai-login-trigger";trigger.setAttribute("aria-haspopup","menu");trigger.setAttribute("aria-expanded","false");trigger.innerHTML='Log in <svg class="agroai-login-chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 7.5 5 5 5-5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';const menu=document.createElement("div");menu.className="agroai-login-menu";menu.setAttribute("role","menu");menu.innerHTML='<a class="agroai-login-product" role="menuitem" href="'+PORTAL+'"><span class="agroai-login-icon">EP</span><span class="agroai-login-copy"><span class="agroai-login-name">Enterprise Portal</span><span class="agroai-login-note">Operations, intelligence, evidence, reports, and connected agricultural workflows.</span></span></a><a class="agroai-login-product" role="menuitem" href="'+API+'"><span class="agroai-login-icon">API</span><span class="agroai-login-copy"><span class="agroai-login-name">API Platform</span><span class="agroai-login-note">Projects, service accounts, API keys, Playground, usage, logs, and webhooks.</span></span></a>';trigger.addEventListener("click",e=>{e.stopPropagation();const next=wrap.dataset.open!=="true";wrap.dataset.open=String(next);trigger.setAttribute("aria-expanded",String(next))});document.addEventListener("click",e=>{if(!wrap.contains(e.target)){wrap.dataset.open="false";trigger.setAttribute("aria-expanded","false")}});document.addEventListener("keydown",e=>{if(e.key==="Escape"){wrap.dataset.open="false";trigger.setAttribute("aria-expanded","false");trigger.focus()}});wrap.append(trigger,menu);target.replaceWith(wrap)}function installHero(){if(document.querySelector("[data-agroai-api-hero-cta]"))return;const links=[...document.querySelectorAll("a")];const portal=links.find(e=>clean(e.textContent)==="open the enterprise portal"||clean(e.textContent)==="open enterprise portal");const demo=links.find(e=>clean(e.textContent)==="book a demo");if(!portal||!demo||!demo.parentElement)return;const api=demo.cloneNode(true);api.href=API;api.textContent="Open API Platform";api.classList.add("agroai-api-hero-cta");api.dataset.agroaiApiHeroCta="true";demo.parentElement.insertBefore(api,demo)}function renameApiNav(){document.querySelectorAll('a[href="/platform-api"],a[href="/platform-api/"]').forEach(a=>{if(clean(a.textContent)==="api")a.textContent="API Platform"})}function install(){installLogin();installHero();renameApiNav()}install();let scheduled=false;new MutationObserver(()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;install()})}).observe(document.documentElement,{childList:true,subtree:true})})();
</script>`;

async function homepage(request: Request, env: Env): Promise<Response> {
  let origin: URL;
  try { origin = safeOrigin(env.MARKETING_ORIGIN); }
  catch { return unavailable("homepage-origin-invalid"); }

  const upstream = await fetch(new URL("/", origin).toString(), {
    method: request.method,
    redirect: "follow",
    headers: { accept: "text/html", "user-agent": "AGRO-AI-Product-Entry/3.0" },
    cf: { cacheEverything: false, cacheTtl: 0 },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) return unavailable("homepage-upstream-unavailable");

  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("cache-control", "public, max-age=0, must-revalidate");
  headers.set("x-agroai-product-entry", "portal-and-api-v3");
  if (request.method === "HEAD") return new Response(null, { status: 200, headers });

  let html = await upstream.text();
  if (!html.includes('<div id="root"></div>') || /This page doesn[’']t exist|>404</i.test(html)) return unavailable("homepage-identity-mismatch");
  html = html.replace("</head>", `${HOMEPAGE_STYLE}</head>`).replace("</body>", `${HOMEPAGE_SCRIPT}</body>`);
  return new Response(html, { status: 200, headers });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method not allowed", { status: 405, headers: { allow: "GET, HEAD", "cache-control": "no-store", "x-robots-tag": "noindex, nofollow" } });
    }

    const url = new URL(request.url);
    if (url.pathname === "/") return homepage(request, env);

    const route = routeFor(url.pathname);
    if (!route) return notFound();
    const marketing = enabled(env.PLATFORM_API_MARKETING_ENABLED);
    const docs = enabled(env.PLATFORM_API_PUBLIC_DOCS_ENABLED);
    if (!surfaceEnabled(route.surface, marketing, docs)) return notFound();
    return platformAsset(request, env, route, enabled(env.PLATFORM_API_INDEXING_ENABLED));
  },
} satisfies ExportedHandler<Env>;
