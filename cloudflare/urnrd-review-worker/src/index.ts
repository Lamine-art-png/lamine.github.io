const SOURCE_URL = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/urnrd-capability-review-2026/index.html";
const REVIEW_PATH = "/urnrd-capability-review-2026";

function securityHeaders(): Headers {
  const headers = new Headers();
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "public, max-age=300, s-maxage=900");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("x-robots-tag", "noindex, nofollow, noarchive");
  headers.set("content-security-policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: https:; connect-src 'self'; font-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
  return headers;
}

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/$/, "");

    if (path !== REVIEW_PATH) {
      return new Response("Not found", { status: 404 });
    }

    if (url.pathname === REVIEW_PATH) {
      return Response.redirect(`${url.origin}${REVIEW_PATH}/`, 308);
    }

    const upstream = await fetch(SOURCE_URL, {
      cf: { cacheEverything: true, cacheTtl: 900 },
      headers: { "user-agent": "AGRO-AI-URNRD-Review/1.0" },
    });

    if (!upstream.ok) {
      return new Response("The capability review is temporarily unavailable.", {
        status: 503,
        headers: securityHeaders(),
      });
    }

    return new Response(await upstream.text(), {
      status: 200,
      headers: securityHeaders(),
    });
  },
};
