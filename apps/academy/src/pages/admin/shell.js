// Shared admin layout and helpers. The admin console is an internal staff
// tool and is presented in English.
import { html, raw } from "../../lib/html.js";
import { icon } from "../../views/icons.js";

const NAV = [
  ["Overview", [["/admin", "chart", "Analytics", "analytics.view"]]],
  [
    "Curriculum",
    [
      ["/admin/courses", "book", "Courses", "courses.edit"],
      ["/admin/programs", "layers", "Programs & paths", "courses.edit"],
      ["/admin/videos", "play", "Videos", "courses.edit"],
      ["/admin/instructors", "users", "Instructors", "instructors.edit"],
    ],
  ],
  [
    "Assessment",
    [
      ["/admin/banks", "list", "Question banks", "assessments.edit"],
      ["/admin/grading", "edit", "Grading queue", "grading"],
    ],
  ],
  [
    "People",
    [
      ["/admin/learners", "user", "Learners", "learners.view"],
      ["/admin/certificates", "award", "Certificates", "certificates.manage"],
      ["/admin/feedback", "star", "Feedback", "feedback.view"],
      ["/admin/support", "help", "Support", "support.manage"],
    ],
  ],
  [
    "Operations",
    [
      ["/admin/translations", "globe", "Translations", "translations.edit"],
      ["/admin/email", "mail", "Email outbox", "support.manage"],
      ["/admin/audit", "shield", "Audit log", "audit.view"],
    ],
  ],
];

export function adminPage(c, { title, active, body, actions = "", status = 200, flash = null }) {
  const nav = html`<nav class="admin-nav" aria-label="Administration">
    ${NAV.map(([group, items]) => {
      const visible = items.filter(([, , , perm]) => c.can(perm));
      if (!visible.length) return "";
      return html`<h2>${group}</h2>${visible.map(([href, ic, label]) => html`<a href="${href}" ${active === href ? raw('aria-current="page"') : ""}>${icon(ic, { size: 16 })} ${label}</a>`)}`;
    })}
  </nav>`;
  const msg = flash ?? c.url.searchParams.get("ok");
  return c.page({
    title: `${title} · Admin`,
    noindex: true,
    status,
    body: html`<div class="admin">${nav}<div class="admin-main" lang="en">
      <div class="row-between mb-2"><h1 class="mb-0">${title}</h1><div class="row">${actions}</div></div>
      ${msg ? html`<div class="alert alert-success" role="status">${icon("check-circle", { size: 18 })}<div>${messageFor(msg)}</div></div>` : ""}
      ${c.url.searchParams.get("err") ? html`<div class="alert alert-error" role="alert">${icon("alert", { size: 18 })}<div>${c.url.searchParams.get("err")}</div></div>` : ""}
      ${body}</div></div>`,
  });
}

function messageFor(code) {
  return (
    {
      saved: "Changes saved.",
      created: "Created.",
      deleted: "Deleted.",
      published: "Course published.",
      issued: "Certificate issued.",
      revoked: "Certificate revoked.",
      reinstated: "Certificate reinstated.",
      graded: "Grade recorded.",
      sent: "Email queued.",
    }[code] || "Done."
  );
}

export const statusBadge = (s) => {
  const cls = { published: "badge-green", active: "badge-green", approved: "badge-green", graded: "badge-green", sent: "badge-green", reviewed: "badge-green", scheduled: "badge-lime", review: "badge-lime", in_review: "badge-lime", machine: "badge-lime", draft: "badge-warn", pending_review: "badge-warn", pending: "badge-warn", open: "badge-warn", planned: "badge-warn", scripted: "badge-warn", unconfigured: "badge-warn", archived: "", retired: "", revoked: "badge-danger", failed: "badge-danger", outdated: "badge-danger", changes_requested: "badge-danger", disabled: "badge-danger" }[s] ?? "";
  return html`<span class="badge ${cls} status-pill">${String(s || "").replace(/_/g, " ")}</span>`;
};

export function table(headers, rows, { label = "" } = {}) {
  // Scrollable on small screens, so the region is focusable for keyboard scrolling.
  return html`<div class="admin-table" tabindex="0" role="region" aria-label="${label || headers.filter((h) => typeof h === "string" && h).join(", ") || "Table"}"><table><thead><tr>${headers.map((h) => html`<th scope="col">${h}</th>`)}</tr></thead><tbody>${rows.length ? rows : html`<tr><td colspan="${headers.length}" class="muted">Nothing here yet.</td></tr>`}</tbody></table></div>`;
}

export const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);
export const num = (x, d = 0) => (x == null ? "—" : Number(x).toFixed(d));

export function barList(rows, { label = (r) => r.k, value = (r) => r.n } = {}) {
  const max = Math.max(1, ...rows.map(value));
  if (!rows.length) return html`<p class="muted small">No data recorded yet.</p>`;
  return html`<div class="bar-list">${rows.map((r) => {
    const v = value(r);
    return html`<div class="bar-row"><span class="small">${label(r)}</span><span class="bar"><span class="pct-${Math.round((v / max) * 100)}"></span></span><span class="small">${v}</span></div>`;
  })}</div>`;
}

export function hidden(c) {
  return html`<input type="hidden" name="_csrf" value="${c.csrf}">`;
}

export function input(name, label, value = "", { type = "text", required = false, hint = "", attrs = "", id = `a-${name}` } = {}) {
  return html`<div class="field"><label for="${id}">${label}</label><input id="${id}" name="${name}" type="${type}" value="${value ?? ""}" ${required ? raw("required") : ""} ${raw(attrs)}>${hint ? html`<p class="field-hint">${hint}</p>` : ""}</div>`;
}

export function textarea(name, label, value = "", { rows = 6, hint = "", cls = "", required = false, id = `a-${name}` } = {}) {
  return html`<div class="field"><label for="${id}">${label}</label><textarea id="${id}" name="${name}" rows="${rows}" class="${cls}" ${required ? raw("required") : ""}>${value ?? ""}</textarea>${hint ? html`<p class="field-hint">${hint}</p>` : ""}</div>`;
}

export function select(name, label, options, value, { hint = "", id = `a-${name}` } = {}) {
  return html`<div class="field"><label for="${id}">${label}</label><select id="${id}" name="${name}">${options.map((o) => {
    const [v, l] = Array.isArray(o) ? o : [o, o];
    return html`<option value="${v}" ${String(v) === String(value ?? "") ? raw("selected") : ""}>${l}</option>`;
  })}</select>${hint ? html`<p class="field-hint">${hint}</p>` : ""}</div>`;
}

export function checkbox(name, label, on, hint = "") {
  return html`<div class="field"><label class="check"><input type="checkbox" name="${name}" value="1" ${on ? raw("checked") : ""}><span>${label}${hint ? html`<span class="field-hint">${hint}</span>` : ""}</span></label></div>`;
}

export const bool = (v) => (v === "1" || v === 1 || v === true || v === "on" ? 1 : 0);
export const str = (v, max = 500) => String(v ?? "").trim().slice(0, max);
export const intOrNull = (v) => (v === "" || v == null || Number.isNaN(Number(v)) ? null : Math.round(Number(v)));
