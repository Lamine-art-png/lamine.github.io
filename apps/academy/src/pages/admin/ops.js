// Admin: analytics overview, feedback, support, email outbox, audit log.
import { html } from "../../lib/html.js";
import { redirect } from "../../lib/http.js";
import { nowIso } from "../../lib/util.js";
import { audit } from "../../lib/security.js";
import { localeInfo } from "../../lib/i18n.js";
import { adminPage, table, statusBadge, pct, num, barList, hidden, select, textarea, str } from "./shell.js";
import { overviewMetrics, courseMetrics, breakdowns, lessonEngagement } from "../../services/analytics.js";
import { flushOutbox } from "../../services/email.js";

export async function overview(c) {
  const days = [7, 30, 90, 365].includes(Number(c.url.searchParams.get("days"))) ? Number(c.url.searchParams.get("days")) : 30;
  const [m, courses, b] = await Promise.all([overviewMetrics(c.env, days), courseMetrics(c.env), breakdowns(c.env, days)]);
  const regionNames = new Intl.DisplayNames(["en"], { type: "region" });
  const kpi = (v, l) => html`<div class="kpi"><span class="value">${v}</span><span class="label">${l}</span></div>`;
  const body = html`
    <form method="get" class="row mb-2"><label for="days" class="mb-0">Window</label>
      <select id="days" name="days" data-autosubmit-change>${[7, 30, 90, 365].map((d) => html`<option value="${d}" ${d === days ? "selected" : ""}>Last ${d} days</option>`)}</select>
      <noscript><button class="btn btn-sm btn-secondary">Apply</button></noscript></form>
    <div class="kpis">
      ${kpi(m.learners, "Registered learners")}
      ${kpi(m.activeLearners, `Active learners (${days}d)`)}
      ${kpi(m.newRegistrations, `New registrations (${days}d)`)}
      ${kpi(m.enrollments, "Enrollments")}
      ${kpi(pct(m.completionRate), "Course completion rate")}
      ${kpi(m.examAttempts, "Graded exam attempts")}
      ${kpi(pct(m.examPassRate), "Exam pass rate")}
      ${kpi(m.avgExamScore == null ? "—" : `${num(m.avgExamScore, 1)}%`, "Average exam score")}
      ${kpi(m.certificates - m.revokedCertificates, "Active certificates")}
      ${kpi(m.avgRating == null ? "—" : `${num(m.avgRating, 1)} / 5`, `Course rating (${m.feedbackCount})`)}
      ${kpi(m.pendingReview, "Awaiting manual grading")}
      ${kpi(m.openSupport, "Open support requests")}
    </div>
    <h2 class="h2">Courses</h2>
    ${table(
      ["Course", "Status", "Enrolled", "Completed", "Avg progress", "Exam attempts", "Pass rate", "Avg score", "Certificates", "Rating"],
      courses.map(
        (r) => html`<tr><td class="wrap-cell"><a href="/admin/courses/${r.id}">${r.title}</a> · <a class="tiny" href="/admin/analytics/course/${r.id}">engagement</a></td><td>${statusBadge(r.status)}</td>
          <td>${r.enrolled}</td><td>${r.completed}</td><td>${r.avg_progress == null ? "—" : `${Math.round(r.avg_progress)}%`}</td>
          <td>${r.exam_attempts}</td><td>${r.exam_attempts ? pct((r.exam_passed || 0) / r.exam_attempts) : "—"}</td><td>${r.avg_score == null ? "—" : `${num(r.avg_score, 1)}%`}</td>
          <td>${r.certificates}</td><td>${r.ratings ? `${num(r.rating, 1)} (${r.ratings})` : "—"}</td></tr>`,
      ),
    )}
    <div class="cards cards-3 mt-4">
      <section class="card"><h2 class="h2">Interface language</h2>${barList(b.languages, { label: (r) => `${localeInfo(r.k).englishName} (${r.k})` })}</section>
      <section class="card"><h2 class="h2">Country <span class="tiny muted">(opt-in only)</span></h2>${barList(b.countries, { label: (r) => regionNames.of(r.k) || r.k })}</section>
      <section class="card"><h2 class="h2">Professional role</h2>${barList(b.roles, { label: (r) => r.k.replace(/_/g, " ") })}</section>
    </div>
    <section class="card mt-2"><h2 class="h2">Registrations by day (${days}d)</h2>${barList(b.registrations)}</section>
    <p class="tiny muted mt-2">All figures are computed from recorded learner activity. Country is shown only for learners who opted in to share it.</p>`;
  return adminPage(c, { title: "Academy analytics", active: "/admin", body });
}

export async function courseEngagement(c) {
  const course = await c.env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(c.params.id).first();
  const rows = await lessonEngagement(c.env, c.params.id);
  const body = table(
    ["Lesson", "Type", "Started", "Completed", "Completion", "Helpful votes"],
    rows.map(
      (r) => html`<tr><td class="wrap-cell">${r.title}</td><td>${r.type}</td><td>${r.started}</td><td>${r.completed}</td><td>${r.started ? pct(r.completed / r.started) : "—"}</td>
        <td>${r.votes ? `${r.helpful || 0}/${r.votes} helpful` : "—"}</td></tr>`,
    ),
  );
  return adminPage(c, { title: `Engagement — ${course?.title || ""}`, active: "/admin", body });
}

export async function feedback(c) {
  const rows = (
    await c.env.DB.prepare(
      `SELECT f.*, c.title AS course_title, u.display_name FROM course_feedback f JOIN courses c ON c.id = f.course_id LEFT JOIN users u ON u.id = f.user_id ORDER BY f.updated_at DESC LIMIT 300`,
    ).all()
  ).results;
  const lessonRows = (
    await c.env.DB.prepare(
      `SELECT lf.comment, lf.helpful, lf.created_at, l.title AS lesson_title, c.title AS course_title FROM lesson_feedback lf JOIN lessons l ON l.id = lf.lesson_id JOIN courses c ON c.id = l.course_id
        WHERE lf.comment != '' ORDER BY lf.created_at DESC LIMIT 100`,
    ).all()
  ).results;
  const body = html`<h2 class="h2">Course feedback</h2>${table(
    ["Course", "Learner", "Rating", "Comment", "Status", ""],
    rows.map(
      (r) => html`<tr><td>${r.course_title}</td><td>${r.display_name || "Former learner"}</td><td>${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</td><td class="wrap-cell">${r.comment}</td><td>${statusBadge(r.status)}</td>
        <td><form method="post" action="/admin/feedback/${r.id}">${hidden(c)}<select name="status" aria-label="Status">${["new", "reviewed", "actioned"].map((s) => html`<option ${s === r.status ? "selected" : ""}>${s}</option>`)}</select> <button class="btn btn-sm btn-secondary">Save</button></form></td></tr>`,
    ),
  )}
  <h2 class="h2 mt-4">Lesson comments</h2>${table(
    ["Course", "Lesson", "Helpful", "Comment", "Date"],
    lessonRows.map((r) => html`<tr><td>${r.course_title}</td><td>${r.lesson_title}</td><td>${r.helpful ? "Yes" : "No"}</td><td class="wrap-cell">${r.comment}</td><td>${r.created_at.slice(0, 10)}</td></tr>`),
  )}`;
  return adminPage(c, { title: "Learner feedback", active: "/admin/feedback", body });
}

export async function feedbackUpdate(c) {
  const b = await c.readBody();
  const status = ["new", "reviewed", "actioned"].includes(b.status) ? b.status : "reviewed";
  await c.env.DB.prepare("UPDATE course_feedback SET status = ?, updated_at = ? WHERE id = ?").bind(status, nowIso(), c.params.id).run();
  return redirect("/admin/feedback?ok=saved");
}

export async function support(c) {
  const status = ["open", "answered", "closed"].includes(c.url.searchParams.get("status")) ? c.url.searchParams.get("status") : "open";
  const rows = (await c.env.DB.prepare("SELECT * FROM support_requests WHERE status = ? ORDER BY created_at DESC LIMIT 200").bind(status).all()).results;
  const body = html`<div class="tabs-inline">${["open", "answered", "closed"].map((s) => html`<a class="chip ${s === status ? "active" : ""}" href="/admin/support?status=${s}">${s}</a>`)}</div>
  ${rows.length
    ? rows.map(
        (r) => html`<article class="panel mt-2"><div class="row-between"><strong>${r.topic} · ${r.name} &lt;<a href="mailto:${r.email}">${r.email}</a>&gt;</strong><span class="tiny muted">${r.created_at.slice(0, 16).replace("T", " ")} UTC</span></div>
          <p class="mt-1">${r.message}</p>
          <form method="post" action="/admin/support/${r.id}">${hidden(c)}${textarea("admin_note", "Internal note", r.admin_note, { rows: 2 })}
            <div class="row">${select("status", "Status", ["open", "answered", "closed"], r.status)}<button class="btn btn-secondary btn-sm">Save</button></div></form></article>`,
      )
    : html`<p class="muted">No ${status} requests.</p>`}`;
  return adminPage(c, { title: "Support requests", active: "/admin/support", body });
}

export async function supportUpdate(c) {
  const b = await c.readBody();
  const status = ["open", "answered", "closed"].includes(b.status) ? b.status : "open";
  await c.env.DB.prepare("UPDATE support_requests SET status = ?, admin_note = ?, updated_at = ? WHERE id = ?").bind(status, str(b.admin_note, 2000), nowIso(), c.params.id).run();
  await audit(c, "support.update", "support_request", c.params.id, { status });
  return redirect("/admin/support?ok=saved");
}

export async function emailOutbox(c) {
  const rows = (await c.env.DB.prepare("SELECT id, to_email, template, category, locale, status, attempts, last_error, created_at, sent_at FROM email_outbox ORDER BY created_at DESC LIMIT 200").all()).results;
  const counts = (await c.env.DB.prepare("SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status").all()).results;
  const mask = (e) => e.replace(/^(.{2}).*(@.*)$/, "$1•••$2");
  const body = html`
    ${c.cfg.emailEnabled ? "" : html`<div class="alert alert-warn">Email delivery is not configured (RESEND_API_KEY and EMAIL_FROM). Messages are recorded as “unconfigured” and are not sent.</div>`}
    <div class="row mb-2">${counts.map((r) => html`${statusBadge(r.status)} <span class="small">${r.n}</span>`)}
      ${c.cfg.emailEnabled ? html`<form method="post" action="/admin/email/flush">${hidden(c)}<button class="btn btn-sm btn-secondary">Retry pending now</button></form>` : ""}</div>
    ${table(
      ["Created", "To", "Template", "Category", "Locale", "Status", "Attempts", "Last error"],
      rows.map((r) => html`<tr><td>${r.created_at.slice(0, 16).replace("T", " ")}</td><td>${mask(r.to_email)}</td><td>${r.template}</td><td>${r.category}</td><td>${r.locale}</td><td>${statusBadge(r.status)}</td><td>${r.attempts}</td><td class="wrap-cell tiny">${r.last_error || ""}</td></tr>`),
    )}`;
  return adminPage(c, { title: "Email outbox", active: "/admin/email", body });
}

export async function emailFlush(c) {
  await flushOutbox(c.env, c.cfg, 50);
  return redirect("/admin/email?ok=sent");
}

export async function auditLog(c) {
  const q = str(c.url.searchParams.get("q"), 80);
  const rows = (
    await c.env.DB.prepare(
      `SELECT a.*, u.email AS actor_email FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id
        ${q ? "WHERE a.action LIKE ? OR a.entity_id = ? OR a.entity_type = ?" : ""} ORDER BY a.created_at DESC LIMIT 300`,
    )
      .bind(...(q ? [`%${q}%`, q, q] : []))
      .all()
  ).results;
  const body = html`<form method="get" class="search-bar"><label class="sr-only" for="aq">Filter</label><input id="aq" name="q" value="${q}" placeholder="Filter by action, entity type or ID"><button class="btn btn-secondary">Filter</button></form>
  ${table(
    ["Time (UTC)", "Actor", "Action", "Entity", "Detail"],
    rows.map((r) => html`<tr><td>${r.created_at.slice(0, 19).replace("T", " ")}</td><td>${r.actor_email || r.actor_id || "system"}</td><td><code>${r.action}</code></td><td>${r.entity_type || ""} ${r.entity_id ? html`<code class="tiny">${r.entity_id}</code>` : ""}</td><td class="wrap-cell tiny">${r.detail || ""}</td></tr>`),
  )}`;
  return adminPage(c, { title: "Audit log", active: "/admin/audit", body });
}
