// Learner workspace: overview, courses, results, history, certificates,
// goals, achievements and notifications. All figures come from the database.
import { html, raw } from "../lib/html.js";
import { redirect } from "../lib/http.js";
import { newId, nowIso } from "../lib/util.js";
import { icon } from "../views/icons.js";
import { courseThumb } from "../views/art.js";
import { alert, csrfField, emptyState, progressBar, ring, field, courseCard } from "../views/components.js";
import { localize } from "../services/content.js";
import { listAchievements } from "../services/activity.js";
import { recommendCourses, reviewSuggestions } from "../services/recommendations.js";
import { checkEligibility } from "../services/certificates.js";

function shell(c, active, content, { aside = "" } = {}) {
  const t = c.t;
  const tabs = [
    ["/dashboard", "overview", t("dash.tab_overview")],
    ["/dashboard/courses", "courses", t("dash.tab_courses")],
    ["/dashboard/results", "results", t("dash.tab_results")],
    ["/dashboard/certificates", "certificates", t("dash.tab_certificates")],
    ["/dashboard/history", "history", t("dash.tab_history")],
  ];
  return html`<section class="page-head"><div class="wrap">
      <p class="eyebrow">${t("dash.eyebrow")}</p>
      <h1 class="display-sm">${t("dash.hello", { name: c.user.display_name.split(" ")[0] })}</h1>
      <nav class="dash-tabs mt-2" aria-label="${t("dash.sections")}">${tabs.map(([href, key, label]) => html`<a href="${href}" ${key === active ? raw('aria-current="page"') : ""}>${label}</a>`)}</nav>
    </div></section>
    <div class="wrap ${aside ? "dash-grid" : "section-tight"}">${aside ? html`<div>${content}</div><aside>${aside}</aside>` : content}</div>`;
}

async function enrollmentRows(env, userId, locale, status) {
  const rows = (
    await env.DB.prepare(
      `SELECT e.*, c.id AS cid, c.slug, c.title, c.subtitle, c.thumbnail_url, c.topics_json, c.level, c.duration_minutes, c.status AS course_status,
              l.slug AS last_lesson_slug, l.title AS last_lesson_title
         FROM enrollments e JOIN courses c ON c.id = e.course_id LEFT JOIN lessons l ON l.id = e.last_lesson_id
        WHERE e.user_id = ? AND e.status ${status === "all" ? "!= 'withdrawn'" : "= ?"}
        ORDER BY e.last_activity_at DESC`,
    )
      .bind(...(status === "all" ? [userId] : [userId, status]))
      .all()
  ).results.map((r) => ({ ...r, id: r.cid, enrollment_id: r.id }));
  await localize(env, "course", rows, ["title", "subtitle"], locale);
  return rows;
}

export async function overview(c) {
  const t = c.t;
  const { env, user } = c;
  const [active, stats, recent, goals, achievements, recs, review, notes, notifications] = await Promise.all([
    enrollmentRows(env, user.id, c.locale, "active"),
    env.DB.prepare(
      `SELECT
        (SELECT COUNT(*) FROM enrollments WHERE user_id = ?1 AND status != 'withdrawn') AS enrolled,
        (SELECT COUNT(*) FROM enrollments WHERE user_id = ?1 AND status = 'completed') AS completed,
        (SELECT COUNT(*) FROM certificates WHERE user_id = ?1 AND status = 'active') AS certificates,
        (SELECT COUNT(*) FROM lesson_progress WHERE user_id = ?1 AND status = 'completed') AS lessons,
        (SELECT AVG(score_pct) FROM attempts t JOIN assessments a ON a.id = t.assessment_id WHERE t.user_id = ?1 AND t.status = 'graded' AND a.kind = 'exam') AS avg_exam,
        (SELECT COALESCE(SUM(l.est_minutes), 0) FROM lesson_progress lp JOIN lessons l ON l.id = lp.lesson_id WHERE lp.user_id = ?1 AND lp.status = 'completed') AS minutes`,
    )
      .bind(user.id)
      .first(),
    env.DB.prepare(
      `SELECT lp.last_viewed_at, lp.status, l.slug, l.title, l.id, c.slug AS course_slug, c.title AS course_title
         FROM lesson_progress lp JOIN lessons l ON l.id = lp.lesson_id JOIN courses c ON c.id = lp.course_id
        WHERE lp.user_id = ? ORDER BY lp.last_viewed_at DESC LIMIT 5`,
    )
      .bind(user.id)
      .all(),
    env.DB.prepare("SELECT * FROM learning_goals WHERE user_id = ? AND status != 'archived' ORDER BY status, created_at DESC").bind(user.id).all(),
    listAchievements(env, user.id),
    recommendCourses(env, user, c.locale, 3),
    reviewSuggestions(env, user.id, c.locale, 4),
    env.DB.prepare("SELECT COUNT(*) AS n FROM notes WHERE user_id = ?").bind(user.id).first(),
    env.DB.prepare("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 6").bind(user.id).all(),
  ]);
  await localize(env, "lesson", recent.results, ["title"], c.locale);
  const cont = active[0];
  const q = c.url.searchParams;
  const unread = notifications.results.filter((n) => !n.read_at).length;

  const main = html`
    ${q.get("welcome") === "1" ? alert("success", t("dash.welcome_new")) : ""}
    ${q.get("verified") === "1" ? alert("success", t("auth.verified")) : ""}
    ${q.get("verification_sent") === "1" ? alert("info", t("auth.verification_sent")) : ""}
    <div class="kpis">
      <div class="kpi"><span class="value">${c.fmtNum(stats.enrolled)}</span><span class="label">${t("dash.stat_enrolled")}</span></div>
      <div class="kpi"><span class="value">${c.fmtNum(stats.completed)}</span><span class="label">${t("dash.stat_completed")}</span></div>
      <div class="kpi"><span class="value">${c.fmtNum(stats.lessons)}</span><span class="label">${t("dash.stat_lessons")}</span></div>
      <div class="kpi"><span class="value">${c.fmtNum(stats.certificates)}</span><span class="label">${t("dash.stat_certificates")}</span></div>
      <div class="kpi"><span class="value">${stats.avg_exam != null ? `${c.fmtNum(stats.avg_exam, { maximumFractionDigits: 0 })}%` : "—"}</span><span class="label">${t("dash.stat_avg_exam")}</span></div>
      <div class="kpi"><span class="value">${c.fmtNum(Math.round(stats.minutes / 6) / 10)}</span><span class="label">${t("dash.stat_hours")}</span></div>
    </div>

    <h2 class="h2">${t("dash.continue")}</h2>
    ${cont
      ? html`<div class="card continue-card">
          <div class="thumb"><img src="${courseThumb(cont)}" alt="" width="800" height="450"></div>
          <div><h3>${cont.title}</h3>
            ${cont.last_lesson_title ? html`<p class="small muted">${t("dash.last_lesson", { lesson: cont.last_lesson_title })}</p>` : ""}
            ${progressBar(c, cont.progress_pct)}
            <p class="tiny muted mt-1">${t("progress.percent_complete", { pct: cont.progress_pct })}</p>
            <a class="btn btn-primary" href="/learn/${cont.slug}">${t("course.continue")} ${icon("arrow-right", { size: 16, cls: "ic-flip" })}</a></div>
        </div>`
      : stats.completed
        ? emptyState({ iconName: "trophy", title: t("dash.all_done_title"), body: t("dash.all_done_body"), action: html`<a class="btn btn-primary" href="/courses">${t("home.cta_explore")}</a>` })
        : emptyState({ iconName: "book", title: t("dash.no_courses_title"), body: t("dash.no_courses_body"), action: html`<a class="btn btn-primary" href="/courses">${t("home.cta_explore")}</a>` })}

    ${active.length > 1
      ? html`<h2 class="h2 mt-4">${t("dash.in_progress")}</h2><div class="card">${active.slice(1).map(
          (e) => html`<div class="list-row"><div class="thumb-sm"><img src="${courseThumb(e)}" alt="" loading="lazy"></div>
            <div class="grow"><a href="/learn/${e.slug}"><strong>${e.title}</strong></a>${progressBar(c, e.progress_pct)}</div><span class="small muted">${e.progress_pct}%</span></div>`,
        )}</div>`
      : ""}

    ${review.length
      ? html`<h2 class="h2 mt-4">${t("dash.review_title")}</h2><p class="muted">${t("dash.review_lead")}</p><div class="card">${review.map(
          (r) => html`<div class="list-row">${icon("target", { size: 20 })}<div class="grow"><a href="/learn/${r.course_slug}/${r.slug}">${r.title}</a><div class="tiny muted">${r.course_title}</div></div></div>`,
        )}</div>`
      : ""}

    <h2 class="h2 mt-4">${t("dash.recommended")}</h2>
    ${recs.length ? html`<div class="cards cards-3">${recs.map((r) => html`<div>${courseCard(c, r.course)}<p class="tiny muted mt-1">${icon("sparkles", { size: 12 })} ${t(r.reason)}</p></div>`)}</div>` : html`<p class="muted">${t("dash.no_recommendations")}</p>`}

    <h2 class="h2 mt-4">${t("dash.recent")}</h2>
    ${recent.results.length
      ? html`<div class="card">${recent.results.map(
          (r) => html`<div class="list-row">${icon(r.status === "completed" ? "check-circle" : "play", { size: 18 })}
            <div class="grow"><a href="/learn/${r.course_slug}/${r.slug}">${r.title}</a><div class="tiny muted">${r.course_title}</div></div>
            <time class="tiny muted" datetime="${r.last_viewed_at}">${c.fmtDate(r.last_viewed_at, { dateStyle: "medium" })}</time></div>`,
        )}</div>`
      : html`<p class="muted">${t("dash.no_recent")}</p>`}`;

  const aside = html`
    <section class="card"><h2 class="h2">${t("dash.goals")}</h2>
      ${goals.results.length
        ? goals.results.map(
            (g) => html`<div class="list-row"><span class="grow ${g.status === "achieved" ? "muted" : ""}">${g.status === "achieved" ? icon("check-circle", { size: 16 }) : icon("target", { size: 16 })} ${g.title}
              ${g.weekly_minutes ? html`<span class="tiny muted"> · ${t("dash.goal_weekly", { n: g.weekly_minutes })}</span>` : ""}${g.target_date ? html`<span class="tiny muted"> · ${c.fmtDate(g.target_date, { dateStyle: "medium" })}</span>` : ""}</span>
              <form method="post" action="/dashboard/goals/${g.id}">${csrfField(c)}<input type="hidden" name="status" value="${g.status === "achieved" ? "archived" : "achieved"}">
                <button class="link-btn tiny" type="submit">${g.status === "achieved" ? t("action.remove") : t("dash.goal_done")}</button></form></div>`,
          )
        : html`<p class="small muted">${t("dash.no_goals")}</p>`}
      <details class="mt-2"><summary class="small"><strong>${t("dash.add_goal")}</strong></summary>
        <form method="post" action="/dashboard/goals" class="mt-2">${csrfField(c)}
          ${field(c, { name: "title", label: t("dash.goal_title"), required: true, attrs: 'maxlength="120"' })}
          <div class="grid-2">${field(c, { name: "weekly_minutes", label: t("dash.goal_minutes"), type: "number", attrs: 'min="10" max="2000" step="5"' })}
          ${field(c, { name: "target_date", label: t("dash.goal_date"), type: "date" })}</div>
          <button class="btn btn-secondary btn-sm" type="submit">${t("action.save")}</button></form></details>
    </section>
    <section class="card mt-2"><h2 class="h2">${t("dash.achievements")}</h2>
      ${achievements.map(
        (a) => html`<div class="achievement ${a.earned ? "" : "locked"}"><span class="medal">${icon(a.earned ? a.icon : "lock", { size: 18 })}</span>
          <div><strong class="small">${t(`ach.${a.code}.title`)}</strong><div class="tiny muted">${a.earned ? t("dash.earned_on", { date: c.fmtDate(a.earned.earned_at, { dateStyle: "medium" }) }) : t(`ach.${a.code}.hint`)}</div></div></div>`,
      )}
    </section>
    <section class="card mt-2"><div class="row-between"><h2 class="h2 mb-0">${t("dash.notifications")}</h2>${unread ? html`<span class="badge badge-lime">${unread}</span>` : ""}</div>
      ${notifications.results.length
        ? html`${notifications.results.map((n) => html`<div class="list-row">${icon(n.read_at ? "bell" : "sparkles", { size: 16 })}<div class="grow small">${n.url ? html`<a href="${n.url}">${t(`notify.${n.kind}`, { title: n.title })}</a>` : t(`notify.${n.kind}`, { title: n.title })}<div class="tiny muted">${c.fmtDate(n.created_at, { dateStyle: "medium" })}</div></div></div>`)}
           ${unread ? html`<form method="post" action="/dashboard/notifications/read">${csrfField(c)}<button class="link-btn tiny" type="submit">${t("dash.mark_read")}</button></form>` : ""}`
        : html`<p class="small muted">${t("dash.no_notifications")}</p>`}
    </section>
    <p class="tiny muted mt-2">${t("dash.notes_count", { n: notes.n })}</p>`;
  return c.page({ title: t("nav.dashboard"), body: shell(c, "overview", main, { aside }), noindex: true });
}

export async function coursesTab(c) {
  const t = c.t;
  const all = await enrollmentRows(c.env, c.user.id, c.locale, "all");
  const section = (title, list) =>
    html`<h2 class="h2 mt-3">${title}</h2>${list.length
      ? html`<div class="cards cards-3">${list.map((e) => courseCard(c, { ...e, status: e.course_status, program_title: null, certificate_enabled: 0 }, { progress: e.progress_pct }))}</div>`
      : html`<p class="muted">${t("dash.none")}</p>`}`;
  const content = html`${section(t("dash.in_progress"), all.filter((e) => e.status === "active"))}${section(t("dash.completed_courses"), all.filter((e) => e.status === "completed"))}`;
  return c.page({ title: t("dash.tab_courses"), body: shell(c, "courses", all.length ? content : emptyState({ iconName: "book", title: t("dash.no_courses_title"), body: t("dash.no_courses_body"), action: html`<a class="btn btn-primary" href="/courses">${t("home.cta_explore")}</a>` })), noindex: true });
}

export async function resultsTab(c) {
  const t = c.t;
  const rows = (
    await c.env.DB.prepare(
      `SELECT t.*, a.title AS assessment_title, a.kind, a.passing_score, c.title AS course_title, c.slug AS course_slug
         FROM attempts t JOIN assessments a ON a.id = t.assessment_id JOIN courses c ON c.id = t.course_id
        WHERE t.user_id = ? ORDER BY t.started_at DESC LIMIT 200`,
    )
      .bind(c.user.id)
      .all()
  ).results;
  const content = rows.length
    ? html`<div class="admin-table mt-2"><table><thead><tr><th>${t("assess.assessment")}</th><th>${t("assess.type")}</th><th>${t("assess.date")}</th><th>${t("assess.score")}</th><th>${t("assess.result")}</th><th></th></tr></thead><tbody>
      ${rows.map(
        (r) => html`<tr><td class="wrap-cell"><strong>${r.assessment_title}</strong><div class="tiny muted">${r.course_title}</div></td>
          <td>${r.kind === "exam" ? t("assess.final_exam") : t("assess.quiz")}</td>
          <td>${c.fmtDate(r.submitted_at || r.started_at, { dateStyle: "medium" })}</td>
          <td>${r.score_pct != null ? `${c.fmtNum(r.score_pct, { maximumFractionDigits: 1 })}%` : "—"}</td>
          <td>${r.status === "graded" ? (r.passed ? html`<span class="badge badge-green">${t("assess.passed")}</span>` : html`<span class="badge badge-danger">${t("assess.not_passed")}</span>`) : html`<span class="badge badge-warn">${t(`assess.status.${r.status}`)}</span>`}</td>
          <td><a href="/attempts/${r.id}">${t("assess.view")}</a></td></tr>`,
      )}</tbody></table></div>`
    : emptyState({ iconName: "target", title: t("dash.no_results") });
  return c.page({ title: t("dash.tab_results"), body: shell(c, "results", content), noindex: true });
}

export async function historyTab(c) {
  const t = c.t;
  const rows = (
    await c.env.DB.prepare(
      `SELECT e.event, e.created_at, c.title AS course_title, c.slug AS course_slug, l.title AS lesson_title, l.slug AS lesson_slug
         FROM learning_events e LEFT JOIN courses c ON c.id = e.course_id LEFT JOIN lessons l ON l.id = e.lesson_id
        WHERE e.user_id = ? AND e.event IN ('registered','enrolled','lesson_completed','course_completed','quiz_passed','quiz_failed','exam_passed','exam_failed','certificate_issued')
        ORDER BY e.created_at DESC LIMIT 200`,
    )
      .bind(c.user.id)
      .all()
  ).results;
  const content = rows.length
    ? html`<ol class="card mt-2">${rows.map(
        (r) => html`<li class="list-row">${icon({ enrolled: "book", lesson_completed: "check-circle", course_completed: "trophy", certificate_issued: "award", exam_passed: "target", quiz_passed: "check" }[r.event] || "circle", { size: 18 })}
          <div class="grow">${t(`history.${r.event}`, { course: r.course_title || "", lesson: r.lesson_title || "" })}</div>
          <time class="tiny muted" datetime="${r.created_at}">${c.fmtDate(r.created_at, { dateStyle: "medium", timeStyle: "short" })}</time></li>`,
      )}</ol>`
    : emptyState({ iconName: "clock", title: t("dash.no_history") });
  return c.page({ title: t("dash.tab_history"), body: shell(c, "history", content), noindex: true });
}

export async function certificatesTab(c) {
  const t = c.t;
  const certs = (await c.env.DB.prepare("SELECT * FROM certificates WHERE user_id = ? ORDER BY issued_at DESC").bind(c.user.id).all()).results;
  // Completed courses that have no credential yet (e.g. email not verified).
  const pending = (
    await c.env.DB.prepare(
      `SELECT c.* FROM enrollments e JOIN courses c ON c.id = e.course_id
        WHERE e.user_id = ? AND e.status = 'completed' AND c.certificate_enabled = 1
          AND NOT EXISTS (SELECT 1 FROM certificates x WHERE x.user_id = e.user_id AND x.course_id = c.id AND x.status = 'active')`,
    )
      .bind(c.user.id)
      .all()
  ).results;
  const pendingInfo = await Promise.all(pending.map(async (course) => ({ course, elig: await checkEligibility(c.env, c.user, course) })));
  const missing = c.url.searchParams.get("missing");
  const content = html`
    ${missing ? alert("warn", t(missing)) : ""}
    ${pendingInfo.map(
      ({ course, elig }) => html`<div class="panel mt-2 row-between"><div><strong>${course.title}</strong><p class="small muted mb-0">${elig.eligible ? t("dash.cert_ready") : elig.reasons.map((r) => t(r)).join(" ")}</p></div>
        ${elig.eligible ? html`<form method="post" action="/certificates/claim/${course.slug}">${csrfField(c)}<button class="btn btn-primary" type="submit">${t("dash.claim_cert")}</button></form>` : ""}</div>`,
    )}
    ${certs.length
      ? html`<div class="cards cards-3 mt-2">${certs.map(
          (x) => html`<a class="card card-link" href="/certificates/${x.credential_id}">
            <span class="feature-icon">${icon("award", { size: 22 })}</span>
            <h3 class="mt-2">${x.course_title}</h3>
            <p class="small muted mb-1">${t("cert.issued")}: ${c.fmtDate(x.issued_at)}</p>
            <p class="tiny mb-0"><code>${x.credential_id}</code> ${x.status === "active" ? html`<span class="badge badge-green">${t("verify.status_active")}</span>` : html`<span class="badge badge-danger">${t("verify.status_revoked")}</span>`}</p></a>`,
        )}</div>`
      : pendingInfo.length
        ? ""
        : emptyState({ iconName: "award", title: t("dash.no_certificates_title"), body: t("dash.no_certificates_body"), action: html`<a class="btn btn-primary" href="/courses">${t("home.cta_explore")}</a>` })}`;
  return c.page({ title: t("nav.my_certificates"), body: shell(c, "certificates", content), noindex: true });
}

export async function addGoal(c) {
  const b = await c.readBody();
  const title = String(b.title || "").trim().slice(0, 120);
  if (title) {
    const count = await c.env.DB.prepare("SELECT COUNT(*) AS n FROM learning_goals WHERE user_id = ? AND status = 'active'").bind(c.user.id).first();
    if (count.n < 20) {
      const minutes = Math.round(Number(b.weekly_minutes)) || null;
      const date = /^\d{4}-\d{2}-\d{2}$/.test(b.target_date || "") ? b.target_date : null;
      const now = nowIso();
      await c.env.DB.prepare("INSERT INTO learning_goals (id, user_id, title, weekly_minutes, target_date, status, created_at, updated_at) VALUES (?,?,?,?,?, 'active', ?, ?)")
        .bind(newId("gol_"), c.user.id, title, minutes && minutes > 0 && minutes <= 2000 ? minutes : null, date, now, now)
        .run();
    }
  }
  return redirect("/dashboard");
}

export async function updateGoal(c) {
  const b = await c.readBody();
  const status = ["achieved", "archived", "active"].includes(b.status) ? b.status : "active";
  await c.env.DB.prepare("UPDATE learning_goals SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?").bind(status, nowIso(), c.params.id, c.user.id).run();
  return redirect("/dashboard");
}

export async function markNotificationsRead(c) {
  await c.env.DB.prepare("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL").bind(nowIso(), c.user.id).run();
  return redirect("/dashboard");
}

export { ring };
