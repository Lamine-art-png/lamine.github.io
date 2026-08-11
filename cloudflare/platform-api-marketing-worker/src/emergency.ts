import productEntryHandler from "./index";

interface Env {
  ASSETS: Fetcher;
  MARKETING_ORIGIN?: string;
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

const CONTACT_API = "https://api.agroai-pilot.com/v1/sales/contact";
const OFFICIAL_CONTACT_EMAIL = "contact@agroai-pilot.com";
const LINKEDIN_URL = "https://www.linkedin.com/company/agro-ai-inc/";
const INSTAGRAM_URL = "https://www.instagram.com/agroai.inc/";
const YOUTUBE_URL = "https://www.youtube.com/channel/UCd3tQLAOtMmjFhRNVdU08tA";
const OFFICIAL_LOGO = "/platform-api/assets/logo.svg";

const socialFooterStyle = `<style id="agroai-social-footer-style">
  #agroai-social-footer{background:#050505;color:#fff;font-family:"Glacial Indifference","Avenir Next",Avenir,Arial,sans-serif;border-top:1px solid rgba(255,255,255,.12)}
  #agroai-social-footer .agroai-social-inner{width:min(1240px,calc(100% - 40px));margin:0 auto;min-height:132px;display:flex;align-items:center;justify-content:space-between;gap:28px;padding:32px 0}
  #agroai-social-footer .agroai-social-email{color:#fff;text-decoration:none;font-size:16px;font-weight:700;letter-spacing:.01em}
  #agroai-social-footer .agroai-social-email:hover,#agroai-social-footer .agroai-social-email:focus-visible{text-decoration:underline;text-underline-offset:5px}
  #agroai-social-footer .agroai-social-links{display:flex;align-items:center;gap:30px}
  #agroai-social-footer .agroai-social-link{display:inline-flex;width:40px;height:40px;align-items:center;justify-content:center;color:#fff;text-decoration:none;border-radius:50%;transition:transform .18s ease,opacity .18s ease}
  #agroai-social-footer .agroai-social-link:hover,#agroai-social-footer .agroai-social-link:focus-visible{transform:translateY(-2px);opacity:.72;outline:none}
  #agroai-social-footer svg{width:25px;height:25px;display:block}
  @media(max-width:680px){#agroai-social-footer .agroai-social-inner{min-height:150px;flex-direction:column;align-items:flex-start;justify-content:center}.agroai-social-links{gap:22px}}
</style>`;

const socialFooter = `<footer id="agroai-social-footer" aria-label="AGRO-AI social links">
  <div class="agroai-social-inner">
    <a class="agroai-social-email" href="mailto:${OFFICIAL_CONTACT_EMAIL}">${OFFICIAL_CONTACT_EMAIL}</a>
    <nav class="agroai-social-links" aria-label="Follow AGRO-AI">
      <a class="agroai-social-link" href="${LINKEDIN_URL}" target="_blank" rel="noopener noreferrer" aria-label="AGRO-AI on LinkedIn" title="LinkedIn">
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M5.36 7.78A2.14 2.14 0 1 0 5.36 3.5a2.14 2.14 0 0 0 0 4.28ZM3.52 20.5h3.69V9.12H3.52V20.5ZM9.46 9.12h3.54v1.56h.05c.49-.93 1.7-1.91 3.5-1.91 3.74 0 4.43 2.46 4.43 5.66v6.07h-3.69v-5.38c0-1.28-.02-2.94-1.79-2.94-1.8 0-2.08 1.4-2.08 2.85v5.47H9.46V9.12Z"/></svg>
      </a>
      <a class="agroai-social-link" href="${INSTAGRAM_URL}" target="_blank" rel="noopener noreferrer" aria-label="AGRO-AI on Instagram" title="Instagram">
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4.2"/><circle cx="17.4" cy="6.7" r="1" fill="currentColor" stroke="none"/></svg>
      </a>
      <a class="agroai-social-link" href="${YOUTUBE_URL}" target="_blank" rel="noopener noreferrer" aria-label="AGRO-AI on YouTube" title="YouTube">
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M23.2 7.1a3 3 0 0 0-2.1-2.12C19.23 4.5 12 4.5 12 4.5s-7.23 0-9.1.48A3 3 0 0 0 .8 7.1 31.3 31.3 0 0 0 .32 12c0 1.65.16 3.3.48 4.9a3 3 0 0 0 2.1 2.12c1.87.48 9.1.48 9.1.48s7.23 0 9.1-.48a3 3 0 0 0 2.1-2.12c.32-1.6.48-3.25.48-4.9s-.16-3.3-.48-4.9ZM9.67 15.21V8.79L15.73 12l-6.06 3.21Z"/></svg>
      </a>
    </nav>
  </div>
</footer>`;

function securityHeaders(contentType: string): Headers {
  return new Headers({
    "content-type": contentType,
    "cache-control": "no-store, max-age=0",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "content-security-policy": [
      "default-src 'none'",
      "img-src 'self' data:",
      "style-src 'unsafe-inline'",
      "script-src 'unsafe-inline'",
      "connect-src https://api.agroai-pilot.com",
      "form-action 'self' mailto:",
      "base-uri 'none'",
      "frame-ancestors 'none'",
    ].join("; "),
  });
}

function contactPage(): Response {
  const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="index,follow">
  <title>Contact AGRO-AI</title>
  <meta name="description" content="Contact AGRO-AI for customer, investor, partner, media, and collaboration inquiries.">
  <style>
    :root{color-scheme:light;--ink:#0b1711;--muted:#5d6962;--line:#dde4df;--paper:#f8faf8;--green:#173c29;--lime:#e6f18d}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Glacial Indifference","Avenir Next",Avenir,Arial,sans-serif;line-height:1.5}
    a{color:inherit}.shell{min-height:100vh;display:flex;flex-direction:column}.top{display:flex;align-items:center;justify-content:space-between;padding:20px clamp(20px,5vw,64px);border-bottom:1px solid var(--line);background:#fff}
    .brand{display:flex;align-items:center;gap:10px;text-decoration:none;font-weight:800;letter-spacing:.02em}.brand img{width:38px;height:38px;object-fit:contain}.back{font-size:14px;font-weight:700;text-decoration:none}.back:hover{text-decoration:underline;text-underline-offset:4px}
    main{width:min(1120px,calc(100% - 36px));margin:0 auto;padding:clamp(52px,8vw,96px) 0 78px}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.16em;font-weight:800;color:#466153}
    h1{font-size:clamp(46px,7vw,82px);line-height:.98;letter-spacing:-.045em;max-width:850px;margin:14px 0 22px;font-weight:700}.lede{max-width:760px;font-size:clamp(17px,2vw,21px);color:var(--muted);margin:0 0 42px}
    .grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr);gap:24px;align-items:start}.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:clamp(22px,4vw,38px)}
    form{display:grid;gap:18px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}label{display:grid;gap:7px;font-size:13px;font-weight:800}.optional{font-weight:400;color:var(--muted)}
    input,textarea{width:100%;border:1px solid #bcc9c1;border-radius:10px;background:#fff;padding:13px 14px;font:inherit;color:var(--ink);outline:none}textarea{min-height:150px;resize:vertical}input:focus,textarea:focus{border-color:var(--green);box-shadow:0 0 0 3px rgba(23,60,41,.12)}
    .honeypot{position:absolute!important;left:-10000px!important;width:1px!important;height:1px!important;overflow:hidden!important}.submit{border:0;border-radius:10px;padding:14px 18px;background:var(--green);color:#fff;font:inherit;font-weight:800;cursor:pointer}.submit:hover{background:#0d2b1e}.submit:disabled{opacity:.6;cursor:wait}
    .status{min-height:24px;font-size:14px;font-weight:700}.status.ok{color:#176b3a}.status.error{color:#9b241c}.side h2{margin:0 0 12px;font-size:22px}.side p{margin:0 0 22px;color:var(--muted)}.action{display:flex;align-items:center;justify-content:center;width:100%;padding:14px 16px;border-radius:10px;border:1px solid var(--line);background:#fff;text-decoration:none;font-weight:800;margin-top:10px}.action.primary{background:var(--lime);border-color:var(--lime)}.action:hover{transform:translateY(-1px)}.note{margin-top:22px;padding-top:20px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
    .mini-socials{display:flex;align-items:center;gap:12px;margin-top:22px}.mini-socials a{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border:1px solid var(--line);border-radius:50%;text-decoration:none}.mini-socials a:hover{background:#f1f4f2}.mini-socials svg{width:21px;height:21px}
    @media(max-width:800px){.grid{grid-template-columns:1fr}.two{grid-template-columns:1fr}.top{padding:15px 18px}}
  </style>
  ${socialFooterStyle}
</head>
<body>
<div class="shell">
  <header class="top">
    <a class="brand" href="/"><img src="${OFFICIAL_LOGO}" alt="AGRO-AI"><span>AGRO-AI</span></a>
    <a class="back" href="/">Back to AGRO-AI</a>
  </header>
  <main>
    <div class="eyebrow">Contact</div>
    <h1>Contact AGRO-AI.</h1>
    <p class="lede">For customer support, partnerships, investment, media, collaborations, and general inquiries, reach our team through the form or our official email.</p>
    <div class="grid">
      <section class="card">
        <form id="contact-form" novalidate>
          <div class="two">
            <label>Full name<input name="name" autocomplete="name" maxlength="160" required></label>
            <label>Work email<input name="email" type="email" autocomplete="email" maxlength="240" required></label>
          </div>
          <div class="two">
            <label>Company <span class="optional">optional</span><input name="company" autocomplete="organization" maxlength="160"></label>
            <label>Subject<input name="subject" maxlength="180" required value="AGRO-AI inquiry"></label>
          </div>
          <label>Message<textarea name="message" maxlength="4000" required placeholder="Tell us how we can help."></textarea></label>
          <label class="honeypot" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
          <button class="submit" type="submit">Send message</button>
          <div id="form-status" class="status" role="status" aria-live="polite"></div>
        </form>
      </section>
      <aside class="card side">
        <h2>Official email</h2>
        <p>Use our official domain address for customers, investors, partners, collaborators, media, and general communication.</p>
        <a class="action primary" href="mailto:${OFFICIAL_CONTACT_EMAIL}?subject=AGRO-AI%20inquiry">${OFFICIAL_CONTACT_EMAIL}</a>
        <div class="mini-socials" aria-label="AGRO-AI social profiles">
          <a href="${LINKEDIN_URL}" target="_blank" rel="noopener noreferrer" aria-label="LinkedIn"><svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M5.36 7.78A2.14 2.14 0 1 0 5.36 3.5a2.14 2.14 0 0 0 0 4.28ZM3.52 20.5h3.69V9.12H3.52V20.5ZM9.46 9.12h3.54v1.56h.05c.49-.93 1.7-1.91 3.5-1.91 3.74 0 4.43 2.46 4.43 5.66v6.07h-3.69v-5.38c0-1.28-.02-2.94-1.79-2.94-1.8 0-2.08 1.4-2.08 2.85v5.47H9.46V9.12Z"/></svg></a>
          <a href="${INSTAGRAM_URL}" target="_blank" rel="noopener noreferrer" aria-label="Instagram"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4.2"/><circle cx="17.4" cy="6.7" r="1" fill="currentColor" stroke="none"/></svg></a>
          <a href="${YOUTUBE_URL}" target="_blank" rel="noopener noreferrer" aria-label="YouTube"><svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M23.2 7.1a3 3 0 0 0-2.1-2.12C19.23 4.5 12 4.5 12 4.5s-7.23 0-9.1.48A3 3 0 0 0 .8 7.1 31.3 31.3 0 0 0 .32 12c0 1.65.16 3.3.48 4.9a3 3 0 0 0 2.1 2.12c1.87.48 9.1.48 9.1.48s7.23 0 9.1-.48a3 3 0 0 0 2.1-2.12c.32-1.6.48-3.25.48-4.9s-.16-3.3-.48-4.9ZM9.67 15.21V8.79L15.73 12l-6.06 3.21Z"/></svg></a>
        </div>
        <div class="note">Do not send passwords, access codes, API keys, financial credentials, or other secrets through this page.</div>
      </aside>
    </div>
  </main>
  ${socialFooter}
</div>
<script>
(() => {
  const form = document.getElementById('contact-form');
  const status = document.getElementById('form-status');
  const button = form.querySelector('button[type="submit"]');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    status.className = 'status';
    status.textContent = '';
    const data = new FormData(form);
    if (String(data.get('website') || '').trim()) return;
    const payload = {
      type: 'sales',
      priority: 'normal',
      name: String(data.get('name') || '').trim(),
      email: String(data.get('email') || '').trim(),
      company: String(data.get('company') || '').trim() || null,
      subject: String(data.get('subject') || '').trim(),
      message: String(data.get('message') || '').trim(),
      source_page: 'contact-page',
      metadata: { channel: 'website', official_contact_email: '${OFFICIAL_CONTACT_EMAIL}' }
    };
    if (!payload.name || !payload.email || !payload.subject || !payload.message) {
      status.className = 'status error';
      status.textContent = 'Complete the required fields.';
      return;
    }
    button.disabled = true;
    button.textContent = 'Sending…';
    try {
      const response = await fetch('${CONTACT_API}', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'accept': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error('request_failed');
      form.reset();
      status.className = 'status ok';
      status.textContent = 'Message received. AGRO-AI will follow up through the email you provided.';
    } catch {
      status.className = 'status error';
      status.innerHTML = 'The form could not complete. Email <a href="mailto:${OFFICIAL_CONTACT_EMAIL}?subject=AGRO-AI%20inquiry">${OFFICIAL_CONTACT_EMAIL}</a>.';
    } finally {
      button.disabled = false;
      button.textContent = 'Send message';
    }
  });
})();
</script>
</body>
</html>`;
  return new Response(html, { status: 200, headers: securityHeaders("text/html; charset=utf-8") });
}

async function homepageWithSocialFooter(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const upstream = await (productEntryHandler as ExportedHandler<Env>).fetch!(request, env, ctx);
  if (request.method === "HEAD" || !upstream.ok || !String(upstream.headers.get("content-type") || "").includes("text/html")) {
    return upstream;
  }
  const headers = new Headers(upstream.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("etag");
  headers.set("cache-control", "public, max-age=0, must-revalidate");
  let html = await upstream.text();
  if (!html.includes('id="agroai-social-footer"')) {
    html = html.replace("</head>", `${socialFooterStyle}</head>`).replace("</body>", `${socialFooter}</body>`);
  }
  return new Response(html, { status: upstream.status, statusText: upstream.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if ((url.pathname === "/contact" || url.pathname === "/contact/") && ["GET", "HEAD"].includes(request.method)) {
      if (request.method === "HEAD") return new Response(null, { status: 200, headers: securityHeaders("text/html; charset=utf-8") });
      return contactPage();
    }
    if (url.pathname === "/") return homepageWithSocialFooter(request, env, ctx);
    return (productEntryHandler as ExportedHandler<Env>).fetch!(request, env, ctx);
  },
} satisfies ExportedHandler<Env>;
