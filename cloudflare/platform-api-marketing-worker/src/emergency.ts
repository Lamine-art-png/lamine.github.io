import productEntryHandler from "./index";

interface Env {
  ASSETS: Fetcher;
  MARKETING_ORIGIN?: string;
  PLATFORM_API_MARKETING_ENABLED?: string;
  PLATFORM_API_PUBLIC_DOCS_ENABLED?: string;
  PLATFORM_API_INDEXING_ENABLED?: string;
}

const CONTACT_API = "https://api.agroai-pilot.com/v1/sales/contact";
const TEMPORARY_DIRECT_EMAIL = "daabolaamiine@gmail.com";
const LINKEDIN_URL = "https://www.linkedin.com/company/agro-ai-inc";
const OFFICIAL_LOGO = "/platform-api/assets/logo.svg";

const emergencyBanner = `<div id="agroai-continuity-banner" role="status" aria-label="AGRO-AI communications update">
  <div class="agroai-continuity-inner">
    <strong>AGRO-AI communications update</strong>
    <span>Our primary Gmail account is temporarily unavailable. AGRO-AI remains fully operational.</span>
    <a href="/contact">Contact AGRO-AI</a>
  </div>
</div>`;

const emergencyBannerStyle = `<style id="agroai-continuity-style">
  #agroai-continuity-banner{position:relative;z-index:1000;background:#102b1d;color:#fff;border-bottom:1px solid rgba(255,255,255,.18);font-family:Arial,sans-serif}
  .agroai-continuity-inner{max-width:1200px;margin:0 auto;padding:11px 22px;display:flex;align-items:center;justify-content:center;gap:12px;font-size:13px;line-height:1.45;text-align:center;flex-wrap:wrap}
  .agroai-continuity-inner strong{font-size:13px;letter-spacing:.01em}
  .agroai-continuity-inner span{color:#e7eee9}
  .agroai-continuity-inner a{display:inline-flex;align-items:center;justify-content:center;padding:6px 11px;border-radius:999px;background:#e6f18d;color:#102b1d;text-decoration:none;font-weight:700;white-space:nowrap}
  .agroai-continuity-inner a:hover,.agroai-continuity-inner a:focus-visible{background:#f2f8bd;outline:2px solid #fff;outline-offset:2px}
  @media(max-width:680px){.agroai-continuity-inner{padding:10px 14px;gap:7px}.agroai-continuity-inner span{width:100%}}
</style>`;

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
  <meta name="description" content="Contact AGRO-AI during the temporary interruption affecting its primary Gmail account.">
  <style>
    :root{color-scheme:light;--ink:#10231b;--muted:#5b6961;--line:#d9e1dc;--paper:#f7f8f4;--green:#173c29;--lime:#e6f18d}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,sans-serif;line-height:1.5}
    a{color:inherit}.shell{min-height:100vh;display:flex;flex-direction:column}.top{display:flex;align-items:center;justify-content:space-between;padding:20px clamp(20px,5vw,64px);border-bottom:1px solid var(--line);background:#fff}
    .brand{display:flex;align-items:center;gap:10px;text-decoration:none;font-weight:800;letter-spacing:.02em}.brand img{width:38px;height:38px;object-fit:contain}.back{font-size:14px;font-weight:700;text-decoration:none}.back:hover{text-decoration:underline}
    main{width:min(1120px,calc(100% - 36px));margin:0 auto;padding:clamp(44px,8vw,90px) 0 70px}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.12em;font-weight:800;color:#466153}
    h1{font-family:Georgia,serif;font-size:clamp(42px,7vw,78px);line-height:.98;letter-spacing:-.045em;max-width:850px;margin:14px 0 22px}.lede{max-width:730px;font-size:clamp(17px,2vw,21px);color:var(--muted);margin:0 0 42px}
    .grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);gap:26px;align-items:start}.card{background:#fff;border:1px solid var(--line);border-radius:22px;padding:clamp(22px,4vw,38px);box-shadow:0 20px 60px rgba(16,35,27,.07)}
    form{display:grid;gap:18px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}label{display:grid;gap:7px;font-size:13px;font-weight:800}.optional{font-weight:400;color:var(--muted)}
    input,textarea{width:100%;border:1px solid #bcc9c1;border-radius:12px;background:#fff;padding:13px 14px;font:inherit;color:var(--ink);outline:none}textarea{min-height:150px;resize:vertical}input:focus,textarea:focus{border-color:var(--green);box-shadow:0 0 0 3px rgba(23,60,41,.12)}
    .honeypot{position:absolute!important;left:-10000px!important;width:1px!important;height:1px!important;overflow:hidden!important}.submit{border:0;border-radius:12px;padding:14px 18px;background:var(--green);color:#fff;font:inherit;font-weight:800;cursor:pointer}.submit:hover{background:#0d2b1e}.submit:disabled{opacity:.6;cursor:wait}
    .status{min-height:24px;font-size:14px;font-weight:700}.status.ok{color:#176b3a}.status.error{color:#9b241c}.side h2{margin:0 0 12px;font-size:20px}.side p{margin:0 0 22px;color:var(--muted)}.action{display:flex;align-items:center;justify-content:center;width:100%;padding:13px 16px;border-radius:12px;border:1px solid var(--line);background:#fff;text-decoration:none;font-weight:800;margin-top:10px}.action.primary{background:var(--lime);border-color:var(--lime)}.note{margin-top:22px;padding-top:20px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
    footer{margin-top:auto;padding:24px clamp(20px,5vw,64px);border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
    @media(max-width:800px){.grid{grid-template-columns:1fr}.two{grid-template-columns:1fr}.top{padding:15px 18px}}
  </style>
</head>
<body>
<div class="shell">
  <header class="top">
    <a class="brand" href="/"><img src="${OFFICIAL_LOGO}" alt="AGRO-AI"><span>AGRO-AI</span></a>
    <a class="back" href="/">Back to AGRO-AI</a>
  </header>
  <main>
    <div class="eyebrow">Business continuity contact</div>
    <h1>AGRO-AI remains operational.</h1>
    <p class="lede">Our primary Gmail account is temporarily unavailable. Customers, partners, investors, media, and collaborators can reach the AGRO-AI team through this secure contact page.</p>
    <div class="grid">
      <section class="card">
        <form id="contact-form" novalidate>
          <div class="two">
            <label>Full name<input name="name" autocomplete="name" maxlength="160" required></label>
            <label>Work email<input name="email" type="email" autocomplete="email" maxlength="240" required></label>
          </div>
          <div class="two">
            <label>Company <span class="optional">optional</span><input name="company" autocomplete="organization" maxlength="160"></label>
            <label>Subject<input name="subject" maxlength="180" required value="AGRO-AI business communication"></label>
          </div>
          <label>Message<textarea name="message" maxlength="4000" required placeholder="Tell us how we can help and include any time-sensitive details."></textarea></label>
          <label class="honeypot" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
          <button class="submit" type="submit">Send to AGRO-AI</button>
          <div id="form-status" class="status" role="status" aria-live="polite"></div>
        </form>
      </section>
      <aside class="card side">
        <h2>Urgent communication</h2>
        <p>For a time-sensitive customer, partner, investor, or operational matter, use the temporary direct channel below or message AGRO-AI on LinkedIn.</p>
        <a class="action primary" href="mailto:${TEMPORARY_DIRECT_EMAIL}?subject=Urgent%20AGRO-AI%20business%20communication">Email the temporary inbox</a>
        <a class="action" href="${LINKEDIN_URL}" rel="noopener noreferrer">Message AGRO-AI on LinkedIn</a>
        <div class="note">Do not send passwords, access codes, API keys, financial credentials, or other secrets through this page.</div>
      </aside>
    </div>
  </main>
  <footer>© AGRO-AI Inc. Communications continuity page.</footer>
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
      priority: 'urgent',
      name: String(data.get('name') || '').trim(),
      email: String(data.get('email') || '').trim(),
      company: String(data.get('company') || '').trim() || null,
      subject: String(data.get('subject') || '').trim(),
      message: String(data.get('message') || '').trim(),
      source_page: 'emergency-business-continuity-contact',
      metadata: { channel: 'website', continuity_incident: 'primary_gmail_unavailable' }
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
      status.innerHTML = 'The secure form could not complete. Use the <a href="mailto:${TEMPORARY_DIRECT_EMAIL}?subject=Urgent%20AGRO-AI%20business%20communication">temporary direct inbox</a>.';
    } finally {
      button.disabled = false;
      button.textContent = 'Send to AGRO-AI';
    }
  });
})();
</script>
</body>
</html>`;
  return new Response(html, { status: 200, headers: securityHeaders("text/html; charset=utf-8") });
}

async function homepageWithContinuityBanner(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
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
  if (!html.includes('id="agroai-continuity-banner"')) {
    html = html.replace("</head>", `${emergencyBannerStyle}</head>`).replace(/<body([^>]*)>/i, `<body$1>${emergencyBanner}`);
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
    if (url.pathname === "/") return homepageWithContinuityBanner(request, env, ctx);
    return (productEntryHandler as ExportedHandler<Env>).fetch!(request, env, ctx);
  },
} satisfies ExportedHandler<Env>;
