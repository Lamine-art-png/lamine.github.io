const ARTICLE_PATH = "/news/introducing-agro-ai-field-intelligence";
const COVER_PATH = `${ARTICLE_PATH}/cover.webp`;
const NEWSROOM_PATH = "/news";
const ARTICLE_SOURCE = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/client/public/news/introducing-agro-ai-field-intelligence/index.html";
const NEWSROOM_SOURCE = "https://lamine-github-io.pages.dev/news";
const CURRENT_VIDEO_ID = "GiM6WZY0HG0";
const OBSOLETE_VIDEO_ID = "IMLVblFeW3s";
const YOUTUBE_COVER = `https://img.youtube.com/vi/${CURRENT_VIDEO_ID}/maxresdefault.jpg`;

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

function newsroomCard(): string {
  return `
<style id="agroai-field-intelligence-newsroom-card">
  .agroai-fi-newsroom{max-width:1360px;margin:0 auto 96px;padding:0 5.5vw;font-family:"Glacial Indifference",system-ui,sans-serif}
  .agroai-fi-newsroom__card{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);overflow:hidden;border:1px solid rgba(15,35,27,.12);border-radius:30px;background:#fff;box-shadow:0 28px 80px rgba(9,39,29,.12);text-decoration:none;color:#10231b}
  .agroai-fi-newsroom__image{min-height:460px;background:#07140f url('${COVER_PATH}') center/cover no-repeat}
  .agroai-fi-newsroom__copy{display:flex;flex-direction:column;justify-content:center;padding:48px}
  .agroai-fi-newsroom__meta{margin-bottom:18px;color:#215e43;font-size:12px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}
  .agroai-fi-newsroom__copy h2{margin:0 0 20px;font-size:clamp(34px,4vw,58px);line-height:1.02;letter-spacing:-.045em}
  .agroai-fi-newsroom__copy p{margin:0 0 28px;color:#4f6258;font-size:18px;line-height:1.55}
  .agroai-fi-newsroom__cta{align-self:flex-start;padding:13px 18px;border-radius:999px;background:#0d3928;color:#fff;font-size:14px;font-weight:700}
  @media(max-width:850px){.agroai-fi-newsroom__card{grid-template-columns:1fr}.agroai-fi-newsroom__image{min-height:300px}.agroai-fi-newsroom__copy{padding:30px 24px}}
</style>
<section class="agroai-fi-newsroom" aria-labelledby="agroai-fi-newsroom-title">
  <a class="agroai-fi-newsroom__card" href="${ARTICLE_PATH}">
    <div class="agroai-fi-newsroom__image" role="img" aria-label="AGRO-AI Field Intelligence launch"></div>
    <div class="agroai-fi-newsroom__copy">
      <div class="agroai-fi-newsroom__meta">Product launch · San Francisco, California · July 21, 2026</div>
      <h2 id="agroai-fi-newsroom-title">Introducing AGRO-AI Field Intelligence</h2>
      <p>Voice, images and location become structured operational evidence, decisions, assigned work and verified outcomes inside the AGRO-AI Enterprise Portal.</p>
      <span class="agroai-fi-newsroom__cta">Read article →</span>
    </div>
  </a>
</section>`;
}

function injectNewsroomCard(html: string): string {
  if (html.includes(ARTICLE_PATH) || html.includes("agroai-field-intelligence-newsroom-card")) return html;
  const card = newsroomCard();
  const newsroomHeading = /(<h[1-3][^>]*>\s*From the newsroom\s*<\/h[1-3]>)/i;
  if (newsroomHeading.test(html)) return html.replace(newsroomHeading, `$1${card}`);
  if (html.includes("</main>")) return html.replace("</main>", `${card}</main>`);
  return html.replace("</body>", `${card}</body>`);
}

async function newsroomResponse(request: Request): Promise<Response> {
  const upstream = await fetch(NEWSROOM_SOURCE, {
    cf: { cacheEverything: true, cacheTtl: 180 },
    headers: { "user-agent": "AGRO-AI-Newsroom-Index/1.0" },
  } as RequestInit & { cf: { cacheEverything: boolean; cacheTtl: number } });
  if (!upstream.ok) return new Response("AGRO-AI Newsroom is temporarily unavailable.", { status: 503 });
  const html = injectNewsroomCard(await upstream.text());
  const headers = new Headers(upstream.headers);
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "public, max-age=180, s-maxage=180, stale-while-revalidate=3600");
  headers.delete("content-length");
  return new Response(request.method === "HEAD" ? null : html, { status: 200, headers });
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
    if (normalized === ARTICLE_PATH) return articleResponse(request);
    if (normalized === COVER_PATH) return coverResponse(request);
    return new Response("Not found", { status: 404 });
  },
};
