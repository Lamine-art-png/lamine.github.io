const NEWSROOM_PATH = "/news";
const NEWSROOM_SCRIPT_PATH = "/news/agroai-news-card-restore.js";
const NEWSROOM_ORIGIN = "https://agroai-343.pages.dev";

const FIELD_INTELLIGENCE_ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
const JOHN_DEERE_ARTICLE_PATH = "/news/agro-ai-connected-john-deere-operations-center";
const LEGACY_JOHN_DEERE_ARTICLE_PATH = "/news/john-deere-api-access";
const JOHN_DEERE_PUBLISH_AT = "2026-07-28T08:00:00-07:00";
const JOHN_DEERE_PUBLISH_AT_MS = Date.parse(JOHN_DEERE_PUBLISH_AT);

const FIELD_INTELLIGENCE_COVER_PATH = `${FIELD_INTELLIGENCE_ARTICLE_PATH}/cover.webp`;
const FIELD_INTELLIGENCE_LOGO_PATH = `${FIELD_INTELLIGENCE_ARTICLE_PATH}/agro-ai-logo.png`;
const JOHN_DEERE_COVER_PATH = `${JOHN_DEERE_ARTICLE_PATH}/cover.webp`;
const JOHN_DEERE_LOGO_PATH = `${JOHN_DEERE_ARTICLE_PATH}/agro-ai-logo.png`;

const FIELD_INTELLIGENCE_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/introducing-agro-ai-field-intelligence/index.html";
const JOHN_DEERE_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-connected-john-deere-operations-center/index.html";
const JOHN_DEERE_COVER_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-connected-john-deere-operations-center/cover.webp";
const OFFICIAL_LOGO_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/customer-portal/assets/agro-ai-logo.png";
const CURRENT_VIDEO_ID = "GiM6WZY0HG0";
const OBSOLETE_VIDEO_ID = "IMLVblFeW3s";
const YOUTUBE_COVER = `https://img.youtube.com/vi/${CURRENT_VIDEO_ID}/maxresdefault.jpg`;

const NEWSROOM_CARD_SCRIPT = `(()=>{
  const cards=[
    {
      path:"/news/agro-ai-connected-john-deere-operations-center",
      title:"AGRO-AI connects with John Deere Operations Center™",
      description:"Customer-authorized operational data can support AGRO-AI intelligence, reporting, recommendations, and verification workflows.",
      date:"July 28, 2026",
      datetime:"2026-07-28",
      category:"Integration",
      image:"/news/agro-ai-connected-john-deere-operations-center/cover.webp"
    },
    {
      path:"/news/introducing-agro-ai-field-intelligence",
      title:"Introducing AGRO-AI Field Intelligence",
      description:"A voice-first field intelligence experience that turns observations into structured operational context, evidence, and action.",
      date:"July 21, 2026",
      datetime:"2026-07-21",
      category:"Product",
      image:"/news/introducing-agro-ai-field-intelligence/cover.webp"
    }
  ];
  const legacyPaths=["/news/john-deere-api-access"];
  const legacyTitles=[
    "agro-ai moves forward through john deere api access process",
    "john deere api access process"
  ];
  const normalize=(value)=>{try{return new URL(value,location.origin).pathname.replace(/\\/$/,"")}catch{return ""}};
  const isNewsPath=(value)=>normalize(value).startsWith("/news/");
  const newsLinks=()=>[...document.querySelectorAll("a[href]")].filter((anchor)=>isNewsPath(anchor.getAttribute("href")||anchor.href));
  const text=(node)=>((node&&node.textContent)||"").replace(/\\s+/g," ").trim().toLowerCase();
  const setText=(node,value)=>{if(node&&node.textContent!==value)node.textContent=value};
  const setAttr=(node,name,value)=>{if(node&&node.getAttribute(name)!==value)node.setAttribute(name,value)};
  const cardFor=(node)=>{
    let element=node instanceof Element?node:null;
    while(element&&element!==document.body){
      if(element.matches("article,li,[class*='card'],[class*='Card'],[class*='item'],[class*='Item'],[class*='post'],[class*='Post']"))return element;
      const links=[...element.querySelectorAll("a[href]")].filter((anchor)=>isNewsPath(anchor.getAttribute("href")||anchor.href));
      if(links.length===1&&(element.querySelector("img")||element.querySelector("h1,h2,h3,h4,h5")))return element;
      element=element.parentElement;
    }
    return node instanceof Element?node.parentElement:null;
  };
  const locateTemplate=()=>{
    let fallback=null;
    for(const link of newsLinks()){
      const path=normalize(link.getAttribute("href")||link.href);
      const card=cardFor(link);
      if(!card||!card.parentElement)continue;
      const candidate={card,container:card.parentElement};
      if(!fallback)fallback=candidate;
      if(!legacyPaths.includes(path)&&!cards.some((item)=>item.path===path))return candidate;
    }
    return fallback;
  };
  const removeLegacyCards=()=>{
    const remove=new Set();
    for(const link of newsLinks()){
      if(legacyPaths.includes(normalize(link.getAttribute("href")||link.href))){
        const card=cardFor(link);
        if(card)remove.add(card);
      }
    }
    for(const node of document.querySelectorAll("h1,h2,h3,h4,h5,a[href]")){
      const value=text(node);
      if(legacyTitles.some((title)=>value.includes(title))){
        const card=cardFor(node);
        if(card)remove.add(card);
      }
    }
    for(const card of remove){
      if(card&&card.isConnected)card.remove();
    }
  };
  const setCard=(card,item)=>{
    setAttr(card,"data-agroai-managed-news-card",item.path);
    if(card.hidden)card.hidden=false;
    if(card.getAttribute("aria-hidden")==="true")card.removeAttribute("aria-hidden");
    const anchors=[...(card.matches("a[href]")?[card]:[]),...card.querySelectorAll("a[href]")];
    for(const anchor of anchors){
      const current=normalize(anchor.getAttribute("href")||anchor.href);
      if(!current||current.startsWith("/news/"))setAttr(anchor,"href",item.path);
    }
    const heading=card.querySelector("h1,h2,h3,h4,h5,[class*='title'],[class*='Title']");
    setText(heading,item.title);
    const paragraphs=[...card.querySelectorAll("p")];
    const description=paragraphs.find((paragraph)=>text(paragraph).length>24)||paragraphs[0];
    setText(description,item.description);
    const time=card.querySelector("time");
    if(time){
      setText(time,item.date);
      setAttr(time,"datetime",item.datetime);
    }else{
      const dateNode=[...card.querySelectorAll("span,div")].find((element)=>element.children.length===0&&/20\\d{2}/.test(element.textContent||""));
      setText(dateNode,item.date);
    }
    const image=card.querySelector("img");
    if(image){
      setAttr(image,"src",item.image);
      setAttr(image,"alt",item.title);
      if(image.hasAttribute("srcset"))image.removeAttribute("srcset");
      if(image.hasAttribute("sizes"))image.removeAttribute("sizes");
    }
    const badge=card.querySelector("[class*='category'],[class*='Category'],[class*='badge'],[class*='Badge'],[class*='tag'],[class*='Tag']");
    if(badge&&badge.children.length===0)setText(badge,item.category);
  };
  const install=()=>{
    const template=locateTemplate();
    if(!template)return false;
    removeLegacyCards();
    for(const item of [...cards].reverse()){
      const matches=new Set();
      for(const link of newsLinks()){
        if(normalize(link.getAttribute("href")||link.href)===item.path){
          const card=cardFor(link);
          if(card)matches.add(card);
        }
      }
      const existing=[...matches];
      if(existing.length){
        setCard(existing[0],item);
        for(const duplicate of existing.slice(1))duplicate.remove();
        const first=template.container.firstElementChild;
        if(existing[0].parentElement===template.container&&existing[0]!==first)template.container.insertBefore(existing[0],first);
        continue;
      }
      const clone=template.card.cloneNode(true);
      setCard(clone,item);
      template.container.insertBefore(clone,template.container.firstElementChild);
    }
    removeLegacyCards();
    const ready=cards.every((item)=>newsLinks().some((link)=>normalize(link.getAttribute("href")||link.href)===item.path))&&!document.body.textContent.toLowerCase().includes("agro-ai moves forward through john deere api access process");
    if(ready)document.documentElement.setAttribute("data-agroai-news-cards-restored","true");
    return ready;
  };
  let running=false;
  let timer=0;
  const run=()=>{
    if(running)return;
    running=true;
    try{install()}finally{running=false}
  };
  const schedule=()=>{
    clearTimeout(timer);
    timer=setTimeout(run,80);
  };
  const start=()=>{
    run();
    [250,750,1500,3000,6000].forEach((delay)=>setTimeout(run,delay));
    if(document.body){
      const observer=new MutationObserver(schedule);
      observer.observe(document.body,{childList:true,subtree:true});
      setTimeout(()=>observer.disconnect(),12000);
    }
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
  window.addEventListener("load",run,{once:true});
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

async function fieldIntelligenceArticleResponse(request: Request): Promise<Response> {
  const upstream = await fetchArticleSource(FIELD_INTELLIGENCE_ARTICLE_SOURCE, "AGRO-AI-Field-Intelligence-Launch/1.1");
  if (!upstream.ok) {
    return new Response("The AGRO-AI Field Intelligence launch article is temporarily unavailable.", { status: 503, headers: articleHeaders() });
  }
  const html = (await upstream.text()).replaceAll(OBSOLETE_VIDEO_ID, CURRENT_VIDEO_ID);
  return new Response(request.method === "HEAD" ? null : html, { status: 200, headers: articleHeaders() });
}

async function johnDeereArticleResponse(request: Request): Promise<Response> {
  if (!johnDeerePublished()) return scheduledArticleResponse();
  const upstream = await fetchArticleSource(JOHN_DEERE_ARTICLE_SOURCE, "AGRO-AI-John-Deere-Operations-Center-News/1.1");
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
    headers: { accept: "text/html", "cache-control": "no-cache", "user-agent": "AGRO-AI-Native-Newsroom/1.0" },
  } as RequestInit & { cf: { cacheEverything: boolean } });
  if (!upstream.ok) return new Response("Newsroom temporarily unavailable", { status: 503, headers: { "cache-control": "no-store" } });
  const html = await upstream.text();
  if (html.length < 1000 || !/<html|<!doctype html/i.test(html)) {
    return new Response("Newsroom origin identity mismatch", { status: 503, headers: { "cache-control": "no-store" } });
  }
  const tag = `<script src="${NEWSROOM_SCRIPT_PATH}" defer data-agroai-news-card-restoration="true"></script>`;
  const body = html.includes("</body>") ? html.replace("</body>", `${tag}</body>`) : `${html}${tag}`;
  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "private, no-cache, must-revalidate");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-agroai-newsroom-source", "native-pages-origin");
  headers.set("x-agroai-newsroom-change", "add-two-native-cards-remove-one-obsolete-card");
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
