const FIELD_INTELLIGENCE_ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
const JOHN_DEERE_ARTICLE_PATH = "/news/agro-ai-connected-john-deere-operations-center";
const LEGACY_JOHN_DEERE_ARTICLE_PATH = "/news/john-deere-api-access";
const JOHN_DEERE_PUBLISH_AT = "2026-07-28T08:00:00-07:00";
const JOHN_DEERE_PUBLISH_AT_MS = Date.parse(JOHN_DEERE_PUBLISH_AT);

const FIELD_INTELLIGENCE_COVER_PATH = `${FIELD_INTELLIGENCE_ARTICLE_PATH}/cover.webp`;
const FIELD_INTELLIGENCE_LOGO_PATH = `${FIELD_INTELLIGENCE_ARTICLE_PATH}/agro-ai-logo.png`;
const JOHN_DEERE_LOGO_PATH = `${JOHN_DEERE_ARTICLE_PATH}/agro-ai-logo.png`;

const FIELD_INTELLIGENCE_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/introducing-agro-ai-field-intelligence/index.html";
const JOHN_DEERE_ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/agro-ai-connected-john-deere-operations-center/index.html";
const OFFICIAL_LOGO_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/customer-portal/assets/agro-ai-logo.png";
const CURRENT_VIDEO_ID = "GiM6WZY0HG0";
const OBSOLETE_VIDEO_ID = "IMLVblFeW3s";
const YOUTUBE_COVER = `https://img.youtube.com/vi/${CURRENT_VIDEO_ID}/maxresdefault.jpg`;

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

async function fetchArticleSource(source: string, userAgent: string): Promise<Response> {
  return fetch(source, {
    cf: { cacheEverything: true, cacheTtl: 300 },
    headers: { "user-agent": userAgent },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
}

async function fieldIntelligenceArticleResponse(request: Request): Promise<Response> {
  const upstream = await fetchArticleSource(
    FIELD_INTELLIGENCE_ARTICLE_SOURCE,
    "AGRO-AI-Field-Intelligence-Launch/1.0",
  );
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
  const upstream = await fetchArticleSource(
    JOHN_DEERE_ARTICLE_SOURCE,
    "AGRO-AI-John-Deere-Operations-Center-News/1.0",
  );
  if (!upstream.ok) {
    return new Response("The AGRO-AI Operations Center announcement is temporarily unavailable.", {
      status: 503,
      headers: articleHeaders(),
    });
  }
  return new Response(request.method === "HEAD" ? null : await upstream.text(), {
    status: 200,
    headers: articleHeaders(),
  });
}

async function officialLogoResponse(request: Request): Promise<Response> {
  const upstream = await fetch(OFFICIAL_LOGO_SOURCE, {
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

async function fieldIntelligenceCoverResponse(request: Request): Promise<Response> {
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

    if (
      normalized === LEGACY_JOHN_DEERE_ARTICLE_PATH ||
      normalized.startsWith(`${LEGACY_JOHN_DEERE_ARTICLE_PATH}/`)
    ) {
      return legacyJohnDeereArticleResponse();
    }
    if (normalized === JOHN_DEERE_ARTICLE_PATH) return johnDeereArticleResponse(request);
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
