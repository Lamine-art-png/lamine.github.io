// Course catalog (search + filters), course landing pages, and enrollment.
import { html, raw } from "../lib/html.js";
import { redirect, HttpError, json } from "../lib/http.js";
import { formatDuration } from "../lib/util.js";
import { LOCALES } from "../lib/i18n.js";
import { icon } from "../views/icons.js";
import { courseThumb } from "../views/art.js";
import { courseCard, pageHead, emptyState, breadcrumbs, courseStatusBadge, levelLabel, translationNotice, lessonTypeIcon, csrfField, progressBar, alert } from "../views/components.js";
import { listCourses, listPrograms, getCourseBySlug, getSyllabus, getInstructorsForCourse, getPrerequisites } from "../services/content.js";
import { getEnrollment, enroll, unmetRequiredPrerequisites, withdraw } from "../services/progress.js";
import { certificationExam, activeCertificate } from "../services/certificates.js";
import { TOPICS } from "./public.js";

const DURATIONS = [["", "catalog.any_length"], ["60", "catalog.under_1h"], ["180", "catalog.under_3h"], ["600", "catalog.under_10h"]];

export async function catalog(c) {
  const t = c.t;
  const q = (c.url.searchParams.get("q") || "").trim().slice(0, 80);
  const filters = {
    q,
    topic: TOPICS.includes(c.url.searchParams.get("topic")) ? c.url.searchParams.get("topic") : "",
    level: ["beginner", "intermediate", "advanced"].includes(c.url.searchParams.get("level")) ? c.url.searchParams.get("level") : "",
    program: (c.url.searchParams.get("program") || "").replace(/[^a-z0-9-]/g, ""),
    language: LOCALES.some((l) => l.code === c.url.searchParams.get("language")) ? c.url.searchParams.get("language") : "",
    maxMinutes: Number(c.url.searchParams.get("duration")) || 0,
  };
  const availableOnly = c.url.searchParams.get("available") === "1";
  const [courses, programs] = await Promise.all([listCourses(c.env, c.locale, { ...filters, includeUpcoming: !availableOnly }), listPrograms(c.env, c.locale)]);
  const progress = new Map();
  if (c.user) {
    for (const e of (await c.env.DB.prepare("SELECT course_id, progress_pct FROM enrollments WHERE user_id = ? AND status != 'withdrawn'").bind(c.user.id).all()).results) progress.set(e.course_id, e.progress_pct);
  }
  const radio = (name, value, label, current) =>
    html`<label class="check"><input type="radio" name="${name}" value="${value}" ${String(current) === String(value) ? raw("checked") : ""}> ${label}</label>`;

  const body = html`${pageHead({ eyebrow: t("catalog.eyebrow"), title: t("catalog.title"), lead: t("catalog.lead") })}
  <div class="wrap catalog">
    <form class="filters" method="get" action="/courses" data-autosubmit-change aria-label="${t("catalog.filters")}">
      <div class="filters-inner">
        <fieldset><legend>${t("catalog.availability")}</legend>
          <label class="check"><input type="checkbox" name="available" value="1" ${availableOnly ? raw("checked") : ""}> ${t("catalog.available_now")}</label></fieldset>
        <fieldset><legend>${t("catalog.level")}</legend>
          ${radio("level", "", t("catalog.all_levels"), filters.level)}
          ${["beginner", "intermediate", "advanced"].map((l) => radio("level", l, levelLabel(c, l), filters.level))}</fieldset>
        <fieldset><legend>${t("catalog.program")}</legend>
          ${radio("program", "", t("catalog.all_programs"), filters.program)}
          ${programs.map((p) => radio("program", p.slug, p.title, filters.program))}</fieldset>
        <fieldset><legend>${t("catalog.duration")}</legend>${DURATIONS.map(([v, k]) => radio("duration", v, t(k), filters.maxMinutes || ""))}</fieldset>
        <fieldset><legend><label for="f-topic">${t("catalog.topic")}</label></legend>
          <select id="f-topic" name="topic"><option value="">${t("catalog.all_topics")}</option>${TOPICS.map((k) => html`<option value="${k}" ${filters.topic === k ? raw("selected") : ""}>${t(`topic.${k}`)}</option>`)}</select></fieldset>
        <fieldset><legend><label for="f-language">${t("catalog.content_language")}</label></legend>
          <select id="f-language" name="language"><option value="">${t("catalog.any_language")}</option>${LOCALES.map((l) => html`<option value="${l.code}" ${filters.language === l.code ? raw("selected") : ""}>${l.nativeName}</option>`)}</select></fieldset>
      </div>
      <input type="hidden" name="q" value="${q}">
      <noscript><button class="btn btn-secondary btn-sm" type="submit">${t("action.apply")}</button></noscript>
      ${filters.level || filters.program || filters.topic || filters.language || filters.maxMinutes || availableOnly || q ? html`<a class="small" href="/courses">${t("catalog.clear")}</a>` : ""}
    </form>
    <div>
      <form class="search-bar" method="get" action="/courses" role="search">
        ${Object.entries({ level: filters.level, program: filters.program, topic: filters.topic, language: filters.language, duration: filters.maxMinutes || "", available: availableOnly ? "1" : "" })
          .filter(([, v]) => v)
          .map(([k, v]) => html`<input type="hidden" name="${k}" value="${v}">`)}
        <label class="sr-only" for="q">${t("catalog.search_label")}</label>
        <input id="q" type="search" name="q" value="${q}" placeholder="${t("catalog.search_placeholder")}" autocomplete="off">
        <button class="btn btn-primary" type="submit">${icon("search", { size: 18 })}<span class="hide-sm">${t("catalog.search")}</span></button>
      </form>
      <p class="results-meta" role="status">${t("catalog.results", { n: courses.length })}</p>
      ${courses.length
        ? html`<div class="cards">${courses.map((x) => courseCard(c, x, { progress: progress.has(x.id) ? progress.get(x.id) : null }))}</div>`
        : emptyState({ iconName: "search", title: t("catalog.no_results_title"), body: t("catalog.no_results_body"), action: html`<a class="btn btn-secondary" href="/courses">${t("catalog.clear")}</a>` })}
    </div>
  </div>`;
  return c.page({ title: t("catalog.title"), description: t("catalog.lead"), body, active: "courses", noindex: Boolean(q) });
}

export async function courseLanding(c) {
  const t = c.t;
  const staff = c.can("courses.edit");
  const course = await getCourseBySlug(c.env, c.params.slug, c.locale, { staff });
  const [syllabus, instructors, prereqs, exam, enrollment, rating] = await Promise.all([
    getSyllabus(c.env, course.id, c.locale),
    getInstructorsForCourse(c.env, course.id),
    getPrerequisites(c.env, course.id, c.locale),
    certificationExam(c.env, course.id),
    c.user ? getEnrollment(c.env, c.user.id, course.id) : null,
    c.env.DB.prepare("SELECT COUNT(*) AS n, AVG(rating) AS avg FROM course_feedback WHERE course_id = ?").bind(course.id).first(),
  ]);
  const cert = c.user ? await activeCertificate(c.env, c.user.id, course.id) : null;
  const unmet = c.user && course.isAvailable && !enrollment ? await unmetRequiredPrerequisites(c.env, c.user.id, course.id) : [];
  const enrolled = enrollment && enrollment.status !== "withdrawn";
  const lessonsTotal = syllabus.lessons.length;
  const err = c.url.searchParams.get("error");

  let action;
  if (enrolled) {
    action = html`${progressBar(c, enrollment.progress_pct)}<p class="small muted mt-1">${t("progress.percent_complete", { pct: enrollment.progress_pct })}</p>
      <a class="btn btn-primary btn-block btn-lg" href="/learn/${course.slug}">${enrollment.progress_pct ? t("course.continue") : t("course.start")} ${icon("arrow-right", { size: 18, cls: "ic-flip" })}</a>
      ${cert ? html`<a class="btn btn-secondary btn-block mt-1" href="/certificates/${cert.credential_id}">${icon("award", { size: 16 })} ${t("course.view_certificate")}</a>` : ""}`;
  } else if (course.isAvailable) {
    action = c.user
      ? unmet.length
        ? html`${alert("warn", html`${t("course.prereq_required")} ${unmet.map((u, i) => html`${i ? ", " : ""}<a href="/courses/${u.slug}">${u.title}</a>`)}`)}`
        : html`<form method="post" action="/courses/${course.slug}/enroll">${csrfField(c)}<button class="btn btn-primary btn-block btn-lg" type="submit">${t("course.enroll_free")}</button></form>`
      : html`<a class="btn btn-primary btn-block btn-lg" href="/register?next=${encodeURIComponent(`/courses/${course.slug}`)}">${t("course.enroll_free")}</a>
             <p class="small center mt-1">${t("auth.have_account")} <a href="/login?next=${encodeURIComponent(`/courses/${course.slug}`)}">${t("nav.sign_in")}</a></p>`;
  } else if (course.isUpcoming) {
    action = html`<div class="upcoming-box">${icon("clock", { size: 20 })}<strong>${course.scheduled_at || course.planned_release_date ? t("course.opens_on", { date: c.fmtDate(course.scheduled_at || course.planned_release_date) }) : t("course.coming_soon")}</strong></div>
      <p class="small muted mt-1">${c.user ? t("course.upcoming_notify_signed_in") : html`${t("course.upcoming_notify")} <a href="/register">${t("auth.create_free")}</a>`}</p>`;
  } else {
    action = html`<p class="muted">${t("course.not_available")}</p>`;
  }

  const body = html`
  ${course.status !== "published" && staff ? html`<div class="notice-bar"><div class="wrap">${icon("eye", { size: 16 })} ${t("course.staff_preview", { status: t(`status.${course.status}`) })}</div></div>` : ""}
  <section class="course-hero"><div class="wrap course-hero-grid">
    <div>
      ${breadcrumbs([[t("nav.courses"), "/courses"], ...(course.program_title ? [[course.program_title, `/programs#${course.program_slug}`]] : []), [course.title]])}
      ${course.program_title ? html`<p class="eyebrow">${t("program.label", { code: course.program_code || "" })} · ${course.program_title}</p>` : ""}
      <h1 class="display-sm">${course.title}</h1>
      <p class="lead">${course.subtitle}</p>
      <div class="meta">
        <span>${icon("layers", { size: 16 })} ${levelLabel(c, course.level)}</span>
        ${course.duration_minutes ? html`<span>${icon("clock", { size: 16 })} ${formatDuration(course.duration_minutes, t)}</span>` : ""}
        <span>${icon("book", { size: 16 })} ${t("course.lesson_count", { n: lessonsTotal })}</span>
        ${course.certificate_enabled ? html`<span>${icon("award", { size: 16 })} ${t("course.free_certificate")}</span>` : ""}
        ${rating?.n >= 5 ? html`<span>${icon("star", { size: 16 })} ${c.fmtNum(rating.avg, { maximumFractionDigits: 1 })} (${rating.n})</span>` : ""}
        ${courseStatusBadge(c, course)}
      </div>
      ${translationNotice(c, course._tr)}
    </div>
    <aside class="enroll-card" aria-label="${t("course.enrollment")}">
      <div class="thumb"><img src="${courseThumb(course)}" alt="" width="800" height="450"></div>
      <div class="body">
        ${err ? alert("error", t(`course.error.${err}`)) : ""}
        <p class="mb-2"><strong class="h2">${t("course.free")}</strong></p>
        ${action}
        <ul class="check-list small">
          <li>${icon("check", { size: 16 })} ${t("course.includes_lessons", { n: lessonsTotal })}</li>
          ${exam ? html`<li>${icon("check", { size: 16 })} ${t("course.includes_exam", { score: exam.passing_score })}</li>` : ""}
          ${course.certificate_enabled && exam ? html`<li>${icon("check", { size: 16 })} ${t("course.includes_certificate")}</li>` : ""}
          <li>${icon("check", { size: 16 })} ${t("course.includes_progress")}</li>
        </ul>
      </div>
    </aside>
  </div></section>

  <div class="wrap course-body">
    <div>
      ${course.objectives.length ? html`<h2 class="h2">${t("course.objectives")}</h2><ul class="objectives">${course.objectives.map((o) => html`<li>${icon("check", { size: 18 })}<span>${o}</span></li>`)}</ul>` : ""}
      <h2 class="h2">${t("course.about")}</h2>
      <div class="prose">${course.description.split(/\n{2,}/).map((p) => html`<p>${p}</p>`)}</div>

      <h2 class="h2 mt-4">${t("course.syllabus")}</h2>
      <p class="muted">${t("course.syllabus_meta", { modules: syllabus.modules.length, lessons: lessonsTotal })}</p>
      <div class="syllabus">${syllabus.modules.map(
        (m, mi) => html`<details ${mi === 0 ? raw("open") : ""}><summary><span>${t("course.module_n", { n: mi + 1 })} · ${m.title}</span><span class="muted">${t("course.lesson_count", { n: m.lessons.length })}</span></summary>
          ${m.summary ? html`<p class="small muted mod-summary">${m.summary}</p>` : ""}
          <ol>${m.lessons.map(
            (l) => html`<li><span class="grow">${icon(lessonTypeIcon(l.type), { size: 16 })} ${l.title}</span>
              ${l.is_preview && course.isAvailable ? html`<a class="badge badge-lime" href="/learn/${course.slug}/${l.slug}">${t("course.preview")}</a>` : ""}
              <span class="small muted nowrap">${t("duration.minutes", { n: l.est_minutes })}</span></li>`,
          )}</ol></details>`,
      )}</div>

      ${prereqs.length
        ? html`<h2 class="h2 mt-4">${t("course.prerequisites")}</h2>
          <ul>${prereqs.map((p) => html`<li><a href="/courses/${p.slug}">${p.title}</a> ${p.is_required ? html`<span class="badge">${t("course.required")}</span>` : html`<span class="badge">${t("course.recommended")}</span>`}</li>`)}</ul>`
        : course.prerequisites_text
          ? html`<h2 class="h2 mt-4">${t("course.prerequisites")}</h2><p>${course.prerequisites_text}</p>`
          : ""}
    </div>
    <div>
      ${exam
        ? html`<section class="panel"><h2 class="h2">${t("course.assessment_policy")}</h2>
          <dl class="kv">
            <dt>${t("assess.passing_score")}</dt><dd>${exam.passing_score}%</dd>
            ${exam.time_limit_seconds ? html`<dt>${t("assess.time_limit")}</dt><dd>${t("duration.minutes", { n: Math.round(exam.time_limit_seconds / 60) })}</dd>` : ""}
            <dt>${t("assess.attempts")}</dt><dd>${exam.max_attempts ? exam.max_attempts : t("assess.unlimited")}</dd>
            ${exam.cooldown_minutes ? html`<dt>${t("assess.retake_wait")}</dt><dd>${t("duration.minutes", { n: exam.cooldown_minutes })}</dd>` : ""}
          </dl>
          <p class="small muted mt-2">${course.require_all_lessons ? t("course.exam_unlock_rule") : ""}</p></section>`
        : ""}
      ${instructors.length
        ? html`<section class="panel mt-2"><h2 class="h2">${t("course.instructors")}</h2>
          ${instructors.map((i) => html`<div class="instructor mt-2"><div class="instructor-avatar">${i.avatar_url ? html`<img src="${i.avatar_url}" alt="">` : i.name.charAt(0)}</div>
            <div><strong>${i.name}</strong><p class="small muted mb-0">${i.title}</p>${i.is_ai_avatar ? html`<span class="badge badge-lime mt-1">${t("instructor.ai_avatar")}</span>` : ""}</div></div>`)}</section>`
        : ""}
      ${course.audience.length ? html`<section class="panel mt-2"><h2 class="h2">${t("course.audience")}</h2><div class="topic-chips">${course.audience.map((r) => html`<span class="chip">${t(`role.${r}`)}</span>`)}</div></section>` : ""}
      ${enrolled && enrollment.status === "active"
        ? html`<form class="mt-2" method="post" action="/courses/${course.slug}/withdraw" data-confirm="${t("course.withdraw_confirm")}">${csrfField(c)}<button class="link-btn small muted" type="submit">${t("course.withdraw")}</button></form>`
        : ""}
    </div>
  </div>`;

  return c.page({
    title: course.title,
    description: course.subtitle || course.description.slice(0, 160),
    body,
    active: "courses",
    noindex: course.status === "draft",
    ogImage: undefined,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "Course",
      name: course.title,
      description: course.subtitle || course.description.slice(0, 300),
      url: `${c.cfg.origin}/courses/${course.slug}`,
      inLanguage: course.source_locale,
      educationalLevel: course.level,
      isAccessibleForFree: true,
      offers: { "@type": "Offer", price: 0, priceCurrency: "USD", category: "Free" },
      provider: { "@type": "Organization", name: "AGRO-AI Academy", sameAs: c.cfg.origin },
      hasCourseInstance: course.isAvailable ? { "@type": "CourseInstance", courseMode: "online", courseWorkload: `PT${Math.max(1, Math.round(course.duration_minutes / 60))}H` } : undefined,
    },
  });
}

export async function enrollAction(c) {
  const course = await getCourseBySlug(c.env, c.params.slug, c.locale);
  const wantsJson = (c.req.headers.get("accept") || "").includes("application/json");
  try {
    await enroll(c, course);
  } catch (e) {
    if (e instanceof HttpError && e.status === 409) {
      if (wantsJson) throw e;
      return redirect(`/courses/${course.slug}?error=${e.code}`);
    }
    throw e;
  }
  if (wantsJson) return json({ ok: true });
  return redirect(`/learn/${course.slug}`);
}

export async function withdrawAction(c) {
  const course = await getCourseBySlug(c.env, c.params.slug, c.locale);
  await withdraw(c.env, c.user.id, course.id);
  return redirect(`/courses/${course.slug}`);
}
