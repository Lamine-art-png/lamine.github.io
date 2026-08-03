const NEWSROOM_PATH = "/news";
const NEWSROOM_SCRIPT_PATH = "/news/agroai-news-card-restore.js";
const NEWSROOM_ORIGIN = "https://agroai-343.pages.dev";

const PLATFORM_API_ARTICLE_PATH = "/news/agro-ai-platform-api-launch";
const FIELD_INTELLIGENCE_ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
const JOHN_DEERE_ARTICLE_PATH = "/news/agro-ai-connected-john-deere-operations-center";
const LEGACY_JOHN_DEERE_ARTICLE_PATH = "/news/john-deere-api-access";
const JOHN_DEERE_PUBLISH_AT = "2026-07-28T08:00:00-07:00";
const JOHN_DEERE_PUBLISH_AT_MS = Date.parse(JOHN_DEERE_PUBLISH_AT);

const PLATFORM_API_COVER_PATH = `${PLATFORM_API_ARTICLE_PATH}/cover.svg`;
const PLATFORM_API_LOGO_PATH = `${PLATFORM_API_ARTICLE_PATH}/agro-ai-logo.png`;
const FIELD_INTELLIGENCE_COVER_PATH = `${FIELD_INTELLIGENCE_ARTICLE_PATH}/cover.webp`;
const FIELD_INTELLIGENCE_LOGO_PATH = `${FIELD_INTELLIGENCE_ARTICLE_PATH}/agro-ai-logo.png`;
const JOHN_DEERE_COVER_PATH = `${JOHN_DEERE_ARTICLE_PATH}/cover.webp`;
const JOHN_DEERE_LOGO_PATH = `${JOHN_DEERE_ARTICLE_PATH}/agro-ai-logo.png`;

const PLATFORM_API_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-platform-api-launch/index.html";
const PLATFORM_API_COVER_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-platform-api-launch/cover.svg";
const FIELD_INTELLIGENCE_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/introducing-agro-ai-field-intelligence/index.html";
const JOHN_DEERE_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-connected-john-deere-operations-center/index.html";
const JOHN_DEERE_COVER_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-connected-john-deere-operations-center/cover.webp";
const OFFICIAL_LOGO_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/customer-portal/assets/agro-ai-logo.png";
const CURRENT_VIDEO_ID = "GiM6WZY0HG0";
const OBSOLETE_VIDEO_ID = "IMLVblFeW3s";
const YOUTUBE_COVER = `https://img.youtube.com/vi/${CURRENT_VIDEO_ID}/maxresdefault.jpg`;

const NEWSROOM_CARD_SCRIPT = `(()=>{
  const managed=[
    {
      path:"/news/agro-ai-platform-api-launch",
      image:"/news/agro-ai-platform-api-launch/cover.svg",
      category:"Product News",
      title:"AGRO-AI launches the Platform API",
      description:"Agricultural enterprises, agtech teams and integrators can build with fields, observations, recommendations, reports, connectors and webhooks.",
      date:"San Francisco, California — August 2, 2026"
    },
    {
      path:"/news/agro-ai-connected-john-deere-operations-center",
      image:"/news/agro-ai-connected-john-deere-operations-center/cover.webp",
      category:"Company News",
      title:"AGRO-AI connects with John Deere Operations Center™",
      description:"Customer-authorized operational data can support AGRO-AI intelligence, reporting, recommendations, and verification workflows.",
      date:"San Francisco, California — July 28, 2026"
    },
    {
      path:"/news/introducing-agro-ai-field-intelligence",
      image:"/news/introducing-agro-ai-field-intelligence/cover.webp",
      category:"Product News",
      title:"Introducing AGRO-AI Field Intelligence",
      description:"A voice-first field intelligence experience that turns observations into structured operational context, evidence, and action.",
      date:"San Francisco, California — July 21, 2026"
    }
  ];
  const legacyPath="/news/john-deere-api-access";
  const legacyTitle="agro-ai moves forward through john deere api access process";
  const preserved=[
    "/news/agro-ai-enterprise-portal-global-launch",
    "/news/agro-ai-submits-contribution-european-commission-water-sector-digitalisation",
    "/news/agro-ai-wiseconn-api-integration",
    "/news/agro-ai-talgil-dream-2-integration"
  ];
  const normalize=(value)=>{try{return new URL(value,location.origin).pathname.replace(/\\/$/,"")}catch{return ""}};
  const directCards=(grid)=>[...grid.children].filter((node)=>node instanceof HTMLAnchorElement&&normalize(node.getAttribute("href")||node.href).startsWith("/news/"));
  const findGrid=()=>[...document.querySelectorAll("div.grid")].find((grid)=>{
    const cards=directCards(grid);
    if(cards.length<4||!grid.classList.contains("gap-8")||!grid.classList.contains("md:grid-cols-2"))return false;
    const paths=new Set(cards.map((card)=>normalize(card.getAttribute("href")||card.href)));
    return preserved.every((path)=>paths.has(path));
  });
  const escapeHtml=(value)=>String(value).replace(/[&<>\"]/g,(character)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[character]));
  const cardHtml=(item)=>'<a href="'+escapeHtml(item.path)+'" data-agroai-news-card="'+escapeHtml(item.path)+'" class="group overflow-hidden rounded-[30px] border border-black/8 bg-white shadow-[0_12px_44px_rgba(15,23,42,0.05)] transition duration-300 hover:-translate-y-1 hover:shadow-[0_18px_48px_rgba(15,23,42,0.08)]"><div class="overflow-hidden"><img src="'+escapeHtml(item.image)+'" alt="'+escapeHtml(item.title)+'" class="aspect-[16/9] w-full object-cover transition duration-500 group-hover:scale-[1.02]"></div><div class="p-7"><p class="text-[11px] font-semibold uppercase tracking-[0.28em] text-[#7ea80f]">'+escapeHtml(item.category)+'</p><h3 class="mt-4 text-[30px] font-semibold leading-tight tracking-[-0.03em] text-neutral-950">'+escapeHtml(item.title)+'</h3><p class="mt-4 text-base leading-7 text-neutral-700">'+escapeHtml(item.description)+'</p><div class="mt-7 flex items-center justify-between text-sm text-neutral-600"><span>'+escapeHtml(item.date)+'</span><span class="inline-flex items-center gap-2 font-semibold text-neutral-950">Read article<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-arrow-right h-4 w-4 transition group-hover:translate-x-1"><path d="M5 12h14"></path><path d="m12 5 7 7-7 7"></path></svg></span></div></div></a>';
  const install=()=>{
    const grid=findGrid();
    if(!grid)return false;
    for(const card of directCards(grid)){
      const path=normalize(card.getAttribute("href")||card.href);
      const title=((card.querySelector("h3")&&card.querySelector("h3").textContent)||"").replace(/\\s+/g," ").trim().toLowerCase();
      if(path===legacyPath||title===legacyTitle||managed.some((item)=>item.path===path))card.remove();
    }
    for(const item of [...managed].reverse())grid.insertAdjacentHTML("afterbegin",cardHtml(item));
    const cards=directCards(grid);
    const paths=cards.map((card)=>normalize(card.getAttribute("href")||card.href));
    const counts=new Map(paths.map((path)=>[path,paths.filter((candidate)=>candidate===path).length]));
    const valid=cards.length===7&&new Set(paths).size===7&&preserved.every((path)=>counts.get(path)===1)&&managed.every((item)=>counts.get(item.path)===1)&&!paths.includes(legacyPath)&&!grid.textContent.toLowerCase().includes(legacyTitle)&&cards.every((card)=>(card.textContent.match(/Read article/g)||[]).length===1);
    if(valid){
      grid.setAttribute("data-agroai-newsroom-grid","complete");
      document.documentElement.setAttribute("data-agroai-news-cards-restored","true");
    }
    return valid;
  };
  let attempts=0;
  const run=()=>{
    attempts+=1;
    if(install()||attempts>=40)return;
    setTimeout(run,200);
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",run,{once:true});else run();
  window.addEventListener("load",()=>{install();setTimeout(install,600);setTimeout(install,1800);},{once:true});
})();`;

function johnDeerePublished(now = Date.now()): boolean {
  return now >= JOHN_DEERE_PUBLISH_AT_MS;
}

function articleHeaders(): Headers {
  const headers = new Headers();
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "public, max-age=60, s-maxage=60, stale-while-revalidate=300");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  headers.set("x-robots-tag", "index, follow, max-image-preview:large");
  headers.set(
    "content-security-policy",
    "default-src 'none'; style-src 'unsafe-inline' https://fonts.cdnfonts.com; script-src 'unsafe-inline'; img-src data: https:; frame-src https://www.youtube-nocookie.com; font-src data: https://fonts.cdnfonts.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  );
  return headers;
}

function scheduledArticleResponse(): Response {
  const headers = new Headers();
  headers.set("cache-control", "no-store");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-robots-tag", "noindex, nofollow");
  headers.set("x-agroai-scheduled-publication", JOHN_DEERE_PUBLISH_AT);
  const retryAfter = Math.max(1, Math.ceil((JOHN_DEERE_PUBLISH_AT_MS - Date.now()) / 1000));
  headers.set("retry-after", String(retryAfter));
  return new Response(null, { status: 404, headers });
}

async function fetchArticleSource(source: string, userAgent: string): Promise<Response> {
  return fetch(source, {
    cf: { cacheEverything: true, cacheTtl: 60 },
    headers: { "user-agent": userAgent, "cache-control": "no-cache" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
}

async function platformApiArticleResponse(request: Request): Promise<Response> {
  const upstream = await fetchArticleSource(PLATFORM_API_ARTICLE_SOURCE, "AGRO-AI-Platform-API-Launch/1.0");
  if (!upstream.ok) {
    return new Response("The AGRO-AI Platform API launch article is temporarily unavailable.", { status: 503, headers: articleHeaders() });
  }
  return new Response(request.method === "HEAD" ? null : await upstream.text(), { status: 200, headers: articleHeaders() });
}

async function fieldIntelligenceArticleResponse(request: Request): Promise<Response> {
  const upstream = await fetchArticleSource(FIELD_INTELLIGENCE_ARTICLE_SOURCE, "AGRO-AI-Field-Intelligence-Launch/1.2");
  if (!upstream.ok) {
    return new Response("The AGRO-AI Field Intelligence launch article is temporarily unavailable.", { status: 503, headers: articleHeaders() });
  }
  const html = (await upstream.text()).replaceAll(OBSOLETE_VIDEO_ID, CURRENT_VIDEO_ID);
  return new Response(request.method === "HEAD" ? null : html, { status: 200, headers: articleHeaders() });
}

async function johnDeereArticleResponse(request: Request): Promise<Response> {
  if (!johnDeerePublished()) return scheduledArticleResponse();
  const upstream = await fetchArticleSource(JOHN_DEERE_ARTICLE_SOURCE, "AGRO-AI-John-Deere-Operations-Center-News/1.2");
  if (!upstream.ok) {
    return new Response("The AGRO-AI Operations Center announcement is temporarily unavailable.", { status: 503, headers: articleHeaders() });
  }
  return new Response(request.method === "HEAD" ? null : await upstream.text(), { status: 200, headers: articleHeaders() });
}

async function repositoryAssetResponse(request: Request, source: string, fallbackType: string, marker: string): Promise<Response> {
  const upstream = await fetch(source, {
    cf: { cacheEverything: true, cacheTtl: 300 },
    headers: { "user-agent": `AGRO-AI-${marker}/1.0`, "cache-control": "no-cache" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) return new Response("Asset unavailable", { status: 503 });
  const headers = new Headers();
  headers.set("content-type", upstream.headers.get("content-type") || fallbackType);
  headers.set("cache-control", "public, max-age=300, s-maxage=300, must-revalidate");
  headers.set("x-content-type-options", "nosniff");
  headers.set("cross-origin-resource-policy", "cross-origin");
  headers.set("x-agroai-asset-source", marker);
  return new Response(request.method === "HEAD" ? null : upstream.body, { status: 200, headers });
}

async function officialLogoResponse(request: Request): Promise<Response> {
  return repositoryAssetResponse(request, OFFICIAL_LOGO_SOURCE, "image/png", "official-repository-logo");
}

async function fieldIntelligenceCoverResponse(request: Request): Promise<Response> {
  const transformed = await fetch(YOUTUBE_COVER, {
    cf: { cacheEverything: true, cacheTtl: 86400, image: { width: 3840, height: 2160, fit: "cover", quality: 92, format: "webp" } },
    headers: { "user-agent": "AGRO-AI-Field-Intelligence-Cover/1.0" },
  } as RequestInit & { cf: Record<string, unknown> });
  if (!transformed.ok) return new Response("Cover unavailable", { status: 503 });
  const headers = new Headers();
  headers.set("content-type", transformed.headers.get("content-type") || "image/webp");
  headers.set("cache-control", "public, max-age=86400, s-maxage=86400, immutable");
  headers.set("x-content-type-options", "nosniff");
  headers.set("cross-origin-resource-policy", "cross-origin");
  headers.set("x-agroai-cover-target", "3840x2160");
  return new Response(request.method === "HEAD" ? null : transformed.body, { status: 200, headers });
}

function newsroomScriptResponse(request: Request): Response {
  const headers = new Headers({
    "content-type": "application/javascript; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  return new Response(request.method === "HEAD" ? null : NEWSROOM_CARD_SCRIPT, { status: 200, headers });
}

async function newsroomResponse(request: Request): Promise<Response> {
  const requested = new URL(request.url);
  const originUrl = new URL(requested.pathname.endsWith("/") ? "/news/" : "/news", NEWSROOM_ORIGIN);
  originUrl.search = requested.search;
  const upstream = await fetch(originUrl.toString(), {
    cf: { cacheEverything: false },
    headers: { accept: "text/html", "cache-control": "no-cache", "user-agent": "AGRO-AI-Native-Newsroom/1.1" },
  } as RequestInit & { cf: { cacheEverything: boolean } });
  if (!upstream.ok) return new Response("Newsroom temporarily unavailable", { status: 503, headers: { "cache-control": "no-store" } });
  const html = await upstream.text();
  if (html.length < 1000 || !/<html|<!doctype html/i.test(html)) {
    return new Response("Newsroom origin identity mismatch", { status: 503, headers: { "cache-control": "no-store" } });
  }
  const tag = `<script src="${NEWSROOM_SCRIPT_PATH}" defer data-agroai-news-card-restoration="exact-native-grid-v2"></script>`;
  const body = html.includes("</body>") ? html.replace("</body>", `${tag}</body>`) : `${html}${tag}`;
  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "private, no-cache, must-revalidate");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-agroai-newsroom-source", "native-pages-origin");
  headers.set("x-agroai-newsroom-change", "preserve-four-native-cards-add-three-remove-one-obsolete");
  return new Response(request.method === "HEAD" ? null : body, { status: 200, headers });
}

function legacyJohnDeereArticleResponse(): Response {
  if (!johnDeerePublished()) return scheduledArticleResponse();
  const headers = new Headers({ location: JOHN_DEERE_ARTICLE_PATH, "cache-control": "public, max-age=300, s-maxage=300", "x-content-type-options": "nosniff" });
  return new Response(null, { status: 301, headers });
}

export default {
  async fetch(request: Request): Promise<Response> {
    if (!["GET", "HEAD"].includes(request.method)) return new Response("Method not allowed", { status: 405, headers: { allow: "GET, HEAD" } });
    const url = new URL(request.url);
    const normalized = url.pathname.length > 1 ? url.pathname.replace(/\/$/, "") : url.pathname;

    if (normalized === NEWSROOM_PATH) return newsroomResponse(request);
    if (normalized === NEWSROOM_SCRIPT_PATH) return newsroomScriptResponse(request);
    if (normalized === PLATFORM_API_ARTICLE_PATH) return platformApiArticleResponse(request);
    if (normalized === PLATFORM_API_COVER_PATH) return repositoryAssetResponse(request, PLATFORM_API_COVER_SOURCE, "image/svg+xml", "reviewed-platform-api-cover");
    if (normalized === PLATFORM_API_LOGO_PATH) return officialLogoResponse(request);
    if (normalized === LEGACY_JOHN_DEERE_ARTICLE_PATH || normalized.startsWith(`${LEGACY_JOHN_DEERE_ARTICLE_PATH}/`)) return legacyJohnDeereArticleResponse();
    if (normalized === JOHN_DEERE_ARTICLE_PATH) return johnDeereArticleResponse(request);
    if (normalized === JOHN_DEERE_COVER_PATH) {
      if (!johnDeerePublished()) return scheduledArticleResponse();
      return repositoryAssetResponse(request, JOHN_DEERE_COVER_SOURCE, "image/webp", "reviewed-john-deere-cover");
    }
    if (normalized === JOHN_DEERE_LOGO_PATH) {
      if (!johnDeerePublished()) return scheduledArticleResponse();
      return officialLogoResponse(request);
    }
    if (normalized === FIELD_INTELLIGENCE_ARTICLE_PATH) return fieldIntelligenceArticleResponse(request);
    if (normalized === FIELD_INTELLIGENCE_LOGO_PATH) return officialLogoResponse(request);
    if (normalized === FIELD_INTELLIGENCE_COVER_PATH) return fieldIntelligenceCoverResponse(request);
    return new Response("Not found", { status: 404 });
  },
};
