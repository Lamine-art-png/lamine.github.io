// Public website: homepage, programs, paths, instructors, about, FAQ, help,
// contact, legal pages, and SEO endpoints.
import { html, raw } from "../lib/html.js";
import { redirect, json, serializeCookie, HttpError } from "../lib/http.js";
import { newId, nowIso } from "../lib/util.js";
import { rateLimit } from "../lib/security.js";
import { md } from "../lib/markdown.js";
import { LOCALES } from "../lib/i18n.js";
import { icon } from "../views/icons.js";
import { artSvg } from "../views/art.js";
import { courseCard, pageHead, emptyState, alert, csrfField, field, selectField } from "../views/components.js";
import { listCourses, listPrograms, listPaths, localize } from "../services/content.js";
import { validEmail } from "../services/users.js";
import { LEGAL } from "../content/legal.js";
import { qrSvg } from "../lib/qr.js";

export const TOPICS = ["ai-foundations", "data", "machine-learning", "remote-sensing", "precision-agriculture", "irrigation", "crop-monitoring", "risk", "ethics", "computer-vision", "robotics", "agents", "platform", "api"];
const TOPIC_ICONS = {
  "ai-foundations": "sparkles", data: "chart", "machine-learning": "cpu", "remote-sensing": "satellite", "precision-agriculture": "target", irrigation: "droplet",
  "crop-monitoring": "leaf", risk: "alert", ethics: "shield", "computer-vision": "eye", robotics: "settings", agents: "compass", platform: "grid", api: "code",
};

const FAQ_KEYS = ["free", "who", "certificates", "linkedin", "languages", "portal", "offline", "verify", "accreditation", "instructor", "data", "start"];

async function instructors(env) {
  return (await env.DB.prepare("SELECT * FROM instructors WHERE status = 'active' ORDER BY sort_order, name").all()).results;
}

function instructorCard(c, i) {
  return html`<article class="card instructor">
    <div class="instructor-avatar">${i.avatar_url ? html`<img src="${i.avatar_url}" alt="" loading="lazy">` : i.name.charAt(0)}</div>
    <div><h3 class="mb-0">${i.name}</h3><p class="muted small mb-0">${i.title}</p>
      ${i.is_ai_avatar ? html`<p class="mt-1 mb-0"><span class="badge badge-lime">${icon("sparkles", { size: 12 })} ${c.t("instructor.ai_avatar")}</span></p>` : ""}
      <p class="mt-1 small">${i.bio}</p>
      ${i.disclosure ? html`<p class="tiny muted mb-0">${i.disclosure}</p>` : ""}</div>
  </article>`;
}

function faqList(c, keys = FAQ_KEYS) {
  return html`<div class="faq">${keys.map(
    (k) => html`<details id="${k === "certificates" ? "certificates" : `faq-${k}`}"><summary>${c.t(`faq.${k}.q`)}</summary><p>${c.t(`faq.${k}.a`, { languages: LOCALES.length, date: c.fmtDate(c.cfg.firstClassesDate) })}</p></details>`,
  )}</div>`;
}

export async function home(c) {
  const t = c.t;
  const [courses, paths, team] = await Promise.all([listCourses(c.env, c.locale, { limit: 6 }), listPaths(c.env, c.locale), instructors(c.env)]);
  const available = courses.filter((x) => x.isAvailable).length;
  const firstDate = c.fmtDate(c.cfg.firstClassesDate);
  const nativeSample = ["English", "Português", "Español", "Français", "Kiswahili", "العربية", "हिन्दी", "中文", "Bahasa Indonesia", "Türkçe", "Русский", "日本語"];

  const body = html`
<section class="hero">
  <div class="wrap hero-grid">
    <div>
      <p class="eyebrow">${t("home.eyebrow")}</p>
      <h1 class="display">${raw(t("home.title_html"))}</h1>
      <p class="lead">${t("home.lead")}</p>
      <div class="actions">
        <a class="btn btn-primary btn-lg" href="/courses">${t("home.cta_explore")} ${icon("arrow-right", { size: 18, cls: "ic-flip" })}</a>
        <a class="btn btn-secondary btn-lg" href="${c.user ? "/dashboard" : "/register"}">${c.user ? t("nav.dashboard") : t("home.cta_start")}</a>
      </div>
      <ul class="hero-points">
        <li>${icon("check-circle", { size: 18 })} ${t("home.point_free")}</li>
        <li>${icon("award", { size: 18 })} ${t("home.point_certificates")}</li>
        <li>${icon("globe", { size: 18 })} ${t("home.point_languages", { n: LOCALES.length })}</li>
      </ul>
    </div>
    <div class="hero-visual">
      <img src="/art/pivots/green/academy-hero.svg?w=900&h=980" alt="${t("home.hero_alt")}" width="900" height="980" fetchpriority="high">
      <div class="hero-card">
        <div class="row-between">
          <div><strong>${t("home.first_classes")}</strong><span class="tiny">${firstDate}</span></div>
          <span class="badge badge-green">${icon("check", { size: 12 })} ${t("home.free_badge")}</span>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="section-tight section-alt">
  <div class="wrap stat-band">
    <div class="stat"><span class="value">$0</span><span class="label">${t("home.stat_cost")}</span></div>
    <div class="stat"><span class="value">${c.fmtNum(LOCALES.length)}</span><span class="label">${t("home.stat_languages")}</span></div>
    <div class="stat"><span class="value">5</span><span class="label">${t("home.stat_programs")}</span></div>
    <div class="stat"><span class="value">80%</span><span class="label">${t("home.stat_passing")}</span></div>
  </div>
</section>

<section class="section">
  <div class="wrap">
    <div class="section-head"><div><p class="eyebrow">${t("home.featured_eyebrow")}</p><h2 class="h2">${t("home.featured_title")}</h2></div>
      <p>${available ? t("home.featured_lead") : t("home.featured_lead_upcoming", { date: firstDate })}</p></div>
    ${courses.length ? html`<div class="cards cards-3">${courses.slice(0, 6).map((x) => courseCard(c, x))}</div>` : emptyState({ title: t("catalog.empty_title"), body: t("catalog.empty_body") })}
    <div class="actions"><a class="btn btn-secondary" href="/courses">${t("home.view_catalog")} ${icon("arrow-right", { size: 16, cls: "ic-flip" })}</a></div>
  </div>
</section>

<section class="section section-alt">
  <div class="wrap">
    <div class="section-head"><div><p class="eyebrow">${t("home.paths_eyebrow")}</p><h2 class="h2">${t("home.paths_title")}</h2></div><p>${t("home.paths_lead")}</p></div>
    <div class="cards cards-3">${paths.slice(0, 6).map(
      (p) => html`<a class="card card-link feature" href="/paths#${p.slug}"><span class="feature-icon">${icon(roleIcon(p.role), { size: 22 })}</span>
        <h3 class="mb-0">${p.title}</h3><p>${p.summary}</p><span class="tiny muted">${t("paths.course_count", { n: p.course_ids.length })}</span></a>`,
    )}</div>
  </div>
</section>

<section class="section">
  <div class="wrap">
    <div class="section-head"><div><p class="eyebrow">${t("home.topics_eyebrow")}</p><h2 class="h2">${t("home.topics_title")}</h2></div></div>
    <div class="topic-chips">${TOPICS.map((k) => html`<a class="chip" href="/courses?topic=${k}">${icon(TOPIC_ICONS[k], { size: 16 })} ${t(`topic.${k}`)}</a>`)}</div>
  </div>
</section>

<section class="section section-alt">
  <div class="wrap">
    <div class="section-head"><div><p class="eyebrow">${t("home.how_eyebrow")}</p><h2 class="h2">${t("home.how_title")}</h2></div></div>
    <ol class="steps">
      ${["account", "learn", "assess", "credential"].map((k) => html`<li><h3>${t(`home.how.${k}.title`)}</h3><p>${t(`home.how.${k}.body`)}</p></li>`)}
    </ol>
  </div>
</section>

<section class="section">
  <div class="wrap cert-showcase">
    <div>
      <p class="eyebrow">${t("home.cert_eyebrow")}</p>
      <h2 class="h2">${t("home.cert_title")}</h2>
      <p class="lead">${t("home.cert_lead")}</p>
      <ul class="check-list">
        ${["unique", "qr", "linkedin", "pdf", "revocation"].map((k) => html`<li>${icon("check-circle", { size: 18 })} <span>${t(`home.cert.${k}`)}</span></li>`)}
      </ul>
      <p class="small muted mt-3">${t("home.cert_disclaimer")}</p>
      <div class="actions"><a class="btn btn-secondary" href="/verify">${icon("shield", { size: 16 })} ${t("nav.verify")}</a></div>
    </div>
    <div aria-hidden="true">${sampleCertificate(c)}</div>
  </div>
</section>

${team.length
  ? html`<section class="section section-alt"><div class="wrap">
    <div class="section-head"><div><p class="eyebrow">${t("home.instructors_eyebrow")}</p><h2 class="h2">${t("home.instructors_title")}</h2></div><p>${t("home.instructors_lead")}</p></div>
    <div class="cards cards-3">${team.slice(0, 3).map((i) => instructorCard(c, i))}</div>
    <div class="actions"><a class="btn btn-quiet" href="/instructors">${t("home.meet_instructors")} ${icon("arrow-right", { size: 16, cls: "ic-flip" })}</a></div></div></section>`
  : ""}

<section class="section">
  <div class="wrap">
    <div class="section-head"><div><p class="eyebrow">${t("home.benefits_eyebrow")}</p><h2 class="h2">${t("home.benefits_title")}</h2></div></div>
    <div class="cards cards-4">
      ${[["target", "practical"], ["award", "credential"], ["clock", "pace"], ["wifi", "bandwidth"]].map(
        ([ic, k]) => html`<div class="feature"><span class="feature-icon">${icon(ic, { size: 22 })}</span><h3>${t(`home.benefit.${k}.title`)}</h3><p>${t(`home.benefit.${k}.body`)}</p></div>`,
      )}
    </div>
  </div>
</section>

<section class="section section-alt">
  <div class="wrap cert-showcase">
    <div>
      <p class="eyebrow">${t("home.global_eyebrow")}</p>
      <h2 class="h2">${t("home.global_title", { n: LOCALES.length })}</h2>
      <p class="lead">${t("home.global_lead")}</p>
      <p class="small muted">${t("home.global_note")}</p>
    </div>
    <div class="topic-chips">${nativeSample.map((n) => html`<span class="chip" lang="">${n}</span>`)}<span class="chip">+${LOCALES.length - nativeSample.length}</span></div>
  </div>
</section>

<section class="section">
  <div class="wrap narrow">
    <p class="eyebrow">${t("home.faq_eyebrow")}</p><h2 class="h2">${t("home.faq_title")}</h2>
    ${faqList(c, ["free", "who", "certificates", "languages", "portal", "accreditation"])}
    <div class="actions"><a class="btn btn-quiet" href="/faq">${t("home.all_questions")} ${icon("arrow-right", { size: 16, cls: "ic-flip" })}</a></div>
  </div>
</section>

<section class="section-tight"><div class="wrap">
  <div class="cta-band"><div><h2>${t("home.cta_title")}</h2><p>${t("home.cta_lead")}</p></div>
    <a class="btn btn-primary btn-lg" href="${c.user ? "/courses" : "/register"}">${c.user ? t("home.cta_explore") : t("home.cta_start")} ${icon("arrow-right", { size: 18, cls: "ic-flip" })}</a></div>
</div></section>`;

  return c.page({
    body,
    canonical: "/",
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "EducationalOrganization",
      name: "AGRO-AI Academy",
      url: c.cfg.origin,
      logo: `${c.cfg.origin}/static/img/mark-512.png`,
      description: t("meta.default_description"),
      parentOrganization: { "@type": "Organization", name: "AGRO-AI Inc.", url: c.cfg.siteUrl },
      address: { "@type": "PostalAddress", addressLocality: "San Francisco", addressRegion: "CA", addressCountry: "US" },
    },
  });
}

function roleIcon(role) {
  return { grower: "sprout", agronomist: "leaf", farm_manager: "chart", operator: "settings", student: "graduation", researcher: "compass", developer: "code", advisor: "users" }[role] || "compass";
}

export function sampleCertificate(c) {
  return html`<div class="certificate" role="img" aria-label="${c.t("home.cert_sample")}">
    <div class="c-top"><div class="c-brand"><img src="/static/img/mark-64.png" alt=""><span>AGRO-AI <span>Academy</span></span></div><span class="c-id">AGA-SAMP-LE00-0000</span></div>
    <div class="c-center">
      <div class="c-label">${c.t("cert.title_label")}</div>
      <div class="c-name">${c.t("home.cert_sample_name")}</div>
      <p class="c-text">${c.t("cert.completed_text")}</p>
      <div class="c-course">${c.t("home.cert_sample_course")}</div>
    </div>
    <div class="c-foot"><div><span>${c.t("cert.issued")}</span><strong>${c.fmtDate(c.cfg.firstClassesDate)}</strong></div>
      <div><span>${c.t("cert.issuer")}</span><strong>AGRO-AI Academy</strong></div>
      <div class="c-qr">${raw(qrSvg(`${c.cfg.origin}/verify`, { title: c.t("cert.qr_label") }))}</div></div>
  </div>`;
}


export async function programs(c) {
  const t = c.t;
  const [list, courses, planned] = await Promise.all([
    listPrograms(c.env, c.locale),
    listCourses(c.env, c.locale),
    c.env.DB.prepare("SELECT id, program_id, title, level FROM courses WHERE status = 'draft' ORDER BY sort_order").all(),
  ]);
  await localize(c.env, "course", planned.results, ["title"], c.locale);
  const body = html`${pageHead({ eyebrow: t("programs.eyebrow"), title: t("programs.title"), lead: t("programs.lead") })}
  <section class="section-tight"><div class="wrap">
    ${list.length
      ? list.map((p) => {
          const pc = courses.filter((x) => x.program_id === p.id);
          return html`<section class="mt-4" id="${p.slug}" aria-labelledby="h-${p.slug}">
            <div class="section-head"><div><p class="eyebrow">${t("program.label", { code: p.code || "" })}</p><h2 class="h2" id="h-${p.slug}">${p.title}</h2></div>
              <p>${p.summary}</p></div>
            ${pc.length ? html`<div class="cards cards-3">${pc.map((x) => courseCard(c, x))}</div>` : ""}
            ${(() => {
              const pl = planned.results.filter((x) => x.program_id === p.id);
              return pl.length
                ? html`<div class="panel mt-2"><p class="small mb-1"><strong>${t("programs.planned")}</strong> <span class="muted">· ${t("programs.planned_note")}</span></p>
                    <ul class="planned-list">${pl.map((x) => html`<li>${icon("clock", { size: 14 })} ${x.title} <span class="tiny muted">· ${t(`level.${x.level}`)}</span></li>`)}</ul></div>`
                : "";
            })()}
          </section>`;
        })
      : emptyState({ title: t("programs.empty") })}
    <p class="small muted mt-4">${t("programs.roadmap_note")}</p>
  </div></section>`;
  return c.page({ title: t("programs.title"), description: t("programs.lead"), body, active: "programs" });
}

export async function paths(c) {
  const t = c.t;
  const [list, courses] = await Promise.all([listPaths(c.env, c.locale), listCourses(c.env, c.locale)]);
  const byId = new Map(courses.map((x) => [x.id, x]));
  const body = html`${pageHead({ eyebrow: t("paths.eyebrow"), title: t("paths.title"), lead: t("paths.lead") })}
  <section class="section-tight"><div class="wrap">
    ${list.length
      ? list.map((p) => {
          const pc = p.course_ids.map((id) => byId.get(id)).filter(Boolean);
          return html`<section class="mt-4" id="${p.slug}" aria-labelledby="h-${p.slug}">
            <div class="row mb-2"><span class="feature-icon">${icon(roleIcon(p.role), { size: 22 })}</span><div><h2 class="h2 mb-0" id="h-${p.slug}">${p.title}</h2><p class="muted mb-0">${p.summary}</p></div></div>
            ${pc.length ? html`<div class="cards cards-3">${pc.map((x) => courseCard(c, x))}</div>` : html`<p class="muted">${t("programs.in_preparation")}</p>`}
          </section>`;
        })
      : emptyState({ title: t("paths.empty") })}
  </div></section>`;
  return c.page({ title: t("paths.title"), description: t("paths.lead"), body, active: "paths" });
}

export async function instructorsPage(c) {
  const t = c.t;
  const team = await instructors(c.env);
  const body = html`${pageHead({ eyebrow: t("instructors.eyebrow"), title: t("instructors.title"), lead: t("instructors.lead") })}
  <section class="section-tight"><div class="wrap">
    ${team.length ? html`<div class="cards cards-3">${team.map((i) => instructorCard(c, i))}</div>` : emptyState({ title: t("instructors.empty") })}
    <div class="panel mt-4">${icon("info", { size: 18 })} <strong>${t("instructors.philosophy_title")}</strong><p class="mt-1 mb-0">${t("instructors.philosophy_body")}</p></div>
  </div></section>`;
  return c.page({ title: t("instructors.title"), description: t("instructors.lead"), body });
}

export async function about(c) {
  const t = c.t;
  const body = html`${pageHead({ eyebrow: t("about.eyebrow"), title: t("about.title"), lead: t("about.lead") })}
  <section class="section-tight"><div class="wrap narrow prose">
    <h2>${t("about.mission_title")}</h2><p>${t("about.mission_body")}</p>
    <h2>${t("about.why_title")}</h2><p>${t("about.why_body")}</p>
    <h2>${t("about.approach_title")}</h2>
    <ul>${["practical", "honest", "accessible", "verifiable"].map((k) => html`<li><strong>${t(`about.approach.${k}.title`)}</strong> — ${t(`about.approach.${k}.body`)}</li>`)}</ul>
    <h2>${t("about.ecosystem_title")}</h2><p>${t("about.ecosystem_body")}</p>
    <p><a href="${c.cfg.siteUrl}">${t("footer.agroai_site")}</a> · <a href="${c.cfg.portalUrl}">${t("footer.portal")}</a> · <a href="${c.cfg.apiDocsUrl}">${t("footer.platform_api")}</a></p>
    <h2>${t("about.credentials_title")}</h2><p>${t("about.credentials_body")}</p>
  </div></section>`;
  return c.page({ title: t("about.title"), description: t("about.lead"), body, active: "about" });
}

export async function faq(c) {
  const t = c.t;
  const body = html`${pageHead({ eyebrow: t("faq.eyebrow"), title: t("faq.title") })}
  <section class="section-tight"><div class="wrap narrow">${faqList(c)}</div></section>`;
  return c.page({
    title: t("faq.title"),
    body,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: FAQ_KEYS.map((k) => ({
        "@type": "Question",
        name: t(`faq.${k}.q`),
        acceptedAnswer: { "@type": "Answer", text: t(`faq.${k}.a`, { languages: LOCALES.length, date: c.fmtDate(c.cfg.firstClassesDate) }) },
      })),
    },
  });
}

export async function help(c) {
  const t = c.t;
  const topics = ["account", "learning", "exams", "certificates", "language", "access"];
  const body = html`${pageHead({ eyebrow: t("help.eyebrow"), title: t("help.title"), lead: t("help.lead") })}
  <section class="section-tight"><div class="wrap">
    <div class="cards cards-3">${topics.map((k) => html`<article class="card"><h3>${t(`help.${k}.title`)}</h3><p class="muted mb-0">${t(`help.${k}.body`)}</p></article>`)}</div>
    <div class="cta-band mt-4"><div><h2>${t("help.contact_title")}</h2><p>${t("help.contact_lead")}</p></div><a class="btn btn-primary" href="/contact">${t("nav.contact")}</a></div>
  </div></section>`;
  return c.page({ title: t("help.title"), description: t("help.lead"), body });
}

const CONTACT_TOPICS = ["account", "course", "certificate", "accessibility", "partnership", "privacy", "other"];

export async function contact(c, { errors = {}, values = {}, sent = false } = {}) {
  const t = c.t;
  const body = html`${pageHead({ eyebrow: t("contact.eyebrow"), title: t("contact.title"), lead: t("contact.lead") })}
  <section class="section-tight"><div class="wrap narrow">
    ${sent ? alert("success", t("contact.sent")) : ""}
    <form class="form-card" method="post" action="/contact" novalidate>
      ${csrfField(c)}
      <div class="grid-2">
        ${field(c, { name: "name", label: t("form.name"), value: values.name ?? c.user?.display_name, required: true, autocomplete: "name", error: errors.name && t(errors.name) })}
        ${field(c, { name: "email", label: t("form.email"), type: "email", value: values.email ?? c.user?.email, required: true, autocomplete: "email", error: errors.email && t(errors.email) })}
      </div>
      ${selectField(c, { name: "topic", label: t("contact.topic"), required: true, value: values.topic, options: CONTACT_TOPICS.map((k) => [k, t(`contact.topic.${k}`)]) })}
      <div class="field"><label for="f-message">${t("contact.message")}</label><textarea id="f-message" name="message" required maxlength="5000" ${errors.message ? raw('aria-invalid="true"') : ""}>${values.message || ""}</textarea>
        ${errors.message ? html`<p class="field-error">${t(errors.message)}</p>` : ""}</div>
      <div class="sr-only" aria-hidden="true"><label for="f-website">Website</label><input id="f-website" name="website" tabindex="-1" autocomplete="off"></div>
      <button class="btn btn-primary" type="submit">${t("contact.send")}</button>
      <p class="small muted mt-2">${t("contact.direct", { email: c.cfg.supportEmail })}</p>
    </form>
  </div></section>`;
  return c.page({ title: t("contact.title"), description: t("contact.lead"), body, status: Object.keys(errors).length ? 422 : 200 });
}

export async function contactSubmit(c) {
  const b = await c.readBody();
  if (b.website) return redirect("/contact?sent=1");
  await rateLimit(c, "contact", { limit: 5, windowSeconds: 3600 });
  const values = { name: String(b.name || "").trim().slice(0, 120), email: String(b.email || "").trim().toLowerCase(), topic: CONTACT_TOPICS.includes(b.topic) ? b.topic : "other", message: String(b.message || "").trim().slice(0, 5000) };
  const errors = {};
  if (values.name.length < 2) errors.name = "form.error.name";
  if (!validEmail(values.email)) errors.email = "form.error.email";
  if (values.message.length < 10) errors.message = "contact.error.message";
  if (Object.keys(errors).length) return contact(c, { errors, values });
  const now = nowIso();
  await c.env.DB.prepare("INSERT INTO support_requests (id, user_id, name, email, topic, message, status, created_at, updated_at) VALUES (?,?,?,?,?,?, 'open', ?, ?)")
    .bind(newId("sup_"), c.user?.id ?? null, values.name, values.email, values.topic, values.message, now, now)
    .run();
  return redirect("/contact?sent=1");
}

export async function legal(c) {
  const doc = LEGAL[c.params.doc];
  if (!doc) throw new HttpError(404, "not_found");
  const t = c.t;
  const body = html`${pageHead({ eyebrow: t("legal.eyebrow"), title: doc.title, lead: t("legal.updated", { date: c.fmtDate(doc.updated) }) })}
  <section class="section-tight"><div class="wrap narrow">
    ${c.locale !== "en" ? alert("info", t("legal.english_governs")) : ""}
    <div class="prose" lang="en">${md(doc.body)}</div>
  </div></section>`;
  return c.page({ title: doc.title, description: doc.summary, body });
}

export async function setTheme(c) {
  const b = await c.readBody();
  const theme = ["light", "dark", "system"].includes(b.theme) ? b.theme : "system";
  c.setCookie(serializeCookie("aca_theme", theme, { maxAge: 31536000, secure: c.cfg.secure, httpOnly: false }));
  if (c.user) await c.env.DB.prepare("UPDATE user_preferences SET theme = ?, updated_at = ? WHERE user_id = ?").bind(theme, nowIso(), c.user.id).run();
  if ((c.req.headers.get("accept") || "").includes("application/json")) return json({ ok: true, theme });
  const next = typeof b.next === "string" && b.next.startsWith("/") && !b.next.startsWith("//") ? b.next : "/";
  return redirect(next);
}

export async function art(c) {
  const [motif, palette, file] = [c.params.motif, c.params.palette, c.params.file];
  if (!/^[a-z]+$/.test(motif) || !/^[a-z]+$/.test(palette) || !/^[\w.-]+\.svg$/.test(file)) throw new HttpError(404, "not_found");
  const w = Math.min(1600, Math.max(200, Number(c.url.searchParams.get("w")) || 800));
  const h = Math.min(1600, Math.max(200, Number(c.url.searchParams.get("h")) || 450));
  return new Response(artSvg(motif, file.replace(/\.svg$/, ""), palette, w, h), {
    headers: { "Content-Type": "image/svg+xml; charset=utf-8", "Cache-Control": "public, max-age=604800", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'" },
  });
}

export async function sitemap(c) {
  const courses = await listCourses(c.env, "en");
  const programsList = await listPrograms(c.env, "en");
  const staticPaths = ["/", "/courses", "/paths", "/programs", "/instructors", "/about", "/faq", "/help", "/contact", "/verify", "/terms", "/privacy", "/accessibility"];
  const urls = [
    ...staticPaths.map((p) => ({ loc: c.cfg.origin + p })),
    ...courses.map((x) => ({ loc: `${c.cfg.origin}/courses/${x.slug}`, lastmod: x.updated_at })),
  ];
  void programsList;
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${urls
  .map(
    (u) => `<url><loc>${u.loc}</loc>${u.lastmod ? `<lastmod>${u.lastmod.slice(0, 10)}</lastmod>` : ""}${LOCALES.map((l) => `<xhtml:link rel="alternate" hreflang="${l.code}" href="${u.loc}?lang=${l.code}"/>`).join("")}</url>`,
  )
  .join("\n")}
</urlset>`;
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8", "Cache-Control": "public, max-age=3600" } });
}

export async function robots(c) {
  const body = c.cfg.isProduction
    ? `User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /dashboard\nDisallow: /account\nDisallow: /learn\nDisallow: /attempts\nDisallow: /api/\n\nSitemap: ${c.cfg.origin}/sitemap.xml\n`
    : "User-agent: *\nDisallow: /\n";
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=3600" } });
}

export async function health(c) {
  let db = "ok";
  let schema = null;
  try {
    schema = (await c.env.DB.prepare("SELECT COUNT(*) AS n FROM courses").first())?.n ?? 0;
  } catch {
    db = "error";
  }
  // Deployed environments are unhealthy without certificate signing, so the
  // post-deploy smoke test fails instead of serving unverifiable credentials.
  const deployed = c.cfg.environment === "production" || c.cfg.environment === "staging";
  const signingOk = c.cfg.certSigning === "configured" || !deployed;
  const ok = db === "ok" && signingOk;
  return json(
    {
      ok,
      service: "agroai-academy",
      environment: c.cfg.environment,
      database: db,
      courses: schema,
      email: c.cfg.emailEnabled ? "configured" : "not_configured",
      certificate_signing: c.cfg.certSigning,
      google_sign_in: c.cfg.googleEnabled ? "configured" : "not_configured",
      languages: LOCALES.length,
    },
    ok ? 200 : 503,
  );
}
