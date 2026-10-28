// Reusable view components.
import { html, raw } from "../lib/html.js";
import { icon } from "./icons.js";
import { courseThumb } from "./art.js";
import { formatDuration } from "../lib/util.js";
import { localeInfo } from "../lib/i18n.js";

export function courseStatusBadge(c, course) {
  if (course.status === "published") return "";
  if (course.isUpcoming) {
    const date = course.status === "review" ? null : (course.scheduled_at || course.planned_release_date);
    return html`<span class="badge badge-lime">${icon("clock", { size: 13 })} ${date ? c.t("course.opens_on", { date: c.fmtDate(date, { dateStyle: "medium" }) }) : c.t("course.coming_soon")}</span>`;
  }
  if (course.status === "draft") return html`<span class="badge badge-warn">${c.t("status.draft")}</span>`;
  if (course.status === "archived") return html`<span class="badge">${c.t("status.archived")}</span>`;
  return "";
}

export function levelLabel(c, level) {
  return c.t(`level.${level}`);
}

export function courseCard(c, course, { progress = null } = {}) {
  const thumb = courseThumb(course);
  return html`<a class="card card-link course-card" href="/courses/${course.slug}">
    <div class="thumb"><img src="${thumb}" alt="" loading="lazy" decoding="async" width="800" height="450">${courseStatusBadge(c, course)}</div>
    <div class="body">
      ${course.program_title ? html`<span class="program-label">${course.program_code ? `${c.t("program.label", { code: course.program_code })} · ` : ""}${course.program_title}</span>` : ""}
      <h3${contentLang(c, course, "title")}>${course.title}</h3>
      <p${contentLang(c, course, "subtitle")}>${course.subtitle || ""}</p>
      ${progress != null
        ? html`<div class="mt-1"><div class="progress" role="progressbar" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100" aria-label="${c.t("progress.label")}"><span class="pct-${Math.round(progress)}"></span></div>
           <span class="tiny muted">${c.t("progress.percent_complete", { pct: progress })}</span></div>`
        : ""}
      <div class="meta">
        <span>${icon("layers", { size: 14 })} ${levelLabel(c, course.level)}</span>
        ${course.duration_minutes ? html`<span>${icon("clock", { size: 14 })} ${formatDuration(course.duration_minutes, c.t)}</span>` : ""}
        ${course.certificate_enabled ? html`<span>${icon("award", { size: 14 })} ${c.t("course.free_certificate")}</span>` : ""}
      </div>
    </div>
  </a>`;
}

export function breadcrumbs(items) {
  return html`<nav aria-label="Breadcrumb"><ol class="breadcrumbs">
    ${items.map(([label, href], i) => html`<li>${href && i < items.length - 1 ? html`<a href="${href}">${label}</a>` : html`<span aria-current="page">${label}</span>`}</li>`)}
  </ol></nav>`;
}

export function pageHead({ eyebrow, title, lead, crumbs, extra }) {
  return html`<section class="page-head"><div class="wrap">
    ${crumbs ? breadcrumbs(crumbs) : ""}
    ${eyebrow ? html`<p class="eyebrow">${eyebrow}</p>` : ""}
    <h1 class="display-sm">${title}</h1>
    ${lead ? html`<p class="lead">${lead}</p>` : ""}
    ${extra || ""}
  </div></section>`;
}

export function progressBar(c, pct, { large = false } = {}) {
  const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
  return html`<div class="progress ${large ? "progress-lg" : ""}" role="progressbar" aria-valuenow="${p}" aria-valuemin="0" aria-valuemax="100" aria-label="${c.t("progress.label")}"><span class="pct-${p}"></span></div>`;
}

export function ring(c, pct, label) {
  const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
  return html`<div class="ring pct-${p}" role="img" aria-label="${label}: ${p}%"><div><span><strong>${p}%</strong></span></div></div>`;
}

export function emptyState({ iconName = "sprout", title, body, action }) {
  return html`<div class="empty">${icon(iconName, { size: 32 })}<h3>${title}</h3>${body ? html`<p>${body}</p>` : ""}${action || ""}</div>`;
}

export function alert(kind, content) {
  const ic = { info: "info", success: "check-circle", warn: "alert", error: "alert" }[kind];
  return html`<div class="alert alert-${kind}" role="${kind === "error" ? "alert" : "status"}">${icon(ic, { size: 18 })}<div>${content}</div></div>`;
}

export function csrfField(c) {
  return html`<input type="hidden" name="_csrf" value="${c.csrf}">`;
}

export function field(c, { name, label, type = "text", value = "", required = false, hint, error, autocomplete, attrs = "", inputmode }) {
  const id = `f-${name}`;
  return html`<div class="field">
    <label for="${id}">${label}${required ? "" : html` <span class="muted small">(${c.t("form.optional")})</span>`}</label>
    <input id="${id}" name="${name}" type="${type}" value="${value ?? ""}" ${required ? raw("required") : ""} ${autocomplete ? raw(`autocomplete="${autocomplete}"`) : ""}
      ${inputmode ? raw(`inputmode="${inputmode}"`) : ""} ${error ? raw(`aria-invalid="true" aria-describedby="${id}-err"`) : hint ? raw(`aria-describedby="${id}-hint"`) : ""} ${raw(attrs)}>
    ${hint ? html`<p class="field-hint" id="${id}-hint">${hint}</p>` : ""}
    ${error ? html`<p class="field-error" id="${id}-err">${error}</p>` : ""}
  </div>`;
}

export function selectField(c, { name, label, options, value, required = false, hint }) {
  const id = `f-${name}`;
  return html`<div class="field"><label for="${id}">${label}${required ? "" : html` <span class="muted small">(${c.t("form.optional")})</span>`}</label>
    <select id="${id}" name="${name}" ${required ? raw("required") : ""}>
      ${options.map(([v, l]) => html`<option value="${v}" ${String(v) === String(value ?? "") ? raw("selected") : ""}>${l}</option>`)}
    </select>${hint ? html`<p class="field-hint">${hint}</p>` : ""}</div>`;
}

/**
 * lang/dir attributes for one curriculum field written in a language other
 * than the page's: English source text inside a translated page, or a
 * translation inside an English page. Decided per field, since a row may be
 * only partly translated. Keeps screen readers and bidi layout correct.
 */
export function contentLang(c, row, field) {
  const tr = row?._tr;
  if (!tr) return "";
  const lang = tr.fields?.has(field) ? c.locale : "en";
  return lang === c.displayLocale ? "" : raw(` lang="${lang}" dir="${localeInfo(lang).dir}"`);
}

/**
 * Says when curriculum content is shown in English or as an unreviewed machine
 * translation. The machine-translation disclosure follows the content's
 * language, so it also shows on pages whose interface falls back to English;
 * "shown in English" is redundant there (the page notice already says so).
 */
export function translationNotice(c, tr) {
  if (!tr || c.locale === "en") return "";
  if (tr.status === "missing" && c.displayLocale !== "en") return html`<p class="translation-note">${icon("globe", { size: 14 })} ${c.t("i18n.content_in_english")}</p>`;
  if (tr.status === "machine") return html`<p class="translation-note">${icon("globe", { size: 14 })} ${c.t("i18n.machine_translated")}</p>`;
  return "";
}

export function lessonTypeIcon(type) {
  return { video: "play", text: "file", reading: "book", interactive: "sparkles", resource: "download", exercise: "target", quiz: "check-circle", case_study: "map", assignment: "edit" }[type] || "file";
}
