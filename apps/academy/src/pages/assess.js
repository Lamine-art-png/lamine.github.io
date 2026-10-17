// Assessment pages: intro and policy, the timed exam interface, autosave,
// submission, and results with policy-controlled feedback.
import { html, raw } from "../lib/html.js";
import { redirect, json, HttpError } from "../lib/http.js";
import { rateLimit } from "../lib/security.js";
import { md } from "../lib/markdown.js";
import { icon } from "../views/icons.js";
import { csrfField, alert, ring, breadcrumbs, emptyState } from "../views/components.js";
import { localize } from "../services/content.js";
import { getAssessment, attemptGate, startAttempt, getOwnAttempt, attemptQuestions, saveResponses, submitAttempt, attemptReview, attemptHistory } from "../services/assessments.js";
import { activeCertificate } from "../services/certificates.js";

async function courseOf(env, id) {
  return env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(id).first();
}

export async function intro(c) {
  const t = c.t;
  const a = await getAssessment(c.env, c.params.id);
  await localize(c.env, "assessment", a, ["title", "instructions"], c.locale);
  const course = await courseOf(c.env, a.course_id);
  const gate = await attemptGate(c.env, c.user, a, course);
  const history = gate.history || (await attemptHistory(c.env, c.user.id, a.id));
  const cert = a.is_certification ? await activeCertificate(c.env, c.user.id, course.id) : null;
  const err = c.url.searchParams.get("error");
  const used = history.length;

  const body = html`<section class="page-head"><div class="wrap narrow">
    ${breadcrumbs([[c.t("nav.dashboard"), "/dashboard"], [course.title, `/learn/${course.slug}`], [a.title]])}
    <p class="eyebrow">${a.kind === "exam" ? t("assess.final_exam") : t("assess.quiz")}</p>
    <h1 class="display-sm">${a.title}</h1>
    ${a.instructions ? html`<div class="lead">${md(a.instructions)}</div>` : ""}
  </div></section>
  <section class="section-tight"><div class="wrap narrow">
    ${err ? alert("error", t(err.startsWith("assess.") ? err : `assess.error.${err}`)) : ""}
    ${cert ? alert("success", html`${t("assess.already_certified")} <a href="/certificates/${cert.credential_id}">${t("course.view_certificate")}</a>`) : ""}
    <div class="cards cards-4">
      <div class="stat"><span class="value">${a.passing_score}%</span><span class="label">${t("assess.passing_score")}</span></div>
      <div class="stat"><span class="value">${a.time_limit_seconds ? Math.round(a.time_limit_seconds / 60) : "—"}</span><span class="label">${a.time_limit_seconds ? t("assess.minutes_limit") : t("assess.no_time_limit")}</span></div>
      <div class="stat"><span class="value">${a.max_attempts ? `${used}/${a.max_attempts}` : used}</span><span class="label">${t("assess.attempts_used")}</span></div>
      <div class="stat"><span class="value">${t(`assess.feedback.${a.feedback_policy}.short`)}</span><span class="label">${t("assess.feedback_label")}</span></div>
    </div>
    <div class="panel mt-3">
      <h2 class="h2">${t("assess.before_you_begin")}</h2>
      <ul class="check-list">
        ${a.time_limit_seconds ? html`<li>${icon("timer", { size: 18 })} ${t("assess.rule_timer")}</li>` : ""}
        <li>${icon("check-circle", { size: 18 })} ${t("assess.rule_autosave")}</li>
        <li>${icon("shield", { size: 18 })} ${t("assess.rule_server")}</li>
        ${a.is_certification ? html`<li>${icon("award", { size: 18 })} ${t("assess.rule_certificate", { score: a.passing_score })}</li>` : ""}
        ${a.cooldown_minutes ? html`<li>${icon("clock", { size: 18 })} ${t("assess.rule_cooldown", { n: a.cooldown_minutes })}</li>` : ""}
        ${a.is_certification && c.locale !== "en" ? html`<li>${icon("globe", { size: 18 })} ${t("assess.rule_reviewed_translations")}</li>` : ""}
      </ul>
      ${gate.ok
        ? html`<form method="post" action="/assessments/${a.id}/start" class="mt-3">${csrfField(c)}
            <button class="btn btn-primary btn-lg" type="submit">${gate.resume ? t("assess.resume") : used ? t("assess.retake") : t("assess.begin")} ${icon("arrow-right", { size: 18, cls: "ic-flip" })}</button></form>`
        : html`${alert("warn", html`${t(gate.reason, { date: gate.readyAt ? c.fmtDate(gate.readyAt, { dateStyle: "medium", timeStyle: "short" }) : "", done: gate.lessons?.done, total: gate.lessons?.required })}`)}
            ${gate.reason === "assess.gate.lessons" ? html`<a class="btn btn-secondary" href="/learn/${course.slug}">${t("course.continue")}</a>` : ""}`}
    </div>
    ${history.length
      ? html`<h2 class="h2 mt-4">${t("assess.history")}</h2>
        <div class="admin-table"><table><thead><tr><th>${t("assess.attempt")}</th><th>${t("assess.date")}</th><th>${t("assess.score")}</th><th>${t("assess.result")}</th><th></th></tr></thead><tbody>
        ${history.map(
          (h) => html`<tr><td>#${h.attempt_no}</td><td>${c.fmtDate(h.submitted_at || h.started_at, { dateStyle: "medium", timeStyle: "short" })}</td>
            <td>${h.score_pct != null ? `${c.fmtNum(h.score_pct, { maximumFractionDigits: 1 })}%` : "—"}</td>
            <td>${h.status === "graded" ? (h.passed ? html`<span class="badge badge-green">${t("assess.passed")}</span>` : html`<span class="badge badge-danger">${t("assess.not_passed")}</span>`) : html`<span class="badge badge-warn">${t(`assess.status.${h.status}`)}</span>`}</td>
            <td><a href="/attempts/${h.id}">${h.status === "in_progress" ? t("assess.resume") : t("assess.view")}</a></td></tr>`,
        )}</tbody></table></div>`
      : ""}
  </div></section>`;
  return c.page({ title: a.title, body, noindex: true });
}

export async function start(c) {
  const a = await getAssessment(c.env, c.params.id);
  const course = await courseOf(c.env, a.course_id);
  await rateLimit(c, "attempt-start", { limit: 30, windowSeconds: 3600, key: c.user.id });
  try {
    const attempt = await startAttempt(c, a, course);
    return redirect(`/attempts/${attempt.id}`);
  } catch (e) {
    if (e instanceof HttpError && e.status === 409) return redirect(`/assessments/${a.id}?error=${encodeURIComponent(e.extra?.reason || e.code)}`);
    throw e;
  }
}

function questionBlock(c, q) {
  const t = c.t;
  const name = `q[${q.id}]`;
  const r = q.response;
  const head = html`<span class="q-num">${t("assess.question_n", { n: q.n })} · ${t("assess.points", { n: q.points })}</span>${q.prompt}`;
  const caseBlock = q.caseBody ? html`<div class="q-case">${q.caseTitle ? html`<strong>${q.caseTitle}</strong>` : ""}${md(q.caseBody)}</div>` : "";
  let control;
  switch (q.type) {
    case "single":
      control = q.options.map((o) => html`<label class="option"><input type="radio" name="${name}" value="${o.id}" ${r === o.id ? raw("checked") : ""}> <span>${o.text}</span></label>`);
      break;
    case "multiple":
      control = html`<p class="small muted">${t("assess.select_all")}</p>${q.options.map(
        (o) => html`<label class="option"><input type="checkbox" name="${name}" value="${o.id}" ${Array.isArray(r) && r.includes(o.id) ? raw("checked") : ""}> <span>${o.text}</span></label>`,
      )}`;
      break;
    case "true_false":
      control = [
        ["true", t("assess.true")],
        ["false", t("assess.false")],
      ].map(([v, l]) => html`<label class="option"><input type="radio" name="${name}" value="${v}" ${String(r) === v ? raw("checked") : ""}> <span>${l}</span></label>`);
      break;
    case "matching":
      control = html`<p class="small muted">${t("assess.match_hint")}</p>${q.left.map(
        (l) => html`<div class="match-row"><label for="m-${q.id}-${l.id}">${l.text}</label>
          <select id="m-${q.id}-${l.id}" name="m[${q.id}][${l.id}]"><option value="">${t("form.choose")}</option>
          ${q.right.map((o) => html`<option value="${o.id}" ${r && r[l.id] === o.id ? raw("selected") : ""}>${o.text}</option>`)}</select></div>`,
      )}`;
      break;
    case "ordering": {
      const current = Array.isArray(r) ? r : q.items.map((i) => i.id);
      const items = current.map((id) => q.items.find((i) => i.id === id)).filter(Boolean);
      control = html`<p class="small muted">${t("assess.order_hint")}</p><ol class="order-list" data-order-list>${items.map(
        (it, i) => html`<li data-item="${it.id}"><span class="grow">${it.text}</span>
          <label class="sr-only" for="o-${q.id}-${it.id}">${t("assess.position_of", { item: it.text })}</label>
          <select id="o-${q.id}-${it.id}" name="o[${q.id}][${it.id}]">${items.map((_, p) => html`<option value="${p + 1}" ${p === i ? raw("selected") : ""}>${p + 1}</option>`)}</select></li>`,
      )}</ol>`;
      break;
    }
    case "short_answer":
      control = html`<label class="sr-only" for="sa-${q.id}">${t("assess.your_answer")}</label><textarea id="sa-${q.id}" name="${name}" maxlength="${q.maxLength}" rows="5">${r || ""}</textarea>`;
      break;
    default:
      control = "";
  }
  return html`<fieldset class="question" id="q-${q.id}" data-question="${q.id}"><legend>${head}</legend>${caseBlock}${control}</fieldset>`;
}

export async function attemptPage(c) {
  const t = c.t;
  const attempt = await getOwnAttempt(c.env, c.user.id, c.params.id);
  const a = await getAssessment(c.env, attempt.assessment_id);
  await localize(c.env, "assessment", a, ["title", "instructions"], attempt.locale);
  const course = await courseOf(c.env, a.course_id);

  if (attempt.status === "in_progress") {
    if (attempt.deadline_at && new Date(attempt.deadline_at).getTime() + 30_000 < Date.now()) {
      await submitAttempt(c, attempt, { auto: true });
      return redirect(`/attempts/${attempt.id}?expired=1`);
    }
    const questions = await attemptQuestions(c.env, attempt, a);
    const anyEnglish = c.locale !== "en" && questions.some((q) => q.translation?.status === "missing");
    const body = html`<div class="exam-shell" data-exam data-attempt="${attempt.id}" data-server-now="${new Date().toISOString()}" ${attempt.deadline_at ? raw(`data-deadline="${attempt.deadline_at}"`) : ""}>
      <div class="exam-status"><div class="row-between">
        <div class="grow"><strong>${a.title}</strong><div class="tiny muted"><span data-answered>0</span>/${questions.length} ${t("assess.answered")} · <span class="save-state" data-save-state data-saving="${t("assess.saving")}" aria-live="polite">${t("assess.autosave_on")}</span></div></div>
        ${attempt.deadline_at ? html`<span class="timer" data-timer role="timer" aria-live="off" aria-label="${t("assess.time_remaining")}">${icon("timer", { size: 18 })}<span data-timer-text>--:--</span></span>` : ""}
      </div></div>
      ${anyEnglish ? alert("info", t(a.is_certification ? "assess.reviewed_only_notice" : "i18n.content_in_english")) : ""}
      <form method="post" action="/attempts/${attempt.id}/submit" data-exam-form>
        ${csrfField(c)}
        ${questions.map((q) => questionBlock(c, q))}
        <div class="panel row-between">
          <p class="mb-0 small muted">${t("assess.submit_note")}</p>
          <button class="btn btn-primary btn-lg" type="submit" data-confirm="${t("assess.submit_confirm")}">${t("assess.submit")}</button>
        </div>
      </form>
    </div>`;
    return c.page({ title: a.title, body, noindex: true });
  }

  // Results.
  const review = await attemptReview(c.env, attempt, a);
  const cert = a.is_certification && attempt.passed ? await activeCertificate(c.env, c.user.id, course.id) : null;
  const gate = await attemptGate(c.env, c.user, a, course);
  const pending = attempt.status === "pending_review";
  const body = html`<div class="exam-shell">
    ${breadcrumbs([[course.title, `/learn/${course.slug}`], [a.title, `/assessments/${a.id}`], [t("assess.attempt_n", { n: attempt.attempt_no })]])}
    ${c.url.searchParams.get("expired") === "1" ? alert("warn", t("assess.auto_submitted")) : ""}
    <section class="result-hero">
      ${pending
        ? html`${icon("clock", { size: 48 })}<h1 class="display-sm">${t("assess.pending_title")}</h1><p class="lead">${t("assess.pending_body")}</p>`
        : html`${ring(c, attempt.score_pct, t("assess.score"))}
          <h1 class="display-sm">${attempt.passed ? t("assess.pass_title") : t("assess.fail_title")}</h1>
          <p class="lead">${t("assess.result_summary", { score: c.fmtNum(attempt.score_pct, { maximumFractionDigits: 1 }), pass: a.passing_score })}</p>`}
    </section>
    ${cert
      ? html`<div class="cta-band"><div><h2>${t("assess.cert_earned")}</h2><p>${t("assess.cert_earned_body")}</p></div>
          <a class="btn btn-primary btn-lg" href="/certificates/${cert.credential_id}">${icon("award", { size: 18 })} ${t("course.view_certificate")}</a></div>`
      : attempt.passed && a.is_certification && !c.user.email_verified_at
        ? alert("warn", t("cert.reason.verify_email"))
        : ""}
    <div class="actions">
      <a class="btn btn-secondary" href="/learn/${course.slug}">${t("assess.back_to_course")}</a>
      ${!attempt.passed && gate.ok && !gate.resume ? html`<form method="post" action="/assessments/${a.id}/start">${csrfField(c)}<button class="btn btn-primary" type="submit">${t("assess.retake")}</button></form>` : ""}
      ${!attempt.passed && !gate.ok ? html`<span class="small muted">${t(gate.reason, { date: gate.readyAt ? c.fmtDate(gate.readyAt, { dateStyle: "medium", timeStyle: "short" }) : "" })}</span>` : ""}
    </div>
    ${review.reviewLessons.length
      ? html`<section class="panel mt-3"><h2 class="h2">${t("assess.review_recommended")}</h2><ul>${review.reviewLessons.map((l) => html`<li><a href="/learn/${course.slug}/${l.slug}">${l.title}</a></li>`)}</ul></section>`
      : ""}
    ${a.feedback_policy !== "score"
      ? html`<h2 class="h2 mt-4">${t("assess.question_review")}</h2>
        ${review.items.map(
          (it) => html`<div class="feedback-item ${it.status === "partial" ? "incorrect" : it.status}">
            <div class="row-between"><span class="q-num">${t("assess.question_n", { n: it.n })}</span>
              <span class="badge ${it.status === "correct" ? "badge-green" : it.status === "pending" ? "badge-warn" : "badge-danger"}">${t(`assess.item.${it.status}`)}${it.points != null ? ` · ${c.fmtNum(it.points, { maximumFractionDigits: 2 })}/${it.max}` : ""}</span></div>
            <p class="mb-1"><strong>${it.prompt}</strong></p>
            ${it.yourAnswer != null ? html`<p class="small mb-1">${t("assess.your_answer")}: ${it.yourAnswer === "true" ? t("assess.true") : it.yourAnswer === "false" ? t("assess.false") : it.yourAnswer}</p>` : ""}
            ${it.correctAnswer ? html`<p class="small mb-1">${t("assess.correct_answer")}: ${it.correctAnswer === "true" ? t("assess.true") : it.correctAnswer === "false" ? t("assess.false") : it.correctAnswer}</p>` : ""}
            ${it.explanation ? html`<p class="small muted mb-1">${it.explanation}</p>` : ""}
            ${it.reviewerComment ? html`<p class="small mb-1">${t("assess.reviewer_comment")}: ${it.reviewerComment}</p>` : ""}
            ${it.lesson && it.status !== "correct" ? html`<a class="small" href="/learn/${course.slug}/${it.lesson.slug}">${t("assess.review_lesson", { lesson: it.lesson.title })}</a>` : ""}
          </div>`,
        )}`
      : html`<p class="muted mt-3">${t("assess.feedback.score.long")}</p>`}
    ${review.items.length ? "" : emptyState({ title: t("assess.no_questions") })}
  </div>`;
  return c.page({ title: `${a.title} — ${t("assess.results")}`, body, noindex: true });
}

/** Convert form fields (q[...], m[...][...], o[...][...]) into a responses object. */
export function parseResponses(body) {
  const out = {};
  const orders = {};
  for (const [k, v] of Object.entries(body || {})) {
    let m;
    if ((m = /^q\[([\w-]+)\]$/.exec(k))) out[m[1]] = v;
    else if ((m = /^m\[([\w-]+)\]\[([\w-]+)\]$/.exec(k))) {
      if (v !== "") (out[m[1]] ||= {})[m[2]] = v;
    } else if ((m = /^o\[([\w-]+)\]\[([\w-]+)\]$/.exec(k))) (orders[m[1]] ||= []).push([m[2], Number(v)]);
  }
  for (const [qid, pairs] of Object.entries(orders)) out[qid] = pairs.sort((a, b) => a[1] - b[1]).map((p) => p[0]);
  return out;
}

export async function saveApi(c) {
  const attempt = await getOwnAttempt(c.env, c.user.id, c.params.id);
  await rateLimit(c, "attempt-save", { limit: 600, windowSeconds: 3600, key: c.user.id });
  const b = await c.readBody();
  const n = await saveResponses(c.env, attempt, b.responses && typeof b.responses === "object" ? b.responses : parseResponses(b));
  return json({ ok: true, saved: n, at: new Date().toISOString() });
}

export async function submit(c) {
  const attempt = await getOwnAttempt(c.env, c.user.id, c.params.id);
  const b = await c.readBody();
  const result = await submitAttempt(c, attempt, { responses: parseResponses(b) });
  if (result.certificate) return redirect(`/certificates/${result.certificate.credential_id}?new=1`);
  return redirect(`/attempts/${attempt.id}`);
}
