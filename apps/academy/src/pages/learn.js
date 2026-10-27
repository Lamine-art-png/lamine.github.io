// The classroom: lesson player, syllabus navigation, notes, bookmarks,
// resources, transcripts, feedback, and the progress API.
import { html, raw, safeUrl } from "../lib/html.js";
import { redirect, json, HttpError } from "../lib/http.js";
import { newId, nowIso, parseJson } from "../lib/util.js";
import { rateLimit, audit } from "../lib/security.js";
import { renderMarkdown, md } from "../lib/markdown.js";
import { icon } from "../views/icons.js";
import { localeInfo } from "../lib/i18n.js";
import { csrfField, translationNotice, contentLang, lessonTypeIcon, progressBar, alert } from "../views/components.js";
import { getCourseBySlug, getSyllabus, getLesson, getVideo } from "../services/content.js";
import { validInteractive } from "../lib/interactive.js";
import { getEnrollment, progressMap, recordProgress, watchRequired } from "../services/progress.js";
import { certificationExam, activeCertificate } from "../services/certificates.js";
import { track } from "../services/activity.js";
import { isStreamVideo, playbackToken, iframeUrl, streamConfigured } from "../services/stream.js";

async function loadContext(c, { lessonSlug = null } = {}) {
  const staff = c.can("courses.edit");
  const course = await getCourseBySlug(c.env, c.params.course, c.locale, { staff, userId: c.user?.id });
  const enrollment = c.user ? await getEnrollment(c.env, c.user.id, course.id) : null;
  const enrolled = Boolean(enrollment && enrollment.status !== "withdrawn");
  const syllabus = await getSyllabus(c.env, course.id, c.locale, { includeDrafts: staff });
  return { course, enrollment, enrolled, syllabus, staff, lessonSlug };
}

export async function resume(c) {
  const { course, enrollment, enrolled, syllabus } = await loadContext(c);
  if (!enrolled) return redirect(`/courses/${course.slug}`);
  const progress = await progressMap(c.env, c.user.id, course.id);
  const last = syllabus.lessons.find((l) => l.id === enrollment.last_lesson_id);
  const target =
    (last && progress.get(last.id)?.status !== "completed" && last) ||
    syllabus.lessons.find((l) => progress.get(l.id)?.status !== "completed") ||
    last ||
    syllabus.lessons[0];
  if (!target) return redirect(`/courses/${course.slug}`);
  return redirect(`/learn/${course.slug}/${target.slug}`, 302);
}

function interactive(c, lesson) {
  const data = parseJson(lesson.interactive_json, null);
  // Shapes are validated when saved; anything older or malformed is skipped, never a 500.
  if (!validInteractive(data)) return "";
  if (data.kind === "reveal") {
    return html`<section class="mt-3" aria-label="${c.t("lesson.interactive")}"><h2 class="h2">${data.title || c.t("lesson.check_understanding")}</h2>
      ${data.cards.map((card) => html`<details class="panel mt-1"><summary><strong>${card.front}</strong></summary><p class="mt-1 mb-0">${card.back}</p></details>`)}</section>`;
  }
  if (data.kind === "checklist") {
    return html`<section class="mt-3 panel" aria-label="${data.title}"><h2 class="h2">${data.title}</h2>
      ${data.items.map((it, i) => html`<label class="check mt-1"><input type="checkbox" data-local-check="${lesson.id}:${i}"> <span>${it}</span></label>`)}
      <p class="tiny muted mt-2 mb-0">${c.t("lesson.checklist_local")}</p></section>`;
  }
  return "";
}

/** Media type of a direct (development-only) source, from its file extension. */
function fileVideoType(url) {
  const ext = /\.([a-z0-9]+)(?:[?#]|$)/i.exec(url)?.[1]?.toLowerCase();
  return { webm: "video/webm", mp4: "video/mp4", m4v: "video/mp4", mov: "video/quicktime" }[ext] || "video/mp4";
}

/**
 * Who a page of course material is licensed to: the learner's name and a
 * short account reference. Shown over the player and under the lesson text so
 * a recording or copy can be traced to its account. It cannot stop a
 * screenshot or screen recording; it makes one attributable.
 */
export function licenseMark(user) {
  if (!user) return "";
  return `${user.display_name || user.email?.split("@")[0] || "Learner"} · ${String(user.id).slice(-6).toUpperCase()}`;
}

// Protected lessons only: callers have already checked enrollment (or staff).
// Stream videos play in Stream's player from a short-lived signed token; no
// media URL, file name or download link is ever written into the page.
async function videoBlock(c, lesson, video, progress) {
  const t = c.t;
  if (video && isStreamVideo(video) && video.status === "approved" && !streamConfigured(c.env)) {
    // Fail closed: without the signing key there is no way to play a protected
    // video. The lesson still requires watching (watchRequired): it waits,
    // with the learner's progress kept, until playback is available again.
    console.warn(JSON.stringify({ event: "video_token", outcome: "unconfigured", lesson: lesson.id }));
    return html`<div class="video-pending" role="note"><div>${icon("alert", { size: 40 })}<h2>${t("lesson.video_unavailable")}</h2><p>${t("lesson.video_unavailable_body")}</p></div></div>`;
  }
  if (video?.playable) {
    const start = progress?.status !== "completed" ? Math.floor(progress?.position_seconds || 0) : 0;
    const stream = isStreamVideo(video);
    const signed = stream ? await playbackToken(c.env, video.provider_ref) : null;
    const captions = video.captions.filter((cap) => cap.status === "reviewed" || c.can("courses.edit"));
    return html`<div class="player${stream ? " player-stream" : ""}" data-player data-lesson="${lesson.id}" data-start="${start}"${stream ? raw(` data-stream data-expires="${signed.expiresAt}"`) : ""}>
        ${stream
          ? html`<iframe src="${iframeUrl(c.env, signed.token)}" title="${t("lesson.video_player", { title: lesson.title })}" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>
            <div class="player-mark" aria-hidden="true" data-license-mark>${licenseMark(c.user)}</div>`
          : html`<video controls playsinline preload="metadata" controlslist="nodownload" ${video.poster_url ? html`poster="${safeUrl(video.poster_url)}"` : ""} aria-label="${lesson.title}">
          ${video.hls_url ? html`<source src="${safeUrl(video.hls_url)}" type="application/vnd.apple.mpegurl">` : ""}
          ${video.mp4_url ? html`<source src="${safeUrl(video.mp4_url)}" type="${fileVideoType(video.mp4_url)}">` : ""}
          ${captions.map((cap, i) => html`<track kind="captions" src="/captions/${cap.id}.vtt" srclang="${cap.locale}" label="${cap.label}" ${cap.locale === c.locale || (i === 0 && !captions.some((x) => x.locale === c.locale)) ? raw("default") : ""}>`)}
          <p>${t("lesson.video_unsupported")}</p>
        </video>`}
      </div>
      <div class="player-bar no-print" data-player-bar>
        <label class="sr-only" for="speed">${t("lesson.speed")}</label>
        <span class="small muted">${icon("speed", { size: 16 })}</span>
        <select id="speed" data-speed>${[0.75, 1, 1.25, 1.5, 1.75, 2].map((s) => html`<option value="${s}" ${s === 1 ? raw("selected") : ""}>${s}×</option>`)}</select>
        ${isStreamVideo(video) ? "" : html`<button class="btn btn-quiet btn-sm" type="button" data-captions-toggle>${icon("captions", { size: 16 })} ${t("lesson.captions")}</button>`}
        <button class="btn btn-quiet btn-sm" type="button" data-fullscreen>${icon("maximize", { size: 16 })} ${t("lesson.fullscreen")}</button>
        <button class="btn btn-quiet btn-sm" type="button" data-bookmark-add>${icon("bookmark", { size: 16 })} ${t("lesson.bookmark_moment")}</button>
        <span class="tiny muted grow">${t("lesson.keyboard_hint")}</span>
      </div>
      ${video.presenter?.is_ai_avatar ? html`<p class="ai-disclosure small mt-1" data-ai-disclosure>${icon("sparkles", { size: 14 })} ${video.presenter.disclosure || t("lesson.ai_presenter", { name: video.presenter.name })}</p>` : ""}
      <p class="small muted mt-1" data-video-error hidden>${icon("alert", { size: 14 })} ${t("lesson.video_failed")}</p>`;
  }
  return html`<div class="video-pending" role="note">
    <div>${icon("play", { size: 40 })}
      <h2>${t("lesson.video_in_production")}</h2>
      <p>${t("lesson.video_in_production_body")}</p></div></div>`;
}

export async function lessonPage(c) {
  const t = c.t;
  const ctx = await loadContext(c);
  const { course, enrolled, syllabus, staff } = ctx;
  const lesson = await getLesson(c.env, course.id, c.params.lesson, c.locale);
  if (lesson.status !== "ready" && !staff) throw new HttpError(404, "not_found");
  // Lesson materials (text, video, captions, transcript, resources) are for
  // enrolled learners and staff only; the public course page stays the sample.
  if (!enrolled && !staff) {
    if (!c.user) return redirect(`/login?next=${encodeURIComponent(c.url.pathname)}`);
    return redirect(`/courses/${course.slug}`);
  }
  const canTrack = enrolled;
  const [progress, video, resources, notes, bookmarks, feedback, exam, cert] = await Promise.all([
    canTrack ? progressMap(c.env, c.user.id, course.id) : new Map(),
    getVideo(c.env, lesson.video_id, c.locale),
    c.env.DB.prepare("SELECT * FROM lesson_resources WHERE lesson_id = ? ORDER BY sort_order").bind(lesson.id).all(),
    c.user ? c.env.DB.prepare("SELECT * FROM notes WHERE user_id = ? AND lesson_id = ? ORDER BY created_at DESC").bind(c.user.id, lesson.id).all() : { results: [] },
    c.user ? c.env.DB.prepare("SELECT * FROM bookmarks WHERE user_id = ? AND lesson_id = ? ORDER BY position_seconds").bind(c.user.id, lesson.id).all() : { results: [] },
    c.user ? c.env.DB.prepare("SELECT helpful FROM lesson_feedback WHERE user_id = ? AND lesson_id = ?").bind(c.user.id, lesson.id).first() : null,
    certificationExam(c.env, course.id),
    c.user ? activeCertificate(c.env, c.user.id, course.id) : null,
  ]);
  if (canTrack) c.defer(track(c.env, c.user, "lesson_viewed", { courseId: course.id, lessonId: lesson.id, locale: c.locale }));
  const lp = progress.get(lesson.id);
  const idx = syllabus.lessons.findIndex((l) => l.id === lesson.id);
  const prev = syllabus.lessons[idx - 1];
  const next = syllabus.lessons[idx + 1];
  const doneCount = syllabus.lessons.filter((l) => progress.get(l.id)?.status === "completed").length;
  const pct = ctx.enrollment?.progress_pct || 0;
  const rendered = renderMarkdown(lesson.body_md, { headingOffset: 0 });
  const isQuizLesson = lesson.type === "quiz" && lesson.assessment_id;
  const assessment = isQuizLesson ? await c.env.DB.prepare("SELECT * FROM assessments WHERE id = ?").bind(lesson.assessment_id).first() : null;
  const transcript = video?.playable ? await reviewedTranscript(c, video) : "";
  const completed = lp?.status === "completed";
  // Same rule the server applies: any lesson with an approved, playable video completes by watching it.
  const mustWatch = await watchRequired(c.env, { ...lesson, video });
  const flash = c.url.searchParams.get("done") === "1";

  const sidebar = html`<aside class="class-sidebar" id="syllabus" data-sidebar aria-label="${t("lesson.course_contents")}">
    <header><a class="small" href="/courses/${course.slug}">${icon("arrow-left", { size: 14, cls: "ic-flip" })} ${t("lesson.course_overview")}</a>
      <h2 class="mt-1">${course.title}</h2>
      ${canTrack ? html`${progressBar(c, pct)}<p class="tiny muted mt-1 mb-0">${t("lesson.progress_summary", { done: doneCount, total: syllabus.lessons.length, pct })}</p>` : ""}
    </header>
    ${syllabus.modules.map(
      (m, mi) => html`<h3>${t("course.module_n", { n: mi + 1 })} · ${m.title}</h3><ol>${m.lessons.map((l) => {
        const done = progress.get(l.id)?.status === "completed";
        return html`<li class="${done ? "done" : ""}"><a href="/learn/${course.slug}/${l.slug}" ${l.id === lesson.id ? raw('aria-current="page"') : ""}>
          ${icon(done ? "check-circle" : lessonTypeIcon(l.type), { size: 18, label: done ? t("lesson.completed") : undefined })}
          <span>${l.title}<span class="lesson-meta">${t(`lesson.type.${l.type}`)} · ${t("duration.minutes", { n: l.est_minutes })}</span></span></a></li>`;
      })}</ol>`,
    )}
    ${exam && canTrack
      ? html`<h3>${t("lesson.final_assessment")}</h3><ol><li><a href="/assessments/${exam.id}">${icon(cert ? "award" : "target", { size: 18 })}<span>${exam.title}<span class="lesson-meta">${t("assess.passing_score")}: ${exam.passing_score}%</span></span></a></li></ol>`
      : ""}
  </aside>`;

  const tabs = [
    ["notes", "note", t("lesson.tab_notes")],
    ["bookmarks", "bookmark", t("lesson.tab_bookmarks")],
    ...(resources.results.length ? [["resources", "download", t("lesson.tab_resources")]] : []),
    ...(transcript ? [["transcript", "captions", t("lesson.tab_transcript")]] : []),
  ];

  const body = html`<div class="classroom">
    ${sidebar}
    <div class="class-main">
      <div class="class-top">
        <button class="icon-btn sidebar-toggle" type="button" data-sidebar-toggle aria-controls="syllabus" aria-expanded="false" aria-label="${t("lesson.course_contents")}">${icon("list", { size: 20 })}</button>
        <span class="title grow"${contentLang(c, lesson, "title")}>${lesson.title}</span>
        ${completed ? html`<span class="badge badge-green">${icon("check", { size: 12 })} ${t("lesson.completed")}</span>` : ""}
        ${next ? html`<a class="btn btn-secondary btn-sm" href="/learn/${course.slug}/${next.slug}">${t("lesson.next")} ${icon("chevron-right", { size: 16, cls: "ic-flip" })}</a>` : ""}
      </div>
      <article class="class-content" data-lesson-root data-lesson-id="${lesson.id}" data-lesson-type="${lesson.type}" data-track="${canTrack ? "1" : "0"}" data-completed="${completed ? "1" : "0"}">
        ${flash ? alert("success", t("lesson.marked_complete")) : ""}
        ${c.url.searchParams.get("watch") === "1" && !completed ? alert("info", t("lesson.watch_to_complete")) : ""}
        <p class="eyebrow">${icon(lessonTypeIcon(lesson.type), { size: 14 })} ${t(`lesson.type.${lesson.type}`)} · ${t("duration.minutes", { n: lesson.est_minutes })}</p>
        <h1 class="display-sm"${contentLang(c, lesson, "title")}>${lesson.title}</h1>
        ${translationNotice(c, lesson._tr)}
        ${lesson.type === "video" || lesson.video_id ? await videoBlock(c, lesson, video, lp) : ""}
        ${lesson.summary ? html`<p class="lead mt-3"${contentLang(c, lesson, "summary")}>${lesson.summary}</p>` : ""}
        ${rendered.toc.length > 2 ? html`<nav class="panel mt-2" aria-label="${t("lesson.on_this_page")}"><strong class="small">${t("lesson.on_this_page")}</strong>
          <ul class="small mb-0 toc-list">${rendered.toc.filter((h) => h.level <= 2).map((h) => html`<li><a href="#${h.id}">${h.text}</a></li>`)}</ul></nav>` : ""}
        <div class="prose mt-3"${contentLang(c, lesson, "body_md")}>${raw(rendered.html)}</div>
        ${c.user ? html`<p class="license-note tiny muted" data-license-note>${icon("lock", { size: 12 })} ${t("lesson.licensed_to", { name: licenseMark(c.user) })}</p>` : ""}
        ${interactive(c, lesson)}
        ${isQuizLesson && assessment
          ? html`<section class="panel mt-3"><h2 class="h2">${assessment.title}</h2><p>${assessment.instructions}</p>
              <dl class="kv"><dt>${t("assess.passing_score")}</dt><dd>${assessment.passing_score}%</dd>
              ${assessment.time_limit_seconds ? html`<dt>${t("assess.time_limit")}</dt><dd>${t("duration.minutes", { n: Math.round(assessment.time_limit_seconds / 60) })}</dd>` : ""}</dl>
              ${canTrack ? html`<a class="btn btn-primary mt-2" href="/assessments/${assessment.id}">${t("assess.open")}</a>` : ""}</section>`
          : ""}

        ${canTrack && !isQuizLesson
          ? html`<div class="complete-box no-print">
              <div><strong>${completed ? t("lesson.completed") : t("lesson.ready_to_complete")}</strong>
                <p class="small muted mb-0">${completed ? t("lesson.completed_on", { date: c.fmtDate(lp.completed_at, { dateStyle: "medium" }) }) : mustWatch ? t("lesson.video_autocomplete") : t("lesson.mark_hint")}</p></div>
              ${completed
                ? next
                  ? html`<a class="btn btn-primary" href="/learn/${course.slug}/${next.slug}">${t("lesson.next")} ${icon("arrow-right", { size: 16, cls: "ic-flip" })}</a>`
                  : exam
                    ? html`<a class="btn btn-primary" href="/assessments/${exam.id}">${t("lesson.go_to_exam")}</a>`
                    : ""
                : mustWatch
                  ? ""
                  : html`<form method="post" action="/learn/${course.slug}/${lesson.slug}/complete" data-complete-form>${csrfField(c)}
                    <button class="btn btn-primary" type="submit">${icon("check", { size: 16 })} ${t("lesson.mark_complete")}</button></form>`}
            </div>`
          : ""}

        ${c.user
          ? html`<div class="lesson-tabs no-print" role="tablist" aria-label="${t("lesson.tools")}">
              ${tabs.map(([id, ic, label], i) => html`<button role="tab" id="tab-${id}" aria-controls="panel-${id}" aria-selected="${i === 0 ? "true" : "false"}" tabindex="${i === 0 ? "0" : "-1"}" type="button">${icon(ic, { size: 16 })} ${label}</button>`)}
            </div>
            <section role="tabpanel" id="panel-notes" aria-labelledby="tab-notes" class="no-print">
              <form method="post" action="/learn/${course.slug}/${lesson.slug}/notes" data-note-form>${csrfField(c)}
                <label for="note-body">${t("lesson.add_note")}</label>
                <textarea id="note-body" name="body" maxlength="5000" required placeholder="${t("lesson.note_placeholder")}"></textarea>
                <input type="hidden" name="position" value="" data-note-position>
                <button class="btn btn-secondary btn-sm mt-1" type="submit">${t("lesson.save_note")}</button></form>
              <div data-notes-list>${notes.results.length ? notes.results.map((n) => noteItem(c, course, lesson, n)) : html`<p class="small muted mt-2" data-empty>${t("lesson.no_notes")}</p>`}</div>
            </section>
            <section role="tabpanel" id="panel-bookmarks" aria-labelledby="tab-bookmarks" hidden>
              <form method="post" action="/learn/${course.slug}/${lesson.slug}/bookmarks" class="row" data-bookmark-form>${csrfField(c)}
                <input type="hidden" name="position" value="0" data-bookmark-position>
                <label class="sr-only" for="bm-label">${t("lesson.bookmark_label")}</label>
                <input id="bm-label" name="label" maxlength="120" placeholder="${t("lesson.bookmark_label")}" class="grow">
                <button class="btn btn-secondary btn-sm" type="submit">${icon("bookmark", { size: 14 })} ${t("lesson.add_bookmark")}</button></form>
              <ul class="mt-2" data-bookmarks-list>${bookmarks.results.map((b) => html`<li><button class="link-btn" type="button" data-seek="${b.position_seconds}">${fmtTime(b.position_seconds)}</button> ${b.label}</li>`)}</ul>
              ${bookmarks.results.length ? "" : html`<p class="small muted">${t("lesson.no_bookmarks")}</p>`}
            </section>
            ${resources.results.length
              ? html`<section role="tabpanel" id="panel-resources" aria-labelledby="tab-resources" hidden><ul>${resources.results.map(
                  (r) => html`<li class="list-row">${icon(r.kind === "file" ? "download" : "external", { size: 18 })}<a class="grow" href="${r.kind === "file" ? `/resources/${r.id}` : safeUrl(r.url)}" rel="noopener">${r.title}</a>
                  ${r.size_bytes ? html`<span class="tiny muted">${Math.max(1, Math.round(r.size_bytes / 1024))} KB</span>` : ""}</li>`,
                )}</ul></section>`
              : ""}
            ${transcript ? html`<section role="tabpanel" id="panel-transcript" aria-labelledby="tab-transcript" hidden><div class="transcript prose"${transcript.lang !== c.displayLocale ? raw(` lang="${transcript.lang}" dir="${localeInfo(transcript.lang).dir}"`) : ""}>${transcript.paragraphs.map((p) => html`<p><button class="link-btn tiny muted" type="button" data-seek="${p.start}">${fmtTime(p.start)}</button> ${p.text}</p>`)}</div></section>` : ""}

            <section class="panel mt-3 no-print" aria-labelledby="fb-h">
              <h2 class="h2" id="fb-h">${t("lesson.helpful_q")}</h2>
              <form method="post" action="/learn/${course.slug}/${lesson.slug}/feedback" class="row">${csrfField(c)}
                <button class="btn ${feedback?.helpful === 1 ? "btn-primary" : "btn-secondary"} btn-sm" name="helpful" value="1" type="submit" aria-pressed="${feedback?.helpful === 1 ? "true" : "false"}">${t("lesson.helpful_yes")}</button>
                <button class="btn ${feedback?.helpful === 0 ? "btn-primary" : "btn-secondary"} btn-sm" name="helpful" value="0" type="submit" aria-pressed="${feedback?.helpful === 0 ? "true" : "false"}">${t("lesson.helpful_no")}</button>
                <label class="sr-only" for="fb-comment">${t("lesson.feedback_comment")}</label>
                <input id="fb-comment" class="grow" name="comment" maxlength="1000" placeholder="${t("lesson.feedback_comment")}">
              </form>
            </section>`
          : ""}

        <nav class="lesson-nav no-print" aria-label="${t("lesson.navigation")}">
          ${prev ? html`<a class="btn btn-quiet" href="/learn/${course.slug}/${prev.slug}">${icon("chevron-left", { size: 16, cls: "ic-flip" })} ${prev.title}</a>` : html`<span></span>`}
          ${next ? html`<a class="btn btn-secondary" href="/learn/${course.slug}/${next.slug}">${next.title} ${icon("chevron-right", { size: 16, cls: "ic-flip" })}</a>` : exam && canTrack ? html`<a class="btn btn-primary" href="/assessments/${exam.id}">${t("lesson.go_to_exam")}</a>` : ""}
        </nav>
      </article>
    </div>
  </div>`;
  return c.page({ title: `${lesson.title} · ${course.title}`, body, noindex: true, bodyClass: "in-classroom", streamPlayer: Boolean(video?.playable && isStreamVideo(video) && streamConfigured(c.env)) });
}

function fmtTime(s) {
  const n = Math.max(0, Math.floor(Number(s) || 0));
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
}

function noteItem(c, course, lesson, n) {
  return html`<div class="note-item" data-note="${n.id}">
    <div class="row-between"><time datetime="${n.created_at}">${c.fmtDate(n.created_at, { dateStyle: "medium", timeStyle: "short" })}${n.position_seconds != null ? ` · ${fmtTime(n.position_seconds)}` : ""}</time>
      <form method="post" action="/learn/${course.slug}/${lesson.slug}/notes/${n.id}/delete" data-note-delete>${csrfField(c)}<button class="link-btn tiny muted" type="submit">${c.t("action.delete")}</button></form></div>
    <p class="mb-0">${n.body}</p></div>`;
}

async function lessonForWrite(c) {
  const course = await getCourseBySlug(c.env, c.params.course, c.locale, { staff: c.can("courses.edit"), userId: c.user?.id });
  const lesson = await c.env.DB.prepare("SELECT * FROM lessons WHERE course_id = ? AND slug = ?").bind(course.id, c.params.lesson).first();
  if (!lesson) throw new HttpError(404, "not_found");
  return { course, lesson };
}

const wantsJson = (c) => (c.req.headers.get("accept") || "").includes("application/json");

export async function completeLesson(c) {
  const { course, lesson } = await lessonForWrite(c);
  // No position: the form neither moves the resume point nor counts as watching.
  const result = await recordProgress(c, lesson, { complete: true, clientAt: nowIso() });
  if (wantsJson(c)) return json({ ok: true, ...result, certificate: result.certificate?.credential_id || null });
  if (!result.completed) return redirect(`/learn/${course.slug}/${lesson.slug}?watch=1`);
  if (result.certificate) return redirect(`/certificates/${result.certificate.credential_id}?new=1`);
  const syllabus = await getSyllabus(c.env, course.id, c.locale);
  const idx = syllabus.lessons.findIndex((l) => l.id === lesson.id);
  const next = syllabus.lessons[idx + 1];
  return redirect(next ? `/learn/${course.slug}/${next.slug}` : `/learn/${course.slug}/${lesson.slug}?done=1`);
}

/** JSON progress beacon from the lesson page (video time, scroll, completion). */
export async function progressApi(c) {
  const b = await c.readBody();
  await rateLimit(c, "progress", { limit: 240, windowSeconds: 600, key: c.user.id });
  const reports = Array.isArray(b.reports) ? b.reports.slice(0, 50) : [b];
  const out = [];
  for (const r of reports) {
    const lesson = await c.env.DB.prepare("SELECT * FROM lessons WHERE id = ?").bind(String(r.lessonId || "")).first();
    if (!lesson) continue;
    try {
      const res = await recordProgress(c, lesson, r);
      out.push({ lessonId: lesson.id, completed: res.completed, progressPct: res.progressPct, certificate: res.certificate?.credential_id || null });
    } catch (e) {
      if (!(e instanceof HttpError)) throw e;
      out.push({ lessonId: lesson.id, error: e.code });
    }
  }
  return json({ ok: true, results: out });
}

export async function addNote(c) {
  const { course, lesson } = await lessonForWrite(c);
  const b = await c.readBody();
  await rateLimit(c, "notes", { limit: 120, windowSeconds: 3600, key: c.user.id });
  const text = String(b.body || "").trim().slice(0, 5000);
  if (!text) throw new HttpError(400, "empty_note");
  const pos = b.position === "" || b.position == null ? null : Math.max(0, Number(b.position) || 0);
  const now = nowIso();
  const note = { id: newId("nte_"), body: text, position_seconds: pos, created_at: now };
  await c.env.DB.prepare("INSERT INTO notes (id, user_id, lesson_id, body, position_seconds, created_at, updated_at) VALUES (?,?,?,?,?,?,?)").bind(note.id, c.user.id, lesson.id, text, pos, now, now).run();
  if (wantsJson(c)) return json({ ok: true, html: noteItem(c, course, lesson, note).toString() });
  return redirect(`/learn/${course.slug}/${lesson.slug}#panel-notes`);
}

export async function deleteNote(c) {
  const { course, lesson } = await lessonForWrite(c);
  await c.env.DB.prepare("DELETE FROM notes WHERE id = ? AND user_id = ?").bind(c.params.note, c.user.id).run();
  if (wantsJson(c)) return json({ ok: true });
  return redirect(`/learn/${course.slug}/${lesson.slug}#panel-notes`);
}

export async function addBookmark(c) {
  const { course, lesson } = await lessonForWrite(c);
  const b = await c.readBody();
  await rateLimit(c, "bookmarks", { limit: 120, windowSeconds: 3600, key: c.user.id });
  const pos = Math.max(0, Number(b.position) || 0);
  const label = String(b.label || "").trim().slice(0, 120);
  await c.env.DB.prepare("INSERT INTO bookmarks (id, user_id, lesson_id, position_seconds, label, created_at) VALUES (?,?,?,?,?,?)").bind(newId("bmk_"), c.user.id, lesson.id, pos, label, nowIso()).run();
  if (wantsJson(c)) return json({ ok: true, position: pos, label, time: fmtTime(pos) });
  return redirect(`/learn/${course.slug}/${lesson.slug}#panel-bookmarks`);
}

export async function lessonFeedback(c) {
  const { course, lesson } = await lessonForWrite(c);
  const b = await c.readBody();
  const helpful = b.helpful === "1" || b.helpful === 1 || b.helpful === true ? 1 : 0;
  await c.env.DB.prepare(
    `INSERT INTO lesson_feedback (user_id, lesson_id, helpful, comment, created_at) VALUES (?,?,?,?,?)
     ON CONFLICT(user_id, lesson_id) DO UPDATE SET helpful = excluded.helpful, comment = CASE WHEN excluded.comment != '' THEN excluded.comment ELSE comment END, created_at = excluded.created_at`,
  )
    .bind(c.user.id, lesson.id, helpful, String(b.comment || "").trim().slice(0, 1000), nowIso())
    .run();
  if (wantsJson(c)) return json({ ok: true });
  return redirect(`/learn/${course.slug}/${lesson.slug}`);
}

export async function courseFeedback(c) {
  const course = await getCourseBySlug(c.env, c.params.slug, c.locale, { userId: c.user?.id });
  const enr = await getEnrollment(c.env, c.user.id, course.id);
  if (!enr) throw new HttpError(403, "not_enrolled");
  const b = await c.readBody();
  const rating = Math.round(Number(b.rating));
  if (!(rating >= 1 && rating <= 5)) throw new HttpError(400, "invalid_rating");
  const now = nowIso();
  await c.env.DB.prepare(
    `INSERT INTO course_feedback (id, user_id, course_id, rating, comment, status, created_at, updated_at) VALUES (?,?,?,?,?, 'new', ?, ?)
     ON CONFLICT(user_id, course_id) DO UPDATE SET rating = excluded.rating, comment = excluded.comment, status = 'new', updated_at = excluded.updated_at`,
  )
    .bind(newId("cfb_"), c.user.id, course.id, rating, String(b.comment || "").trim().slice(0, 3000), now, now)
    .run();
  const back = typeof b.next === "string" && b.next.startsWith("/") && !b.next.startsWith("//") ? b.next : `/courses/${course.slug}`;
  return redirect(`${back}${back.includes("?") ? "&" : "?"}feedback=1`);
}

// Captions are lesson material: served only to someone entitled to a ready
// lesson that uses the video, never cached by shared caches, and unreviewed
// (machine) captions only to staff.
export async function captions(c) {
  const id = c.params.file.replace(/\.vtt$/, "");
  const row = await c.env.DB.prepare("SELECT id, video_id, vtt, status FROM video_captions WHERE id = ?").bind(id).first();
  const staff = c.can("courses.edit");
  if (!row || (row.status !== "reviewed" && !staff) || !(staff || (await entitledToVideo(c, row.video_id)))) throw new HttpError(404, "not_found");
  return new Response(row.vtt, { headers: { "Content-Type": "text/vtt; charset=utf-8", "Cache-Control": "private, no-store" } });
}

/** True when the signed-in learner holds an active enrollment in a course with a ready lesson using this video. */
async function entitledToVideo(c, videoId) {
  if (!c.user) return false;
  const row = await c.env.DB.prepare(
    `SELECT 1 FROM lessons l JOIN enrollments e ON e.course_id = l.course_id
      WHERE l.video_id = ? AND l.status = 'ready' AND e.user_id = ? AND e.status != 'withdrawn' LIMIT 1`,
  )
    .bind(videoId, c.user.id)
    .first();
  return Boolean(row);
}

/** Readable transcript from the reviewed captions of the final video (never the planning script). */
async function reviewedTranscript(c, video) {
  const rows = (await c.env.DB.prepare("SELECT locale, vtt FROM video_captions WHERE video_id = ? AND status = 'reviewed'").bind(video.id).all()).results;
  const pick = rows.find((r) => r.locale === c.locale) || rows.find((r) => r.locale === "en") || rows[0];
  if (!pick) return "";
  const paragraphs = vttParagraphs(pick.vtt);
  return paragraphs.length ? { lang: pick.locale, paragraphs } : "";
}

/** WebVTT cues → paragraphs of about 40 seconds, each with its start time. */
export function vttParagraphs(vtt) {
  const cues = [];
  for (const block of String(vtt || "").replace(/\r/g, "").split(/\n{2,}/)) {
    const lines = block.split("\n");
    const at = lines.findIndex((l) => l.includes("-->"));
    if (at < 0) continue;
    const m = /^(?:(\d+):)?(\d{1,2}):(\d{2})[.,]\d+/.exec(lines[at].trim());
    if (!m) continue;
    const text = lines.slice(at + 1).join(" ").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
    if (text) cues.push({ start: Number(m[1] || 0) * 3600 + Number(m[2]) * 60 + Number(m[3]), text });
  }
  const out = [];
  for (const cue of cues) {
    const last = out[out.length - 1];
    if (last && cue.start - last.start < 40) last.text += ` ${cue.text}`;
    else out.push({ ...cue });
  }
  return out;
}

// Fresh playback token for a protected video, for a player whose token expired
// mid-lesson. Same entitlement as the lesson page; rate limited; never cached.
export async function videoToken(c) {
  const b = await c.readBody();
  try {
    await rateLimit(c, "video_token", { limit: 60, windowSeconds: 600, key: c.user.id });
  } catch (e) {
    // Unusual playback volume is recorded for staff review (Admin → Audit log).
    if (e?.status === 429) await audit(c, "playback.rate_limited", "user", c.user.id, { lesson: String(b.lessonId || "").slice(0, 64) });
    throw e;
  }
  const lesson = await c.env.DB.prepare("SELECT l.id, l.course_id, l.status, l.video_id FROM lessons l WHERE l.id = ?").bind(String(b.lessonId || "")).first();
  const staff = c.can("courses.edit");
  const enr = lesson ? await getEnrollment(c.env, c.user.id, lesson.course_id) : null;
  const allowed = lesson && (staff || (lesson.status === "ready" && enr && enr.status !== "withdrawn"));
  const video = allowed ? await getVideo(c.env, lesson.video_id, c.locale) : null;
  const log = (outcome) => console.log(JSON.stringify({ event: "video_token", outcome, lesson: lesson?.id || null, staff }));
  if (!allowed) {
    log("denied");
    throw new HttpError(403, "not_enrolled");
  }
  if (!isStreamVideo(video) || video.status !== "approved") throw new HttpError(404, "not_found");
  const signed = await playbackToken(c.env, video.provider_ref);
  if (!signed) {
    log("unconfigured");
    throw new HttpError(503, "video_unavailable");
  }
  log("granted");
  return json({ ok: true, url: iframeUrl(c.env, signed.token), expiresAt: signed.expiresAt }, 200, { "Cache-Control": "private, no-store" });
}

export async function resourceDownload(c) {
  const r = await c.env.DB.prepare(
    `SELECT r.*, l.course_id FROM lesson_resources r JOIN lessons l ON l.id = r.lesson_id WHERE r.id = ?`,
  )
    .bind(c.params.id)
    .first();
  if (!r) throw new HttpError(404, "not_found");
  // Active (or completed) enrollment only: withdrawn learners lose access to private files.
  const enr = await getEnrollment(c.env, c.user.id, r.course_id);
  const active = enr && enr.status !== "withdrawn";
  if (!active && !c.can("courses.edit")) throw new HttpError(403, "not_enrolled");
  if (r.kind === "link") return redirect(safeUrl(r.url), 302);
  if (!c.env.FILES || !r.file_key) throw new HttpError(404, "not_found");
  const obj = await c.env.FILES.get(r.file_key);
  if (!obj) throw new HttpError(404, "not_found");
  return new Response(obj.body, {
    headers: {
      "Content-Type": r.mime || "application/octet-stream",
      "Content-Disposition": `attachment; filename="${r.title.replace(/[^\w.-]+/g, "_").slice(0, 80)}${(/\.[a-z0-9]+$/.exec(r.file_key) || [""])[0]}"`,
      "Cache-Control": "private, no-store",
    },
  });
}
