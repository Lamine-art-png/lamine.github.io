// Request context and dispatch for AGRO-AI Academy.
import { Router } from "./lib/router.js";
import { HttpError, parseCookies, securityHeaders, redirect, json, readBody, serializeCookie } from "./lib/http.js";
import { loadSession, ensureCsrf, checkCsrf, can } from "./lib/security.js";
import { negotiate, matchLocale, localeInfo, makeTranslator, loadOverrides, formatDate, formatNumber } from "./lib/i18n.js";
import { renderPage, renderError } from "./views/layout.js";
import { registerRoutes } from "./routes.js";

export const BUILD = "2026.10.17";

export function config(env, url) {
  const origin = (env.APP_ORIGIN || url.origin).replace(/\/$/, "");
  const environment = env.ENVIRONMENT || "development";
  return {
    origin,
    host: new URL(origin).host,
    secure: origin.startsWith("https://"),
    environment,
    isProduction: environment === "production",
    portalUrl: env.PORTAL_URL || "https://app.agroai-pilot.com",
    siteUrl: env.SITE_URL || "https://agroai-pilot.com",
    apiUrl: env.API_URL || "https://api.agroai-pilot.com",
    apiDocsUrl: env.API_DOCS_URL || "https://platform.agroai-pilot.com",
    supportEmail: env.SUPPORT_EMAIL || "contact@agroai-pilot.com",
    certSecret: env.CERT_SIGNING_SECRET || (environment === "production" ? null : "development-only-certificate-secret"),
    googleEnabled: Boolean(env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET),
    emailEnabled: Boolean(env.RESEND_API_KEY && env.EMAIL_FROM),
    bootstrapAdmins: String(env.BOOTSTRAP_ADMIN_EMAILS || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
    linkedinOrgId: env.LINKEDIN_ORGANIZATION_ID || "",
    firstClassesDate: env.FIRST_CLASSES_DATE || "2026-10-29",
    exposeDevMail: environment === "development" && env.DEV_MAILBOX === "1",
  };
}

const router = new Router();
registerRoutes(router);
export { router };

const LOCALE_COOKIE = "aca_lang";
const THEME_COOKIE = "aca_theme";

export async function handle(req, env, ctx) {
  const url = new URL(req.url);
  const cfg = config(env, url);
  const setCookies = [];
  const deferred = [];
  const c = {
    req,
    env,
    url,
    cfg,
    cookies: parseCookies(req.headers.get("cookie")),
    params: {},
    setCookie: (v) => setCookies.push(v),
    defer: (p) => {
      const safe = Promise.resolve(p).catch((e) => console.error("deferred task failed", e?.message));
      if (ctx?.waitUntil) ctx.waitUntil(safe);
      else deferred.push(safe);
    },
  };

  let response;
  try {
    const sess = await loadSession(c);
    c.session = sess;
    c.user = sess?.user || null;
    c.roles = sess?.roles || [];
    c.can = (perm) => can(c.roles, perm);

    // Locale: explicit ?lang → cookie → profile → Accept-Language.
    const qLang = matchLocale(url.searchParams.get("lang"));
    if (qLang && qLang !== c.cookies[LOCALE_COOKIE]) {
      c.setCookie(serializeCookie(LOCALE_COOKIE, qLang, { maxAge: 31536000, secure: cfg.secure, httpOnly: false }));
    }
    c.locale = qLang || matchLocale(c.cookies[LOCALE_COOKIE]) || matchLocale(c.user?.locale) || negotiate(req.headers.get("accept-language"));
    c.localeInfo = localeInfo(c.locale);
    c.t = makeTranslator(c.locale, await loadOverrides(env));
    c.fmtDate = (iso, opts) => formatDate(c.locale, iso, opts);
    c.fmtNum = (n, opts) => formatNumber(c.locale, n, opts);
    c.theme = ["light", "dark"].includes(c.cookies[THEME_COOKIE]) ? c.cookies[THEME_COOKIE] : "system";
    c.csrf = ensureCsrf(c);
    c.page = (opts) => renderPage(c, opts);
    c.body = null;
    c.readBody = async () => (c.body ??= await readBody(req));

    const m = router.match(req.method, url.pathname);
    if (!m) throw new HttpError(404, "not_found");
    if (m.methodNotAllowed) throw new HttpError(405, "method_not_allowed");
    c.params = m.params;
    const opts = m.route.opts;

    if (req.method === "POST" && opts.csrf !== false) {
      // Multipart bodies stay unread for the handler; their token travels in the query.
      const multipart = (req.headers.get("content-type") || "").startsWith("multipart/form-data");
      checkCsrf(c, multipart ? { _csrf: url.searchParams.get("_csrf") } : await c.readBody());
    }
    if (opts.auth || opts.perm) {
      if (!c.user) {
        if (url.pathname.startsWith("/api/")) throw new HttpError(401, "auth_required");
        return finalize(redirect(`/login?next=${encodeURIComponent(url.pathname + url.search)}`), c, setCookies, deferred);
      }
      if (opts.perm && !c.can(opts.perm)) throw new HttpError(403, "forbidden");
    }
    response = await m.route.handler(c);
  } catch (err) {
    response = errorResponse(c, err);
  }
  return finalize(response, c, setCookies, deferred);
}

function errorResponse(c, err) {
  const isHttp = err instanceof HttpError;
  const status = isHttp ? err.status : 500;
  if (!isHttp) console.error("unhandled error", err?.stack || err);
  const code = isHttp ? err.code : "server_error";
  const wantsJson = c.url.pathname.startsWith("/api/") || (c.req.headers.get("accept") || "").includes("application/json");
  const headers = {};
  if (status === 429 && err.extra?.retryAfter) headers["Retry-After"] = String(err.extra.retryAfter);
  if (wantsJson) return json({ ok: false, error: code, ...(isHttp ? err.extra : {}) }, status, headers);
  try {
    const res = renderError(c, status, code);
    for (const [k, v] of Object.entries(headers)) res.headers.set(k, v);
    return res;
  } catch (e) {
    console.error("error page failed", e?.message);
    return new Response("AGRO-AI Academy is temporarily unavailable.", { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
}

async function finalize(response, c, setCookies, deferred) {
  const res = new Response(response.body, response);
  for (const ck of setCookies) res.headers.append("Set-Cookie", ck);
  const type = res.headers.get("content-type") || "";
  securityHeaders(res.headers, { isHtml: type.includes("text/html"), secure: c.cfg.secure });
  if (!res.headers.has("Cache-Control")) res.headers.set("Cache-Control", "private, no-store");
  res.headers.set("Vary", "Cookie, Accept-Language");
  if (deferred.length) await Promise.all(deferred);
  return res;
}
