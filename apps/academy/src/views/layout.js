// Page shell: document head (SEO, social, hreflang), header, footer.
import { html, raw, jsonScript } from "../lib/html.js";
import { LOCALES, interfaceStatus } from "../lib/i18n.js";
import { icon } from "./icons.js";
import { BUILD } from "../app.js";

export const asset = (p) => `/static/${p}?v=${BUILD}`;

function langSwitcher(c) {
  const here = c.url.pathname + (c.url.search ? c.url.search.replace(/([?&])lang=[^&]*&?/, "$1").replace(/[?&]$/, "") : "");
  return html`<form class="lang" method="get" action="${c.url.pathname}" data-autosubmit>
    ${[...c.url.searchParams].filter(([k]) => k !== "lang").map(([k, v]) => html`<input type="hidden" name="${k}" value="${v}">`)}
    <label class="lang-label">${icon("globe", { size: 16 })}<span class="sr-only">${c.t("nav.language")}</span>
      <select name="lang" aria-label="${c.t("nav.language")}" data-current="${here}">
        ${[
          ["translated", LOCALES.filter((l) => interfaceStatus(l.code) !== "fallback")],
          ["fallback", LOCALES.filter((l) => interfaceStatus(l.code) === "fallback")],
        ].map(
          ([group, list]) => html`<optgroup label="${c.t(`nav.lang_group_${group}`)}">${list.map(
            (l) => html`<option value="${l.code}" lang="${l.code}" dir="${l.dir}" ${l.code === c.locale ? raw("selected") : ""}>${l.nativeName}</option>`,
          )}</optgroup>`,
        )}
      </select></label>
    <noscript><button class="btn btn-sm btn-quiet" type="submit">${c.t("action.apply")}</button></noscript>
  </form>`;
}

/** Says plainly when the interface is a machine draft or not translated yet. */
function languageNotice(c) {
  const status = interfaceStatus(c.locale);
  if (status !== "machine" && status !== "fallback") return "";
  return html`<div class="lang-notice no-print" role="note"><div class="wrap">${icon("globe", { size: 15 })}
    <span>${c.t(`lang.notice_${status}`, { language: c.localeInfo.nativeName })}</span> <a href="/languages">${c.t("lang.notice_link")}</a></div></div>`;
}

function themeToggle(c) {
  const next = c.theme === "dark" ? "light" : "dark";
  return html`<form method="post" action="/preferences/theme" class="theme-form">
    <input type="hidden" name="_csrf" value="${c.csrf}"><input type="hidden" name="theme" value="${next}">
    <input type="hidden" name="next" value="${c.url.pathname + c.url.search}">
    <button class="icon-btn" type="submit" data-theme-toggle aria-label="${c.t("nav.toggle_theme")}" title="${c.t("nav.toggle_theme")}">
      <span class="when-light">${icon("moon", { size: 18 })}</span><span class="when-dark">${icon("sun", { size: 18 })}</span>
    </button></form>`;
}

function header(c, active) {
  const t = c.t;
  const nav = [
    ["/courses", t("nav.courses"), "courses"],
    ["/paths", t("nav.paths"), "paths"],
    ["/programs", t("nav.programs"), "programs"],
    ["/verify", t("nav.verify_short"), "verify"],
    ["/about", t("nav.about"), "about"],
  ];
  const user = c.user;
  return html`<header class="site-header">
  <div class="wrap header-row">
    <a class="brand" href="/" aria-label="${t("brand.home_label")}">
      <img src="${asset("img/mark-64.png")}" width="32" height="32" alt="" decoding="async">
      <span class="brand-text"><span class="brand-agro">AGRO-AI</span> <span class="brand-academy">Academy</span></span>
    </a>
    <nav class="primary-nav" aria-label="${t("nav.primary")}">
      <ul>${nav.map(([href, label, key]) => html`<li><a href="${href}" ${active === key ? raw('aria-current="page"') : ""}>${label}</a></li>`)}</ul>
    </nav>
    <div class="header-tools">
      ${langSwitcher(c)}
      ${themeToggle(c)}
      ${user
        ? html`<details class="account-menu">
            <summary class="avatar-btn" aria-label="${t("nav.account_menu")}"><span class="avatar" aria-hidden="true">${(user.display_name || "?").trim().charAt(0).toUpperCase()}</span></summary>
            <div class="menu-panel" role="menu">
              <p class="menu-name">${user.display_name}<span>${user.email}</span></p>
              <a role="menuitem" href="/dashboard">${icon("home", { size: 16 })} ${t("nav.dashboard")}</a>
              <a role="menuitem" href="/dashboard/certificates">${icon("award", { size: 16 })} ${t("nav.my_certificates")}</a>
              <a role="menuitem" href="/account">${icon("settings", { size: 16 })} ${t("nav.account")}</a>
              ${c.can("admin.access") ? html`<a role="menuitem" href="/admin">${icon("shield", { size: 16 })} ${t("nav.admin")}</a>` : ""}
              <form method="post" action="/logout"><input type="hidden" name="_csrf" value="${c.csrf}">
                <button role="menuitem" type="submit">${icon("logout", { size: 16 })} ${t("nav.sign_out")}</button></form>
            </div></details>`
        : html`<a class="btn btn-quiet btn-sm hide-sm" href="/login">${t("nav.sign_in")}</a>
               <a class="btn btn-primary btn-sm btn-start" href="/register">${t("nav.start_learning")}</a>`}
      <details class="mobile-nav">
        <summary class="icon-btn" aria-label="${t("nav.menu")}">${icon("menu", { size: 20 })}</summary>
        <nav class="mobile-panel" aria-label="${t("nav.primary")}">
          ${nav.map(([href, label]) => html`<a href="${href}">${label}</a>`)}
          ${user ? html`<a href="/dashboard">${t("nav.dashboard")}</a>` : html`<a href="/login">${t("nav.sign_in")}</a><a href="/register">${t("nav.start_learning")}</a>`}
        </nav>
      </details>
    </div>
  </div>
  ${user && !user.email_verified_at && !c.hideVerifyBanner
    ? html`<div class="notice-bar" role="status"><div class="wrap">${icon("mail", { size: 16 })} ${t("auth.verify_banner")}
        <form method="post" action="/verify-email/resend" class="inline"><input type="hidden" name="_csrf" value="${c.csrf}">
        <button class="link-btn" type="submit">${t("auth.resend_verification")}</button></form></div></div>`
    : ""}
</header>`;
}

function footer(c) {
  const t = c.t;
  const year = new Date().getUTCFullYear();
  return html`<footer class="site-footer">
  <div class="wrap footer-grid">
    <div class="footer-brand">
      <a class="brand" href="/"><img src="${asset("img/mark-64.png")}" width="32" height="32" alt="" loading="lazy">
        <span class="brand-text"><span class="brand-agro">AGRO-AI</span> <span class="brand-academy">Academy</span></span></a>
      <p>${t("footer.tagline")}</p>
      <p class="free-badge">${icon("check-circle", { size: 16 })} ${t("footer.free_forever")}</p>
    </div>
    <nav aria-label="${t("footer.academy")}"><h2>${t("footer.academy")}</h2>
      <a href="/courses">${t("nav.courses")}</a><a href="/paths">${t("nav.paths")}</a><a href="/programs">${t("nav.programs")}</a>
      <a href="/instructors">${t("nav.instructors")}</a><a href="/about">${t("nav.about")}</a></nav>
    <nav aria-label="${t("footer.credentials")}"><h2>${t("footer.credentials")}</h2>
      <a href="/verify">${t("nav.verify")}</a><a href="/faq#certificates">${t("footer.how_certificates")}</a>
      <a href="/faq">${t("nav.faq")}</a></nav>
    <nav aria-label="${t("footer.support")}"><h2>${t("footer.support")}</h2>
      <a href="/help">${t("nav.help")}</a><a href="/contact">${t("nav.contact")}</a><a href="/accessibility">${t("nav.accessibility")}</a>
      <a href="/languages">${t("nav.languages")}</a>
      <a href="/terms">${t("nav.terms")}</a><a href="/privacy">${t("nav.privacy")}</a></nav>
    <nav aria-label="${t("footer.ecosystem")}"><h2>${t("footer.ecosystem")}</h2>
      <a href="${c.cfg.siteUrl}" rel="noopener">${t("footer.agroai_site")} ${icon("external", { size: 13 })}</a>
      <a href="${c.cfg.portalUrl}" rel="noopener">${t("footer.portal")} ${icon("external", { size: 13 })}</a>
      <a href="${c.cfg.apiDocsUrl}" rel="noopener">${t("footer.platform_api")} ${icon("external", { size: 13 })}</a>
      <a href="${c.cfg.siteUrl}/news/" rel="noopener">${t("footer.newsroom")} ${icon("external", { size: 13 })}</a></nav>
  </div>
  <div class="wrap footer-base">
    <p>© ${year} AGRO-AI Inc. · San Francisco, California</p>
    <p>${t("footer.not_accredited")}</p>
  </div>
</footer>`;
}

export function renderPage(c, opts) {
  const { title, description = c.t("meta.default_description"), body, active, status = 200, noindex = false, ogImage, ogType = "website", jsonLd, bodyClass = "", bare = false } = opts;
  const t = c.t;
  const fullTitle = title ? `${title} · AGRO-AI Academy` : `AGRO-AI Academy — ${t("meta.tagline")}`;
  const canonicalPath = opts.canonical ?? c.url.pathname;
  const canonical = c.cfg.origin + canonicalPath;
  const og = ogImage || c.cfg.origin + asset("img/og-academy.png");
  const indexable = !noindex && status === 200 && !c.user;
  const doc = html`<!doctype html>
<html lang="${c.locale}" dir="${c.localeInfo.dir}" data-theme="${c.theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>${fullTitle}</title>
<meta name="description" content="${description}">
<link rel="canonical" href="${canonical}">
${indexable ? html`<link rel="alternate" hreflang="x-default" href="${canonical}">
${LOCALES.map((l) => html`<link rel="alternate" hreflang="${l.code}" href="${canonical}?lang=${l.code}">`)}` : html`<meta name="robots" content="noindex, nofollow">`}
<meta property="og:site_name" content="AGRO-AI Academy">
<meta property="og:type" content="${ogType}">
<meta property="og:title" content="${title || "AGRO-AI Academy"}">
<meta property="og:description" content="${description}">
<meta property="og:url" content="${canonical}">
<meta property="og:image" content="${og}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:locale" content="${c.locale.replace("-", "_")}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#1F3D27" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0C1510" media="(prefers-color-scheme: dark)">
<meta name="csrf-token" content="${c.csrf}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="${asset("img/favicon-32.png")}">
<link rel="apple-touch-icon" href="${asset("img/apple-touch-icon.png")}">
<link rel="manifest" href="/site.webmanifest">
<link rel="stylesheet" href="${asset("css/academy.css")}">
<script src="${asset("js/academy.js")}" defer></script>
${jsonLd ? html`<script type="application/ld+json">${jsonScript(jsonLd)}</script>` : ""}
</head>
<body class="${bodyClass}">
<a class="skip-link" href="#main">${t("a11y.skip_to_content")}</a>
${bare ? "" : header(c, active)}
${languageNotice(c)}
<main id="main" tabindex="-1">${body}</main>
${bare ? "" : footer(c)}
<div class="toast" role="status" aria-live="polite" data-toast hidden></div>
<div class="offline-pill" role="status" data-offline hidden>${icon("wifi", { size: 14 })} ${t("offline.notice")}</div>
</body>
</html>`;
  return new Response(doc.toString(), { status, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

const ERROR_KEYS = { 400: "bad_request", 401: "auth_required", 403: "forbidden", 404: "not_found", 405: "not_found", 413: "too_large", 429: "rate_limited" };

export function renderError(c, status, code) {
  const t = c.t || ((k) => k);
  const key = ERROR_KEYS[status] || "server_error";
  const detail = code === "csrf_failed" || code === "bad_origin" ? t("error.csrf") : t(`error.${key}.body`);
  return renderPage(c, {
    title: t(`error.${key}.title`),
    status,
    noindex: true,
    body: html`<section class="wrap narrow error-page">
      <p class="eyebrow">${t("error.code", { status })}</p>
      <h1 class="display-sm">${t(`error.${key}.title`)}</h1>
      <p class="lead">${detail}</p>
      <div class="actions"><a class="btn btn-primary" href="/">${t("error.go_home")}</a><a class="btn btn-quiet" href="/courses">${t("nav.courses")}</a></div>
    </section>`,
  });
}
