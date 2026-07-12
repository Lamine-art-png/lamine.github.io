const REVIEW_SOURCE_URL = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/urnrd-capability-review-2026/index.html";
const ENGINEERING_SOURCE_URL = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/urnrd-capability-review-2026/engineering/index.html";
const REVIEW_PATH = "/urnrd-capability-review-2026";
const ENGINEERING_PATH = `${REVIEW_PATH}/engineering`;
const PUBLIC_MONOREPO_URL = "https://github.com/Lamine-art-png/lamine.github.io";

function securityHeaders(): Headers {
  const headers = new Headers();
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "public, max-age=60, s-maxage=60");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("x-robots-tag", "noindex, nofollow, noarchive");
  headers.set("content-security-policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: https:; connect-src 'self'; font-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
  return headers;
}

function sanitizeReviewHtml(html: string, origin: string): string {
  const safeEngineeringUrl = `${origin}${ENGINEERING_PATH}/`;
  return html
    .replaceAll(PUBLIC_MONOREPO_URL, safeEngineeringUrl)
    .replaceAll("Public engineering repository", "Public engineering portfolio");
}

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/$/, "");

    const isReview = path === REVIEW_PATH;
    const isEngineering = path === ENGINEERING_PATH;
    if (!isReview && !isEngineering) {
      return new Response("Not found", { status: 404 });
    }

    const canonicalPath = isReview ? REVIEW_PATH : ENGINEERING_PATH;
    if (url.pathname === canonicalPath) {
      return Response.redirect(`${url.origin}${canonicalPath}/`, 308);
    }

    const sourceUrl = isReview ? REVIEW_SOURCE_URL : ENGINEERING_SOURCE_URL;
    const upstream = await fetch(sourceUrl, {
      cf: { cacheEverything: true, cacheTtl: 60 },
      headers: { "user-agent": "AGRO-AI-URNRD-Review/2.0" },
    });

    if (!upstream.ok) {
      return new Response("The requested AGRO-AI review material is temporarily unavailable.", {
        status: 503,
        headers: securityHeaders(),
      });
    }

    const sourceHtml = await upstream.text();
    const html = isReview ? sanitizeReviewHtml(sourceHtml, url.origin) : sourceHtml;
    return new Response(html, {
      status: 200,
      headers: securityHeaders(),
    });
  },
};
