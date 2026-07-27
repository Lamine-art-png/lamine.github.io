const NEWSROOM_PATH = "/news";
const NEWSROOM_SCRIPT_PATH = "/news/field-intelligence-newsroom.js";
const NEWSROOM_STYLE_PATH = "/news/field-intelligence-newsroom.css";
const ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
const JOHN_DEERE_ARTICLE_PATH = "/news/agro-ai-connected-john-deere-operations-center";
const LEGACY_JOHN_DEERE_ARTICLE_PATH = "/news/john-deere-api-access";
const JOHN_DEERE_PUBLISH_AT = "2026-07-28T08:00:00-07:00";
const JOHN_DEERE_PUBLISH_AT_MS = Date.parse(JOHN_DEERE_PUBLISH_AT);
const COVER_PATH = `${ARTICLE_PATH}/cover.webp`;
const LOGO_PATH = `${ARTICLE_PATH}/agro-ai-logo.png`;
const JOHN_DEERE_LOGO_PATH = `${JOHN_DEERE_ARTICLE_PATH}/agro-ai-logo.png`;
const MARKETING_ORIGIN = "https://agroai-343.pages.dev";
const ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/introducing-agro-ai-field-intelligence/index.html";
const JOHN_DEERE_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-connected-john-deere-operations-center/index.html";
const LOGO_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/customer-portal/assets/agro-ai-logo.png";
const CURRENT_VIDEO_ID = "GiM6WZY0HG0";
const OBSOLETE_VIDEO_ID = "IMLVblFeW3s";
const YOUTUBE_COVER = `https://img.youtube.com/vi/${CURRENT_VIDEO_ID}/maxresdefault.jpg`;
const LEGACY_JOHN_DEERE_ARTICLE_HREF = /href\s*=\s*["'](?:https:\/\/(?:agroai-pilot\.com|agroai-343\.pages\.dev))?\/news\/john-deere-api-access\/?(?:[?#][^"']*)?["']/i;

const NEWSROOM_STYLE = `
.agroai-fi-news-card-shell{display:block;min-width:0;height:100%;font-family:"Glacial Indifference",system-ui,sans-serif}
.agroai-fi-news-card{display:flex;flex-direction:column;height:100%;overflow:hidden;border:1px solid rgba(25,68,43,.12);border-radius:22px;background:#fff;color:#10231b;text-decoration:none;box-shadow:0 18px 45px rgba(16,35,27,.08);transition:transform .2s ease,box-shadow .2s ease}
.agroai-fi-news-card:hover{transform:translateY(-3px);box-shadow:0 24px 58px rgba(16,35,27,.14)}
.agroai-fi-news-card-media{position:relative;overflow:hidden;aspect-ratio:16/9;background:#09271d}
.agroai-fi-news-card-media img{display:block;width:100%;height:100%;object-fit:cover;transition:transform .35s ease}
.agroai-fi-news-card:hover .agroai-fi-news-card-media img{transform:scale(1.025)}
.agroai-fi-news-card-badge{position:absolute;top:16px;left:16px;padding:7px 10px;border-radius:999px;background:#b7ee31;color:#10231b;font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.agroai-fi-news-card-body{display:flex;flex:1;flex-direction:column;padding:25px 25px 22px}
.agroai-fi-news-card-kicker{margin-bottom:13px;color:#5a7c2a;font-size:10px;font-weight:800;letter-spacing:.17em;text-transform:uppercase}
.agroai-fi-news-card-title{margin:0 0 13px;color:#10231b;font-size:clamp(24px,2vw,34px);font-weight:800;letter-spacing:-.035em;line-height:1.08}
.agroai-fi-news-card-copy{margin:0 0 22px;color:#53645b;font-size:15px;line-height:1.6}
.agroai-fi-news-card-footer{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-top:auto;color:#627168;font-size:11px;line-height:1.45}
.agroai-fi-news-card-read{flex:0 0 auto;color:#10231b;font-weight:800;white-space:nowrap}
.agroai-jd-news-card-media{position:relative;display:flex;flex-direction:column;justify-content:space-between;overflow:hidden;aspect-ratio:16/9;padding:28px;background:radial-gradient(circle at 80% 18%,rgba(183,238,49,.26),transparent 28%),linear-gradient(145deg,#071f17,#164b35);color:#fff}
.agroai-jd-news-card-media:before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.06) 1px,transparent 1px);background-size:38px 38px;mask-image:linear-gradient(to bottom,black,transparent)}
.agroai-jd-news-card-logo,.agroai-jd-news-card-flow{position:relative}.agroai-jd-news-card-logo{width:auto!important;height:48px!important;max-width:150px;object-fit:contain!important;object-position:left center}
.agroai-jd-news-card-flow{display:flex;align-items:center;gap:12px;font-size:15px;font-weight:800}.agroai-jd-news-card-node{padding:10px 12px;border:1px solid rgba(255,255,255,.2);border-radius:10px;background:rgba(255,255,255,.08)}.agroai-jd-news-card-arrow{color:#b7ee31}
@media(max-width:680px){.agroai-fi-news-card-body{padding:21px}.agroai-fi-news-card-title{font-size:25px}.agroai-fi-news-card-footer{align-items:flex-start;flex-direction:column;gap:10px}.agroai-jd-news-card-media{padding:22px}.agroai-jd-news-card-flow{font-size:13px}}
`;

const NEWSROOM_SCRIPT = `
(function () {
  var FIELD_ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
  var JOHN_DEERE_ARTICLE_PATH = "/news/agro-ai-connected-john-deere-operations-center";
  var LEGACY_JOHN_DEERE_ARTICLE_PATH = "/news/john-deere-api-access";
  var JOHN_DEERE_PUBLISH_AT_MS = Date.parse("2026-07-28T08:00:00-07:00");
  var FIELD_CARD_ID = "agroai-field-intelligence-newsroom-card";
  var JOHN_DEERE_CARD_ID = "agroai-john-deere-newsroom-card";

  function isPublished() {
    return Date.now() >= JOHN_DEERE_PUBLISH_AT_MS;
  }

  function isReadArticleLink(link) {
    return /read article/i.test((link.textContent || "").replace(/\\s+/g, " ").trim());
  }

  function nearestArticleGroup(link) {
    var node = link.parentElement;
    for (var depth = 0; node && depth < 12; depth += 1, node = node.parentElement) {
      var readLinks = Array.prototype.filter.call(node.querySelectorAll("a"), isReadArticleLink);
      if (readLinks.length >= 2 && readLinks.length <= 24) return node;
    }
    return null;
  }

  function findNewsroomGrid() {
    var readLinks = Array.prototype.filter.call(document.querySelectorAll("a"), isReadArticleLink);
    var groups = new Map();
    readLinks.forEach(function (link) {
      var group = nearestArticleGroup(link);
      if (group) groups.set(group, (groups.get(group) || 0) + 1);
    });
    var best = null;
    var bestScore = 0;
    groups.forEach(function (score, group) {
      if (score > bestScore) {
        best = group;
        bestScore = score;
      }
    });
    return best;
  }

  function removeLegacyJohnDeereArticle() {
    var grid = findNewsroomGrid();
    Array.prototype.forEach.call(document.querySelectorAll("a[href]"), function (link) {
      var pathname;
      try {
        pathname = new URL(link.getAttribute("href"), window.location.origin).pathname.replace(/\\/$/, "");
      } catch (_error) {
        return;
      }
      if (pathname !== LEGACY_JOHN_DEERE_ARTICLE_PATH) return;

      var entry = link;
      if (grid) {
        while (entry.parentElement && entry.parentElement !== grid) entry = entry.parentElement;
      }
      if (grid && entry.parentElement === grid) {
        entry.remove();
        return;
      }
      var article = link.closest("article");
      if (article) article.remove();
      else link.remove();
    });
  }

  function renderFieldIntelligenceCard() {
    var existing = document.getElementById(FIELD_CARD_ID);
    if (existing || document.querySelector('a[href*="introducing-agro-ai-field-intelligence"]')) return true;
    var grid = findNewsroomGrid();
    if (!grid) return false;

    var shell = document.createElement("article");
    shell.id = FIELD_CARD_ID;
    shell.className = "agroai-fi-news-card-shell";
    shell.setAttribute("data-agroai-newsroom-entry", "field-intelligence");
    shell.innerHTML =
      '<a class="agroai-fi-news-card" href="' + FIELD_ARTICLE_PATH + '" aria-label="Read Introducing AGRO-AI Field Intelligence">' +
        '<div class="agroai-fi-news-card-media">' +
          '<img src="' + FIELD_ARTICLE_PATH + '/cover.webp" alt="AGRO-AI Field Intelligence" width="3840" height="2160" loading="eager" />' +
          '<span class="agroai-fi-news-card-badge">' + (isPublished() ? 'Product' : 'Latest') + '</span>' +
        '</div>' +
        '<div class="agroai-fi-news-card-body">' +
          '<div class="agroai-fi-news-card-kicker">Product launch · Field Intelligence</div>' +
          '<h2 class="agroai-fi-news-card-title">Introducing AGRO-AI Field Intelligence</h2>' +
          '<p class="agroai-fi-news-card-copy">Voice, images and location become structured field evidence, operational decisions, assigned work and verified outcomes inside the AGRO-AI Enterprise Portal.</p>' +
          '<div class="agroai-fi-news-card-footer"><span>San Francisco, California<br />Tuesday, July 21, 2026</span><span class="agroai-fi-news-card-read">Read article →</span></div>' +
        '</div>' +
      '</a>';
    grid.insertBefore(shell, grid.firstElementChild);
    return true;
  }

  function updateFieldIntelligenceBadge() {
    var fieldCard = document.getElementById(FIELD_CARD_ID);
    if (!fieldCard) return;
    var badge = fieldCard.querySelector(".agroai-fi-news-card-badge");
    if (badge) badge.textContent = isPublished() ? "Product" : "Latest";
  }

  function renderJohnDeereCard() {
    if (!isPublished()) return false;
    if (document.getElementById(JOHN_DEERE_CARD_ID) || document.querySelector('a[href*="agro-ai-connected-john-deere-operations-center"]')) return true;
    var grid = findNewsroomGrid();
    if (!grid) return false;

    var shell = document.createElement("article");
    shell.id = JOHN_DEERE_CARD_ID;
    shell.className = "agroai-fi-news-card-shell";
    shell.setAttribute("data-agroai-newsroom-entry", "john-deere-operations-center");
    shell.innerHTML =
      '<a class="agroai-fi-news-card" href="' + JOHN_DEERE_ARTICLE_PATH + '" aria-label="Read AGRO-AI is now connected with John Deere Operations Center">' +
        '<div class="agroai-jd-news-card-media">' +
          '<img class="agroai-jd-news-card-logo" src="' + JOHN_DEERE_ARTICLE_PATH + '/agro-ai-logo.png" alt="AGRO-AI" width="150" height="48" />' +
          '<span class="agroai-fi-news-card-badge">Latest</span>' +
          '<div class="agroai-jd-news-card-flow"><span class="agroai-jd-news-card-node">Operations Center</span><span class="agroai-jd-news-card-arrow">→</span><span class="agroai-jd-news-card-node">AGRO-AI</span></div>' +
        '</div>' +
        '<div class="agroai-fi-news-card-body">' +
          '<div class="agroai-fi-news-card-kicker">Company news · Connected operations</div>' +
          '<h2 class="agroai-fi-news-card-title">AGRO-AI is now connected with John Deere Operations Center™</h2>' +
          '<p class="agroai-fi-news-card-copy">Eligible users can bring authorized Operations Center context into AGRO-AI recommendations, reporting, verification and Field Intelligence workflows.</p>' +
          '<div class="agroai-fi-news-card-footer"><span>San Francisco, California<br />Tuesday, July 28, 2026 · 8:00 AM PDT</span><span class="agroai-fi-news-card-read">Read article →</span></div>' +
        '</div>' +
      '</a>';
    grid.insertBefore(shell, grid.firstElementChild);
    return true;
  }

  function reconcileNewsroom() {
    removeLegacyJohnDeereArticle();
    renderFieldIntelligenceCard();
    updateFieldIntelligenceBadge();
    renderJohnDeereCard();
  }

  var observer = new MutationObserver(reconcileNewsroom);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  reconcileNewsroom();
  window.setTimeout(reconcileNewsroom, 250);
  window.setTimeout(reconcileNewsroom, 1000);
  window.setTimeout(function () {
    reconcileNewsroom();
    observer.disconnect();
  }, 5000);

  var publicationDelay = JOHN_DEERE_PUBLISH_AT_MS - Date.now();
  if (publicationDelay > 0 && publicationDelay < 2147483000) {
    window.setTimeout(reconcileNewsroom, publicationDelay + 250);
  }
})();
`;

function johnDeerePublished(now = Date.now()): boolean {
  return now >= JOHN_DEERE_PUBLISH_AT_MS;
}

function articleHeaders(): Headers {
  const headers = new Headers();
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "public, max-age=300, s-maxage=300, stale-while-revalidate=86400");
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

function assetHeaders(contentType: string): Headers {
  const headers = new Headers();
  headers.set("content-type", contentType);
  headers.set("cache-control", "public, max-age=300, s-maxage=300, stale-while-revalidate=86400");
  headers.set("x-content-type-options", "nosniff");
  headers.set("cross-origin-resource-policy", "same-origin");
  return headers;
}

function newsroomHeaders(upstream: Response, published: boolean): Headers {
  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", published ? "public, max-age=120, s-maxage=120, stale-while-revalidate=3600" : "no-store");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-agroai-newsroom-field-intelligence", "visible");
  headers.set("x-agroai-newsroom-john-deere", published ? "visible" : `scheduled:${JOHN_DEERE_PUBLISH_AT}`);
  return headers;
}

function removeLegacyJohnDeereArticleMarkup(html: string): string {
  const withoutArticleBlocks = html.replace(/<article\b[^>]*>[\s\S]*?<\/article>/gi, (article) =>
    LEGACY_JOHN_DEERE_ARTICLE_HREF.test(article) ? "" : article,
  );
  return withoutArticleBlocks.replace(/<a\b[^>]*>[\s\S]*?<\/a>/gi, (anchor) =>
    LEGACY_JOHN_DEERE_ARTICLE_HREF.test(anchor) ? "" : anchor,
  );
}

async function newsroomResponse(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const upstreamUrl = new URL(NEWSROOM_PATH + incoming.search, MARKETING_ORIGIN);
  const upstream = await fetch(upstreamUrl.toString(), {
    cf: { cacheEverything: true, cacheTtl: 120 },
    headers: { "user-agent": "AGRO-AI-Newsroom/2.0", accept: "text/html" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) {
    return new Response("The AGRO-AI newsroom is temporarily unavailable.", {
      status: 503,
      headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
    });
  }

  const published = johnDeerePublished();
  let html = removeLegacyJohnDeereArticleMarkup(await upstream.text());
  const injection = `<link rel="stylesheet" href="${NEWSROOM_STYLE_PATH}" data-agroai-newsroom="style" /><script defer src="${NEWSROOM_SCRIPT_PATH}" data-agroai-newsroom="script"></script>`;
  if (!html.includes("data-agroai-newsroom=")) {
    html = html.includes("</body>") ? html.replace("</body>", `${injection}</body>`) : `${html}${injection}`;
  }
  return new Response(request.method === "HEAD" ? null : html, {
    status: upstream.status,
    headers: newsroomHeaders(upstream, published),
  });
}

async function articleResponse(request: Request): Promise<Response> {
  const upstream = await fetch(ARTICLE_SOURCE, {
    cf: { cacheEverything: true, cacheTtl: 300 },
    headers: { "user-agent": "AGRO-AI-Field-Intelligence-Launch/1.0" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) {
    return new Response("The AGRO-AI Field Intelligence launch article is temporarily unavailable.", {
      status: 503,
      headers: articleHeaders(),
    });
  }
  const html = (await upstream.text()).replaceAll(OBSOLETE_VIDEO_ID, CURRENT_VIDEO_ID);
  return new Response(request.method === "HEAD" ? null : html, { status: 200, headers: articleHeaders() });
}

async function johnDeereArticleResponse(request: Request): Promise<Response> {
  if (!johnDeerePublished()) return scheduledArticleResponse();
  const upstream = await fetch(JOHN_DEERE_ARTICLE_SOURCE, {
    cf: { cacheEverything: true, cacheTtl: 300 },
    headers: { "user-agent": "AGRO-AI-John-Deere-Operations-Center-News/1.0" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) {
    return new Response("The AGRO-AI Operations Center announcement is temporarily unavailable.", {
      status: 503,
      headers: articleHeaders(),
    });
  }
  return new Response(request.method === "HEAD" ? null : await upstream.text(), { status: 200, headers: articleHeaders() });
}

async function logoResponse(request: Request): Promise<Response> {
  const upstream = await fetch(LOGO_SOURCE, {
    cf: { cacheEverything: true, cacheTtl: 86400 },
    headers: { "user-agent": "AGRO-AI-Official-Logo/1.0" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) return new Response("Logo unavailable", { status: 503 });

  const headers = new Headers();
  headers.set("content-type", upstream.headers.get("content-type") || "image/png");
  headers.set("cache-control", "public, max-age=86400, s-maxage=86400, immutable");
  headers.set("x-content-type-options", "nosniff");
  headers.set("cross-origin-resource-policy", "same-origin");
  headers.set("x-agroai-logo-source", "official-repository-asset");
  return new Response(request.method === "HEAD" ? null : upstream.body, { status: 200, headers });
}

async function coverResponse(request: Request): Promise<Response> {
  const transformed = await fetch(YOUTUBE_COVER, {
    cf: {
      cacheEverything: true,
      cacheTtl: 86400,
      image: { width: 3840, height: 2160, fit: "cover", quality: 92, format: "webp" },
    },
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

function legacyJohnDeereArticleResponse(): Response {
  if (!johnDeerePublished()) return scheduledArticleResponse();
  const headers = new Headers();
  headers.set("location", JOHN_DEERE_ARTICLE_PATH);
  headers.set("cache-control", "public, max-age=300, s-maxage=300");
  headers.set("x-content-type-options", "nosniff");
  return new Response(null, { status: 301, headers });
}

export default {
  async fetch(request: Request): Promise<Response> {
    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method not allowed", { status: 405, headers: { allow: "GET, HEAD" } });
    }
    const url = new URL(request.url);
    const normalized = url.pathname.length > 1 ? url.pathname.replace(/\/$/, "") : url.pathname;
    if (normalized === NEWSROOM_PATH) return newsroomResponse(request);
    if (normalized === NEWSROOM_SCRIPT_PATH) {
      return new Response(request.method === "HEAD" ? null : NEWSROOM_SCRIPT, { status: 200, headers: assetHeaders("text/javascript; charset=utf-8") });
    }
    if (normalized === NEWSROOM_STYLE_PATH) {
      return new Response(request.method === "HEAD" ? null : NEWSROOM_STYLE, { status: 200, headers: assetHeaders("text/css; charset=utf-8") });
    }
    if (normalized === LEGACY_JOHN_DEERE_ARTICLE_PATH || normalized.startsWith(`${LEGACY_JOHN_DEERE_ARTICLE_PATH}/`)) return legacyJohnDeereArticleResponse();
    if (normalized === JOHN_DEERE_ARTICLE_PATH) return johnDeereArticleResponse(request);
    if (normalized === JOHN_DEERE_LOGO_PATH) {
      if (!johnDeerePublished()) return scheduledArticleResponse();
      return logoResponse(request);
    }
    if (normalized === ARTICLE_PATH) return articleResponse(request);
    if (normalized === LOGO_PATH) return logoResponse(request);
    if (normalized === COVER_PATH) return coverResponse(request);
    return new Response("Not found", { status: 404 });
  },
};
