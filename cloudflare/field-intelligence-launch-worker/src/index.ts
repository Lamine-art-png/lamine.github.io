const NEWSROOM_PATH = "/news";
const NEWSROOM_SCRIPT_PATH = "/news/field-intelligence-newsroom.js";
const NEWSROOM_STYLE_PATH = "/news/field-intelligence-newsroom.css";
const ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
const COVER_PATH = `${ARTICLE_PATH}/cover.webp`;
const MARKETING_ORIGIN = "https://agroai-343.pages.dev";
const ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/introducing-agro-ai-field-intelligence/index.html";
const CURRENT_VIDEO_ID = "GiM6WZY0HG0";
const OBSOLETE_VIDEO_ID = "IMLVblFeW3s";
const YOUTUBE_COVER = `https://img.youtube.com/vi/${CURRENT_VIDEO_ID}/maxresdefault.jpg`;

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
@media(max-width:680px){.agroai-fi-news-card-body{padding:21px}.agroai-fi-news-card-title{font-size:25px}.agroai-fi-news-card-footer{align-items:flex-start;flex-direction:column;gap:10px}}
`;

const NEWSROOM_SCRIPT = `
(function () {
  var ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
  var CARD_ID = "agroai-field-intelligence-newsroom-card";

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

  function renderCard() {
    if (document.getElementById(CARD_ID) || document.querySelector('a[href*="introducing-agro-ai-field-intelligence"]')) return true;
    var grid = findNewsroomGrid();
    if (!grid) return false;

    var shell = document.createElement("article");
    shell.id = CARD_ID;
    shell.className = "agroai-fi-news-card-shell";
    shell.setAttribute("data-agroai-newsroom-entry", "field-intelligence");
    shell.innerHTML =
      '<a class="agroai-fi-news-card" href="' + ARTICLE_PATH + '" aria-label="Read Introducing AGRO-AI Field Intelligence">' +
        '<div class="agroai-fi-news-card-media">' +
          '<img src="' + ARTICLE_PATH + '/cover.webp" alt="AGRO-AI Field Intelligence" width="3840" height="2160" loading="eager" />' +
          '<span class="agroai-fi-news-card-badge">Latest</span>' +
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

  var observer = new MutationObserver(function () {
    if (renderCard()) observer.disconnect();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  renderCard();
  window.setTimeout(renderCard, 250);
  window.setTimeout(renderCard, 1000);
  window.setTimeout(renderCard, 2500);
})();
`;

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

function assetHeaders(contentType: string): Headers {
  const headers = new Headers();
  headers.set("content-type", contentType);
  headers.set("cache-control", "public, max-age=300, s-maxage=300, stale-while-revalidate=86400");
  headers.set("x-content-type-options", "nosniff");
  headers.set("cross-origin-resource-policy", "same-origin");
  return headers;
}

function newsroomHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "public, max-age=120, s-maxage=120, stale-while-revalidate=3600");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-agroai-newsroom-field-intelligence", "visible");
  return headers;
}

async function newsroomResponse(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const upstreamUrl = new URL(NEWSROOM_PATH + incoming.search, MARKETING_ORIGIN);
  const upstream = await fetch(upstreamUrl.toString(), {
    cf: { cacheEverything: true, cacheTtl: 120 },
    headers: { "user-agent": "AGRO-AI-Field-Intelligence-Newsroom/1.0", accept: "text/html" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) {
    return new Response("The AGRO-AI newsroom is temporarily unavailable.", {
      status: 503,
      headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
    });
  }

  let html = await upstream.text();
  const injection = `<link rel="stylesheet" href="${NEWSROOM_STYLE_PATH}" data-agroai-field-intelligence-newsroom="style" /><script defer src="${NEWSROOM_SCRIPT_PATH}" data-agroai-field-intelligence-newsroom="script"></script>`;
  if (!html.includes("data-agroai-field-intelligence-newsroom")) {
    html = html.includes("</body>") ? html.replace("</body>", `${injection}</body>`) : `${html}${injection}`;
  }
  return new Response(request.method === "HEAD" ? null : html, {
    status: upstream.status,
    headers: newsroomHeaders(upstream),
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
    if (normalized === ARTICLE_PATH) return articleResponse(request);
    if (normalized === COVER_PATH) return coverResponse(request);
    return new Response("Not found", { status: 404 });
  },
};
