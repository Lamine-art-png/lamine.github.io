// Admin: courses (with publication readiness checks), modules, lessons,
// resources, videos and captions, instructors, programs and learning paths.
import { html, raw } from "../../lib/html.js";
import { redirect, HttpError } from "../../lib/http.js";
import { newId, nowIso, parseJson, slugify } from "../../lib/util.js";
import { audit, auditStmt } from "../../lib/security.js";
import { renderMarkdown } from "../../lib/markdown.js";
import { adminPage, table, statusBadge, hidden, input, textarea, select, checkbox, bool, str, intOrNull } from "./shell.js";
import { TOPICS } from "../public.js";
import { PROFESSIONAL_ROLES } from "../../services/users.js";
import { LOCALES } from "../../lib/i18n.js";
import { publishReadiness, recordReview, REVIEW_TYPES, REVIEW_DECISIONS } from "../../services/readiness.js";
import { draftCourse, draftChanged, latestRevision, liveToDraftStatements, publishDraft, pruneFiles, DraftChangedError } from "../../services/drafts.js";

export { publishReadiness };

const LESSON_TYPES = ["video", "text", "interactive", "reading", "resource", "exercise", "quiz", "case_study", "assignment"];
const COURSE_STATUSES = ["draft", "review", "scheduled", "published", "archived"];

// ───────────── Courses ─────────────

export async function courses(c) {
  const rows = (
    await c.env.DB.prepare(
      `SELECT c.id, c.status, c.scheduled_at, d.slug, d.title, d.planned_release_date, p.code AS program_code,
              (SELECT COUNT(*) FROM draft_lessons l WHERE l.course_id = c.id) AS lessons,
              (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.id) AS enrolled
         FROM courses c JOIN draft_courses d ON d.id = c.id LEFT JOIN programs p ON p.id = d.program_id ORDER BY COALESCE(p.sort_order, 99), d.sort_order`,
    ).all()
  ).results;
  const body = table(
    ["Program", "Course", "Status", "Planned / scheduled", "Lessons", "Enrolled", ""],
    rows.map(
      (r) => html`<tr><td>${r.program_code || "—"}</td><td class="wrap-cell"><a href="/admin/courses/${r.id}"><strong>${r.title}</strong></a><div class="tiny muted">/${r.slug}</div></td>
        <td>${statusBadge(r.status)}</td><td>${(r.scheduled_at || r.planned_release_date || "").slice(0, 16).replace("T", " ") || "—"}</td><td>${r.lessons}</td><td>${r.enrolled}</td>
        <td><a href="/courses/${r.slug}">View</a></td></tr>`,
    ),
  );
  return adminPage(c, { title: "Courses", active: "/admin/courses", body, actions: html`<a class="btn btn-primary btn-sm" href="/admin/courses/new">New course</a>` });
}

export async function newCourse(c) {
  const programs = (await c.env.DB.prepare("SELECT id, title FROM programs ORDER BY sort_order").all()).results;
  const body = html`<form class="form-card" method="post" action="/admin/courses">${hidden(c)}
    ${input("title", "Title", "", { required: true })}
    ${select("program_id", "Program", [["", "None"], ...programs.map((p) => [p.id, p.title])], "")}
    ${select("level", "Level", ["beginner", "intermediate", "advanced"], "beginner")}
    <button class="btn btn-primary">Create draft</button></form>`;
  return adminPage(c, { title: "New course", active: "/admin/courses", body });
}

/** A course slug is taken if any other course uses it live or in its draft. */
async function slugTaken(env, slug, exceptId = "") {
  return env.DB.prepare("SELECT 1 FROM courses WHERE slug = ?1 AND id != ?2 UNION ALL SELECT 1 FROM draft_courses WHERE slug = ?1 AND id != ?2").bind(slug, exceptId).first();
}

export async function createCourse(c) {
  const b = await c.readBody();
  const title = str(b.title, 200);
  if (!title) return redirect("/admin/courses/new?err=Title%20is%20required");
  let slug = slugify(title) || newId("course-").toLowerCase();
  if (await slugTaken(c.env, slug)) slug = `${slug}-${Date.now().toString(36)}`;
  const id = newId("crs_");
  const now = nowIso();
  await c.env.DB.batch([
    c.env.DB.prepare("INSERT INTO courses (id, slug, program_id, title, level, status, created_by, created_at, updated_at) VALUES (?,?,?,?,?, 'draft', ?, ?, ?)").bind(
      id,
      slug,
      b.program_id || null,
      title,
      ["beginner", "intermediate", "advanced"].includes(b.level) ? b.level : "beginner",
      c.user.id,
      now,
      now,
    ),
    c.env.DB.prepare("INSERT INTO draft_courses (id, slug, program_id, title, level, updated_at, updated_by) SELECT id, slug, program_id, title, level, updated_at, ? FROM courses WHERE id = ?").bind(c.user.id, id),
    auditStmt(c.env, c.user.id, "course.create", "course", id, { title }),
  ]);
  return redirect(`/admin/courses/${id}?ok=created`);
}

export async function editCourse(c) {
  const course = await draftCourse(c.env, c.params.id);
  if (!course) throw new HttpError(404, "not_found");
  const [programs, modules, lessons, instructors, linked, allCourses, prereqs, assessments, readiness, revision] = await Promise.all([
    c.env.DB.prepare("SELECT id, title FROM programs ORDER BY sort_order").all(),
    c.env.DB.prepare("SELECT * FROM draft_modules WHERE course_id = ? ORDER BY sort_order, created_at").bind(course.id).all(),
    c.env.DB.prepare("SELECT l.*, v.status AS video_status FROM draft_lessons l LEFT JOIN video_assets v ON v.id = l.video_id WHERE l.course_id = ? ORDER BY l.sort_order, l.created_at").bind(course.id).all(),
    c.env.DB.prepare("SELECT id, name FROM instructors ORDER BY sort_order").all(),
    c.env.DB.prepare("SELECT instructor_id FROM draft_course_instructors WHERE course_id = ?").bind(course.id).all(),
    c.env.DB.prepare("SELECT id, title FROM courses WHERE id != ? ORDER BY title").bind(course.id).all(),
    c.env.DB.prepare("SELECT * FROM draft_course_prerequisites WHERE course_id = ?").bind(course.id).all(),
    c.env.DB.prepare("SELECT * FROM draft_assessments WHERE course_id = ? ORDER BY kind DESC, created_at").bind(course.id).all(),
    publishReadiness(c.env, course),
    latestRevision(c.env, course.id),
  ]);
  // A released course changes for learners only by publishing a reviewed revision.
  const released = Boolean(course.published_at);
  const unpublished = released && revision?.content_hash !== readiness.hash;
  const linkedIds = new Set(linked.results.map((r) => r.instructor_id));
  const objectives = parseJson(course.objectives_json, []);
  const audience = new Set(parseJson(course.audience_json, []));
  const topics = new Set(parseJson(course.topics_json, []));
  const pre = new Map(prereqs.results.map((p) => [p.prerequisite_course_id, p]));

  const body = html`
  <section class="panel"><div class="row-between"><div><strong>Status:</strong> ${statusBadge(course.status)}
      ${course.scheduled_at ? html`<span class="small"> · publishes ${course.scheduled_at.slice(0, 16).replace("T", " ")} UTC</span>` : ""}
      ${course.published_at ? html`<span class="small"> · published ${course.published_at.slice(0, 10)}</span>` : ""}</div>
    <a class="btn btn-sm btn-quiet" href="/courses/${course.slug}">View live course page</a></div>
    ${released
      ? html`<div class="alert ${unpublished ? "alert-warn" : "alert-info"} mt-2" id="revision">
          <p class="small mb-0">${revision ? `Live content is revision ${revision.number}, published ${revision.published_at.slice(0, 10)}.` : "Live content was released before revisions were recorded."}
          ${unpublished
            ? "This draft has unpublished changes. Learners keep seeing the live revision until the changes pass every check below (including fresh reviews) and are published."
            : "The draft matches the live revision."}</p>
          ${unpublished
            ? html`<div class="row mt-1">${c.can("courses.publish") && course.status === "published"
                ? html`<form method="post" action="/admin/courses/${course.id}/status" class="inline">${hidden(c)}<input type="hidden" name="status" value="published"><button class="btn btn-primary btn-sm" ${readiness.ok ? "" : raw("disabled")}>Publish changes as revision ${(revision?.number || 0) + 1}</button></form>`
                : ""}
              <form method="post" action="/admin/courses/${course.id}/discard" class="inline" data-confirm="Discard every unpublished change and return the draft to the live content?">${hidden(c)}<button class="btn btn-danger btn-sm">Discard unpublished changes</button></form></div>`
            : ""}</div>`
      : html`<p class="tiny muted mt-1">Not yet released: edits appear on the upcoming course page straight away. Once published, edits are kept as a draft until they are reviewed and published again.</p>`}
    <h2 class="h2 mt-2">Publication readiness</h2>
    <ul class="check-list">${readiness.checks.map((ch) => html`<li><span aria-hidden="true">${ch.ok ? (ch.warn ? "⚠️" : "✅") : "❌"}</span> <span>${ch.label}</span></li>`)}</ul>
    <form method="post" action="/admin/courses/${course.id}/status" class="row mt-2">${hidden(c)}
      <label for="st" class="mb-0">Change status</label>
      <select id="st" name="status">${COURSE_STATUSES.map((s) => html`<option value="${s}" ${s === course.status ? raw("selected") : ""}>${s}</option>`)}</select>
      <label for="sched" class="mb-0">Publish at (UTC, for “scheduled”)</label><input id="sched" type="datetime-local" name="scheduled_at" value="${(course.scheduled_at || "").slice(0, 16)}">
      <button class="btn btn-primary btn-sm">Apply</button></form>
    <p class="tiny muted mt-1">Publishing and scheduling require every check above to pass. “Review” shows the course as upcoming without opening enrollment.</p>
  </section>

  <section class="form-card mt-3" id="reviews"><h2 class="h2">Mandatory reviews</h2>
    <p class="small muted">Each decision is recorded against the exact draft content at that moment. Editing lessons, assessments or questions afterwards voids earlier approvals until they are recorded again.</p>
    ${table(
      ["Review", "Current state", "History"],
      readiness.reviews.map(
        (r) => html`<tr><td class="wrap-cell">${r.label}</td><td>${statusBadge(r.state)}</td>
          <td class="wrap-cell tiny">${r.history.length
            ? r.history.slice(0, 3).map((h) => html`<div>${h.created_at.slice(0, 16).replace("T", " ")} · ${h.decision.replace("_", " ")} · ${h.reviewer_name || h.reviewer_display || "unknown"}${h.notes ? html` — ${h.notes}` : ""}</div>`)
            : "—"}</td></tr>`,
      ),
    )}
    ${c.can("courses.review")
      ? html`<form method="post" action="/admin/courses/${course.id}/reviews" class="mt-2">${hidden(c)}
        <div class="grid-2">
          ${select("review_type", "Review", readiness.reviews.map((r) => [r.type, r.label]), "")}
          ${select("decision", "Decision", [["approved", "Approve the current content"], ["changes_requested", "Request changes"]], "approved")}
          ${input("reviewer_name", "Reviewer (name and role, if different from your account)", "", { hint: "For example an external faculty member whose review you are recording." })}
        </div>
        ${textarea("notes", "Notes", "", { rows: 3, hint: "Required when requesting changes." })}
        ${checkbox("confirm", "I confirm this review covered the course content as it is now", false)}
        <button class="btn btn-secondary btn-sm">Record review decision</button></form>`
      : html`<p class="small muted">Recording review decisions requires the reviewer permission (super admin, academy admin or instructor).</p>`}
  </section>

  <form class="form-card mt-3" method="post" action="/admin/courses/${course.id}">${hidden(c)}
    <h2 class="h2">Course details</h2>
    <div class="grid-2">${input("title", "Title", course.title, { required: true })}${input("slug", "URL slug", course.slug, { required: true, hint: "Lowercase letters, numbers and hyphens." })}</div>
    ${input("subtitle", "Subtitle", course.subtitle)}
    ${textarea("description", "Description", course.description, { rows: 6, hint: "Separate paragraphs with a blank line." })}
    ${textarea("objectives", "Learning objectives", objectives.join("\n"), { rows: 5, hint: "One objective per line." })}
    <div class="grid-2">
      ${select("program_id", "Program", [["", "None"], ...programs.results.map((p) => [p.id, p.title])], course.program_id)}
      ${select("level", "Level", ["beginner", "intermediate", "advanced"], course.level)}
      ${input("duration_minutes", "Duration (minutes)", course.duration_minutes, { type: "number", attrs: 'min="0" max="10000"' })}
      ${select("source_locale", "Source language", LOCALES.map((l) => [l.code, l.englishName]), course.source_locale)}
      ${input("planned_release_date", "Planned release date (shown while upcoming)", course.planned_release_date, { type: "date" })}
      ${input("sort_order", "Sort order", course.sort_order, { type: "number" })}
    </div>
    ${input("thumbnail_url", "Thumbnail image URL", course.thumbnail_url, { hint: "Leave empty to use generated artwork. Use licensed images only." })}
    ${textarea("prerequisites_text", "Prerequisites (free text)", course.prerequisites_text, { rows: 2 })}
    <fieldset><legend>Audience</legend><div class="topic-chips">${PROFESSIONAL_ROLES.map((r) => html`<label class="chip"><input type="checkbox" name="audience" value="${r}" ${audience.has(r) ? raw("checked") : ""}> ${r.replace(/_/g, " ")}</label>`)}</div></fieldset>
    <fieldset><legend>Topics</legend><div class="topic-chips">${TOPICS.map((k) => html`<label class="chip"><input type="checkbox" name="topics" value="${k}" ${topics.has(k) ? raw("checked") : ""}> ${k}</label>`)}</div></fieldset>
    <fieldset><legend>Instructors</legend><div class="topic-chips">${instructors.results.map((i) => html`<label class="chip"><input type="checkbox" name="instructors" value="${i.id}" ${linkedIds.has(i.id) ? raw("checked") : ""}> ${i.name}</label>`)}</div></fieldset>
    <fieldset><legend>Prerequisite courses</legend>
      ${allCourses.results.map((x) => html`<div class="row"><label class="check"><input type="checkbox" name="prereq" value="${x.id}" ${pre.has(x.id) ? raw("checked") : ""}> ${x.title}</label>
        <label class="check small"><input type="checkbox" name="prereq_required" value="${x.id}" ${pre.get(x.id)?.is_required ? raw("checked") : ""}> required</label></div>`)}</fieldset>
    <fieldset><legend>Completion and certification</legend>
      ${checkbox("certificate_enabled", "Issue a certificate on completion", course.certificate_enabled)}
      ${checkbox("require_all_lessons", "Require all required lessons before the final exam", course.require_all_lessons)}
      ${checkbox("require_quizzes_pass", "Require passing every required quiz", course.require_quizzes_pass)}
      ${input("passing_score", "Default passing score (%)", course.passing_score, { type: "number", attrs: 'min="1" max="100"', hint: "Applied to new assessments; each assessment can override it." })}
    </fieldset>
    <fieldset><legend>Instructor video</legend>
      ${select("video_requirement", "Video policy", [["required", "Required — every planned lesson video must be approved, playable and captioned before publication"], ["optional", "Optional — publish with text lessons while videos are produced"]], course.video_requirement || "required")}
      ${textarea("video_waiver_reason", "Reason videos are optional (required when optional)", course.video_waiver_reason, { rows: 2, hint: "Recorded in the audit log and shown in the readiness checks." })}
    </fieldset>
    ${textarea("content_review_note", "Content review note (internal)", course.content_review_note, { rows: 2, hint: "Shown in the readiness checklist until cleared." })}
    <button class="btn btn-primary">Save course</button>
  </form>

  <section class="form-card mt-3"><h2 class="h2">Curriculum</h2>
    ${modules.results.map((m) => {
      const ml = lessons.results.filter((l) => l.module_id === m.id);
      return html`<div class="panel mt-2">
        <form method="post" action="/admin/modules/${m.id}" class="row">${hidden(c)}
          <label class="sr-only" for="m-${m.id}">Module title</label><input id="m-${m.id}" name="title" value="${m.title}" class="grow">
          <label class="sr-only" for="ms-${m.id}">Order</label><input id="ms-${m.id}" name="sort_order" type="number" value="${m.sort_order}" class="w-small">
          <button class="btn btn-sm btn-secondary">Save</button></form>
        ${table(
          ["#", "Lesson", "Type", "Status", "Video", ""],
          ml.map(
            (l) => html`<tr><td>${l.sort_order}</td><td class="wrap-cell"><a href="/admin/lessons/${l.id}">${l.title}</a>${l.is_preview ? html` <span class="badge">preview</span>` : ""}${l.is_required ? "" : html` <span class="badge">optional</span>`}</td>
              <td>${l.type}</td><td>${statusBadge(l.status)}</td><td>${l.video_id ? statusBadge(l.video_status) : "—"}</td><td><a href="/courses/${course.slug}" class="tiny">—</a></td></tr>`,
          ),
        )}
        <form method="post" action="/admin/modules/${m.id}/lessons" class="row mt-1">${hidden(c)}
          <label class="sr-only" for="nl-${m.id}">New lesson title</label><input id="nl-${m.id}" name="title" placeholder="New lesson title" class="grow" required>
          <select name="type" aria-label="Lesson type">${LESSON_TYPES.map((t) => html`<option>${t}</option>`)}</select>
          <button class="btn btn-sm btn-secondary">Add lesson</button></form>
        ${ml.length ? "" : html`<form method="post" action="/admin/modules/${m.id}/delete" class="mt-1">${hidden(c)}<button class="link-btn tiny">Delete empty module</button></form>`}
      </div>`;
    })}
    <form method="post" action="/admin/courses/${course.id}/modules" class="row mt-2">${hidden(c)}
      <label class="sr-only" for="nm">New module title</label><input id="nm" name="title" placeholder="New module title" class="grow" required>
      <button class="btn btn-secondary">Add module</button></form>
  </section>

  <section class="form-card mt-3"><h2 class="h2">Assessments</h2>
    ${table(
      ["Title", "Kind", "Certification", "Passing", "Status", ""],
      assessments.results.map((a) => html`<tr><td>${a.title}</td><td>${a.kind}</td><td>${a.is_certification ? "Yes" : "—"}</td><td>${a.passing_score}%</td><td>${statusBadge(a.status)}</td><td><a href="/admin/assessments/${a.id}">Edit</a></td></tr>`),
    )}
    <form method="post" action="/admin/courses/${course.id}/assessments" class="row mt-2">${hidden(c)}
      <input name="title" placeholder="Assessment title" required class="grow" aria-label="Assessment title">
      <select name="kind" aria-label="Kind"><option value="quiz">quiz</option><option value="exam">exam (certification)</option></select>
      <button class="btn btn-secondary btn-sm">Add assessment</button></form>
  </section>`;
  return adminPage(c, { title: course.title, active: "/admin/courses", body, actions: html`<a class="btn btn-sm btn-quiet" href="/admin/analytics/course/${course.id}">Engagement</a>` });
}

const list = (v) => [].concat(v ?? []).map(String);

export async function saveCourse(c) {
  const b = await c.readBody();
  const id = c.params.id;
  const slug = slugify(b.slug || b.title);
  if (!slug) return redirect(`/admin/courses/${id}?err=Invalid%20slug`);
  if (!(await c.env.DB.prepare("SELECT 1 FROM courses WHERE id = ?").bind(id).first())) throw new HttpError(404, "not_found");
  if (await slugTaken(c.env, slug, id)) return redirect(`/admin/courses/${id}?err=Slug%20already%20used`);
  const objectives = String(b.objectives || "").split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 20);
  const audience = list(b.audience).filter((r) => PROFESSIONAL_ROLES.includes(r));
  const topics = list(b.topics).filter((k) => TOPICS.includes(k));
  const instructors = list(b.instructors);
  const prereq = list(b.prereq).filter((x) => x !== id);
  const required = new Set(list(b.prereq_required));
  const now = nowIso();
  const passing = Math.min(100, Math.max(1, intOrNull(b.passing_score) || 80));
  const before = await c.env.DB.prepare("SELECT video_requirement, video_waiver_reason FROM courses WHERE id = ?").bind(id).first();
  const videoRequirement = b.video_requirement === "optional" ? "optional" : "required";
  const videoWaiver = videoRequirement === "optional" ? str(b.video_waiver_reason, 500) || null : null;
  if (videoRequirement === "optional" && !videoWaiver) return redirect(`/admin/courses/${id}?err=${encodeURIComponent("Record why instructor video is optional for this course.")}`);
  const policyChanged = before && (before.video_requirement !== videoRequirement || (before.video_waiver_reason || null) !== videoWaiver);
  await c.env.DB.batch([
    c.env.DB.prepare(
      `UPDATE draft_courses SET title=?, slug=?, subtitle=?, description=?, objectives_json=?, program_id=?, level=?, duration_minutes=?, source_locale=?, planned_release_date=?, sort_order=?,
         thumbnail_url=?, prerequisites_text=?, audience_json=?, topics_json=?, certificate_enabled=?, require_all_lessons=?, require_quizzes_pass=?, passing_score=?, updated_at=?, updated_by=? WHERE id=?`,
    ).bind(
      str(b.title, 200),
      slug,
      str(b.subtitle, 300),
      str(b.description, 8000),
      JSON.stringify(objectives),
      b.program_id || null,
      ["beginner", "intermediate", "advanced"].includes(b.level) ? b.level : "beginner",
      Math.max(0, intOrNull(b.duration_minutes) || 0),
      LOCALES.some((l) => l.code === b.source_locale) ? b.source_locale : "en",
      /^\d{4}-\d{2}-\d{2}$/.test(b.planned_release_date || "") ? b.planned_release_date : null,
      intOrNull(b.sort_order) || 0,
      str(b.thumbnail_url, 500) || null,
      str(b.prerequisites_text, 1000),
      JSON.stringify(audience),
      JSON.stringify(topics),
      bool(b.certificate_enabled),
      bool(b.require_all_lessons),
      bool(b.require_quizzes_pass),
      passing,
      now,
      c.user.id,
      id,
    ),
    // Publication policy (not reviewed content) stays on the live record.
    c.env.DB.prepare("UPDATE courses SET content_review_note=?, video_requirement=?, video_waiver_reason=?, updated_at=? WHERE id=?").bind(str(b.content_review_note, 1000) || null, videoRequirement, videoWaiver, now, id),
    c.env.DB.prepare("DELETE FROM draft_course_instructors WHERE course_id = ?").bind(id),
    ...instructors.map((iid, i) => c.env.DB.prepare("INSERT OR IGNORE INTO draft_course_instructors (course_id, instructor_id, sort_order) SELECT ?, id, ? FROM instructors WHERE id = ?").bind(id, i, iid)),
    c.env.DB.prepare("DELETE FROM draft_course_prerequisites WHERE course_id = ?").bind(id),
    ...prereq.map((pid) => c.env.DB.prepare("INSERT OR IGNORE INTO draft_course_prerequisites (course_id, prerequisite_course_id, is_required) SELECT ?, id, ? FROM courses WHERE id = ?").bind(id, required.has(pid) ? 1 : 0, pid)),
    auditStmt(c.env, c.user.id, "course.update", "course", id, { slug }),
    ...(policyChanged ? [auditStmt(c.env, c.user.id, "course.video_policy", "course", id, { video_requirement: videoRequirement, reason: videoWaiver })] : []),
  ]);
  await draftChanged(c.env, id);
  return redirect(`/admin/courses/${id}?ok=saved`);
}

export async function setCourseStatus(c) {
  const b = await c.readBody();
  const course = await c.env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(c.params.id).first();
  if (!course) throw new HttpError(404, "not_found");
  const status = COURSE_STATUSES.includes(b.status) ? b.status : course.status;
  // Publishing, scheduling, and any change to a published course's
  // availability (draft, review, archive) need the publish permission.
  if ((status === "published" || status === "scheduled" || course.status === "published" || course.status === "scheduled") && !c.can("courses.publish")) {
    throw new HttpError(403, "forbidden");
  }
  let readiness = null;
  if (status === "published" || status === "scheduled") {
    readiness = await publishReadiness(c.env, course);
    if (!readiness.ok) return redirect(`/admin/courses/${course.id}?err=${encodeURIComponent("Readiness checks must pass before publishing.")}`);
  }
  if (status === "published") {
    // Copy the reviewed draft live as a new revision, atomically with the status.
    try {
      // Bound to the status and schedule loaded above: an archive or cancellation in between wins.
      await publishDraft(c.env, course, { actorId: c.user.id, hash: readiness.hash, version: readiness.version, expect: { status: course.status, scheduled_at: course.scheduled_at ?? null } });
    } catch (e) {
      if (e instanceof DraftChangedError) return redirect(`/admin/courses/${course.id}?err=${encodeURIComponent(e.message + " Check the readiness list and publish again.")}`);
      throw e;
    }
    return redirect(`/admin/courses/${course.id}?ok=published`);
  }
  let scheduledAt = null;
  if (status === "scheduled") {
    const when = String(b.scheduled_at || "");
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(when)) return redirect(`/admin/courses/${course.id}?err=${encodeURIComponent("Choose a publication date and time.")}`);
    scheduledAt = new Date(`${when.slice(0, 16)}:00Z`).toISOString();
  }
  const now = nowIso();
  // Scheduling an update of a live course keeps the live revision published
  // (enrollment stays open); the scheduler publishes the reviewed draft later.
  const nextStatus = status === "scheduled" && course.status === "published" ? "published" : status;
  // Only if the status is still the one the permission check above saw: a
  // concurrent publication makes this request fail instead of overriding it.
  const res = await c.env.DB.prepare("UPDATE courses SET status = ?, scheduled_at = ?, updated_at = ? WHERE id = ? AND status = ?")
    .bind(nextStatus, scheduledAt, now, course.id, course.status)
    .run();
  if (!res.meta.changes) return redirect(`/admin/courses/${course.id}?err=${encodeURIComponent("The course changed while you were saving. Review its status and try again.")}`);
  await auditStmt(c.env, c.user.id, `course.status.${status}`, "course", course.id, { from: course.status, scheduled_at: scheduledAt }).run();
  return redirect(`/admin/courses/${course.id}?ok=saved`);
}

/** Throw away unpublished draft edits of a released course: the draft becomes the live revision again. */
export async function discardDraft(c) {
  const course = await c.env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(c.params.id).first();
  if (!course) throw new HttpError(404, "not_found");
  if (!course.published_at) return redirect(`/admin/courses/${course.id}?err=${encodeURIComponent("This course has not been released; its draft is its content.")}`);
  await c.env.DB.batch([...liveToDraftStatements(c.env, course.id), auditStmt(c.env, c.user.id, "course.draft.discarded", "course", course.id, {})]);
  return redirect(`/admin/courses/${course.id}?ok=saved`);
}

export async function saveReview(c) {
  const b = await c.readBody();
  const course = await c.env.DB.prepare("SELECT id FROM courses WHERE id = ?").bind(c.params.id).first();
  if (!course) throw new HttpError(404, "not_found");
  const back = (q) => redirect(`/admin/courses/${course.id}?${q}#reviews`);
  if (!REVIEW_TYPES.includes(b.review_type) || !REVIEW_DECISIONS.includes(b.decision)) return back(`err=${encodeURIComponent("Choose a review and a decision.")}`);
  if (!bool(b.confirm)) return back(`err=${encodeURIComponent("Confirm that the review covered the current content.")}`);
  const notes = str(b.notes, 2000);
  if (b.decision === "changes_requested" && !notes) return back(`err=${encodeURIComponent("Describe the changes requested.")}`);
  await recordReview(c.env, { courseId: course.id, type: b.review_type, decision: b.decision, notes, reviewerId: c.user.id, reviewerName: str(b.reviewer_name, 200) });
  return back("ok=saved");
}

export async function addModule(c) {
  const b = await c.readBody();
  if (!(await c.env.DB.prepare("SELECT 1 FROM courses WHERE id = ?").bind(c.params.id).first())) throw new HttpError(404, "not_found");
  const max = await c.env.DB.prepare("SELECT COALESCE(MAX(sort_order), 0) AS m FROM draft_modules WHERE course_id = ?").bind(c.params.id).first();
  const now = nowIso();
  await c.env.DB.prepare("INSERT INTO draft_modules (id, course_id, title, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?)").bind(newId("mod_"), c.params.id, str(b.title, 200) || "Untitled module", max.m + 1, now, now).run();
  await draftChanged(c.env, c.params.id);
  return redirect(`/admin/courses/${c.params.id}?ok=created`);
}

export async function saveModule(c) {
  const b = await c.readBody();
  const m = await c.env.DB.prepare("SELECT * FROM draft_modules WHERE id = ?").bind(c.params.id).first();
  if (!m) throw new HttpError(404, "not_found");
  await c.env.DB.prepare("UPDATE draft_modules SET title = ?, sort_order = ?, updated_at = ? WHERE id = ?").bind(str(b.title, 200) || m.title, intOrNull(b.sort_order) ?? m.sort_order, nowIso(), m.id).run();
  await draftChanged(c.env, m.course_id);
  return redirect(`/admin/courses/${m.course_id}?ok=saved`);
}

export async function deleteModule(c) {
  const m = await c.env.DB.prepare("SELECT * FROM draft_modules WHERE id = ?").bind(c.params.id).first();
  if (!m) throw new HttpError(404, "not_found");
  const n = await c.env.DB.prepare("SELECT COUNT(*) AS n FROM draft_lessons WHERE module_id = ?").bind(m.id).first();
  if (n.n) return redirect(`/admin/courses/${m.course_id}?err=Module%20is%20not%20empty`);
  await c.env.DB.prepare("DELETE FROM draft_modules WHERE id = ?").bind(m.id).run();
  await draftChanged(c.env, m.course_id);
  return redirect(`/admin/courses/${m.course_id}?ok=deleted`);
}

/**
 * Lesson slugs are unique within the draft. A slug kept by a lesson that the
 * live course still shows is also reserved, so progress links never point at
 * a different lesson after the next publication.
 */
async function lessonSlugTaken(env, courseId, slug, exceptId = "") {
  return env.DB.prepare(
    "SELECT 1 FROM draft_lessons WHERE course_id = ?1 AND slug = ?2 AND id != ?3 UNION ALL SELECT 1 FROM lessons WHERE course_id = ?1 AND slug = ?2 AND id != ?3 AND status = 'ready'",
  )
    .bind(courseId, slug, exceptId)
    .first();
}

export async function addLesson(c) {
  const b = await c.readBody();
  const m = await c.env.DB.prepare("SELECT * FROM draft_modules WHERE id = ?").bind(c.params.id).first();
  if (!m) throw new HttpError(404, "not_found");
  const title = str(b.title, 200) || "Untitled lesson";
  let slug = slugify(title) || "lesson";
  if (await lessonSlugTaken(c.env, m.course_id, slug)) slug = `${slug}-${Date.now().toString(36)}`;
  const max = await c.env.DB.prepare("SELECT COALESCE(MAX(sort_order), 0) AS m FROM draft_lessons WHERE course_id = ?").bind(m.course_id).first();
  const id = newId("les_");
  const now = nowIso();
  await c.env.DB.prepare("INSERT INTO draft_lessons (id, course_id, module_id, slug, title, type, status, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?, 'draft', ?, ?, ?)")
    .bind(id, m.course_id, m.id, slug, title, LESSON_TYPES.includes(b.type) ? b.type : "text", max.m + 1, now, now)
    .run();
  await draftChanged(c.env, m.course_id);
  return redirect(`/admin/lessons/${id}?ok=created`);
}

export async function editLesson(c) {
  const l = await c.env.DB.prepare("SELECT * FROM draft_lessons WHERE id = ?").bind(c.params.id).first();
  if (!l) throw new HttpError(404, "not_found");
  const [course, modules, videos, assessments, resources] = await Promise.all([
    c.env.DB.prepare("SELECT id, title, slug FROM draft_courses WHERE id = ?").bind(l.course_id).first(),
    c.env.DB.prepare("SELECT id, title FROM draft_modules WHERE course_id = ? ORDER BY sort_order").bind(l.course_id).all(),
    c.env.DB.prepare("SELECT id, title, status FROM video_assets ORDER BY created_at DESC").all(),
    c.env.DB.prepare("SELECT id, title, kind FROM draft_assessments WHERE course_id = ?").bind(l.course_id).all(),
    c.env.DB.prepare("SELECT * FROM draft_lesson_resources WHERE lesson_id = ? ORDER BY sort_order").bind(l.id).all(),
  ]);
  const preview = c.url.searchParams.get("preview") === "1";
  const body = html`<p><a href="/admin/courses/${course.id}">← ${course.title}</a> · <a href="/learn/${course.slug}/${l.slug}">Open in classroom</a></p>
  <form class="form-card" method="post" action="/admin/lessons/${l.id}">${hidden(c)}
    <div class="grid-2">${input("title", "Title", l.title, { required: true })}${input("slug", "Slug", l.slug, { required: true })}</div>
    <div class="grid-2">
      ${select("type", "Lesson type", LESSON_TYPES, l.type)}
      ${select("module_id", "Module", modules.results.map((m) => [m.id, m.title]), l.module_id)}
      ${input("est_minutes", "Estimated minutes", l.est_minutes, { type: "number", attrs: 'min="1" max="600"' })}
      ${input("sort_order", "Order in course", l.sort_order, { type: "number" })}
      ${select("video_id", "Instructor video", [["", "None"], ...videos.results.map((v) => [v.id, `${v.title} (${v.status})`])], l.video_id)}
      ${select("assessment_id", "Linked assessment (quiz lessons)", [["", "None"], ...assessments.results.map((a) => [a.id, `${a.title} (${a.kind})`])], l.assessment_id)}
      ${select("status", "Status", [["draft", "draft (hidden)"], ["ready", "ready (visible in published courses)"]], l.status)}
    </div>
    ${checkbox("is_required", "Required for completion", l.is_required)}
    ${checkbox("is_preview", "Free preview (viewable before enrolling)", l.is_preview)}
    ${input("summary", "Summary", l.summary)}
    ${textarea("body_md", "Lesson content (Markdown)", l.body_md, { rows: 22, cls: "code", hint: "Supports headings (##), lists, **bold**, *italic*, links, tables, blockquotes and callouts like > **Key idea:** … Raw HTML is not allowed." })}
    ${textarea("interactive_json", "Interactive block (JSON, optional)", l.interactive_json, { rows: 5, cls: "code", hint: 'Example: {"kind":"reveal","title":"Check yourself","cards":[{"front":"Q","back":"A"}]} or {"kind":"checklist","title":"Field checklist","items":["…"]}' })}
    <div class="row"><button class="btn btn-primary" name="after" value="stay">Save lesson</button><button class="btn btn-secondary" name="after" value="preview">Save and preview</button></div>
  </form>
  ${preview ? html`<section class="form-card mt-3"><h2 class="h2">Preview</h2><div class="prose">${raw(renderMarkdown(l.body_md).html)}</div></section>` : ""}
  <section class="form-card mt-3"><h2 class="h2">Resources</h2>
    ${table(["Title", "Link", ""], resources.results.map((r) => html`<tr><td>${r.title}</td><td class="wrap-cell tiny">${r.url || r.file_key}</td><td><form method="post" action="/admin/resources/${r.id}/delete">${hidden(c)}<button class="link-btn tiny">Remove</button></form></td></tr>`))}
    <form method="post" action="/admin/lessons/${l.id}/resources" class="row mt-2">${hidden(c)}
      <input name="title" placeholder="Resource title" required aria-label="Resource title" class="grow"><input name="url" type="url" placeholder="https://…" required aria-label="Resource URL" class="grow">
      <button class="btn btn-sm btn-secondary">Add link</button></form>
    <p class="tiny muted mt-1">${c.env.FILES ? "File uploads are stored in the Academy R2 bucket." : "File uploads require the optional R2 binding (FILES); link resources work without it."}</p>
    ${c.env.FILES
      ? html`<form method="post" action="/admin/lessons/${l.id}/upload?_csrf=${c.csrf}" enctype="multipart/form-data" class="row mt-1">
          <input type="file" name="file" required aria-label="Resource file" accept=".pdf,.csv,.xlsx,.docx,.pptx,.png,.jpg,.jpeg,.zip,.txt"><input name="title" placeholder="Title" aria-label="File title">
          <button class="btn btn-sm btn-secondary">Upload</button></form>`
      : ""}
  </section>
  <form method="post" action="/admin/lessons/${l.id}/delete" class="mt-3" data-confirm="Remove this lesson from the draft? After the next publication learners no longer see it; their progress records are kept.">${hidden(c)}<button class="btn btn-danger btn-sm">Delete lesson</button></form>`;
  return adminPage(c, { title: l.title, active: "/admin/courses", body });
}

export async function saveLesson(c) {
  const b = await c.readBody();
  const l = await c.env.DB.prepare("SELECT * FROM draft_lessons WHERE id = ?").bind(c.params.id).first();
  if (!l) throw new HttpError(404, "not_found");
  const slug = slugify(b.slug || b.title) || l.slug;
  if (await lessonSlugTaken(c.env, l.course_id, slug, l.id)) return redirect(`/admin/lessons/${l.id}?err=Slug%20already%20used`);
  let interactive = str(b.interactive_json, 20000) || null;
  if (interactive) {
    const parsed = parseJson(interactive, null);
    if (!parsed || !["reveal", "checklist"].includes(parsed.kind)) return redirect(`/admin/lessons/${l.id}?err=${encodeURIComponent("Interactive block must be valid JSON with kind reveal or checklist.")}`);
    interactive = JSON.stringify(parsed);
  }
  // Module, video and assessment must belong to this course draft (or exist).
  const moduleId = b.module_id && (await c.env.DB.prepare("SELECT 1 FROM draft_modules WHERE id = ? AND course_id = ?").bind(b.module_id, l.course_id).first()) ? b.module_id : l.module_id;
  const assessmentId = b.assessment_id && (await c.env.DB.prepare("SELECT 1 FROM draft_assessments WHERE id = ? AND course_id = ?").bind(b.assessment_id, l.course_id).first()) ? b.assessment_id : null;
  const videoId = b.video_id && (await c.env.DB.prepare("SELECT 1 FROM video_assets WHERE id = ?").bind(b.video_id).first()) ? b.video_id : null;
  await c.env.DB.batch([
    c.env.DB.prepare(
      `UPDATE draft_lessons SET title=?, slug=?, type=?, module_id=?, est_minutes=?, sort_order=?, video_id=?, assessment_id=?, status=?, is_required=?, is_preview=?, summary=?, body_md=?, interactive_json=?, updated_at=? WHERE id=?`,
    ).bind(
      str(b.title, 200) || l.title,
      slug,
      LESSON_TYPES.includes(b.type) ? b.type : l.type,
      moduleId,
      Math.max(1, intOrNull(b.est_minutes) || 5),
      intOrNull(b.sort_order) ?? l.sort_order,
      videoId,
      assessmentId,
      b.status === "ready" ? "ready" : "draft",
      bool(b.is_required),
      bool(b.is_preview),
      str(b.summary, 500),
      String(b.body_md ?? "").slice(0, 200000),
      interactive,
      nowIso(),
      l.id,
    ),
    auditStmt(c.env, c.user.id, "lesson.update", "lesson", l.id, { course_id: l.course_id }),
  ]);
  await draftChanged(c.env, l.course_id);
  return redirect(`/admin/lessons/${l.id}?ok=saved${b.after === "preview" ? "&preview=1" : ""}`);
}

export async function deleteLesson(c) {
  const l = await c.env.DB.prepare("SELECT * FROM draft_lessons WHERE id = ?").bind(c.params.id).first();
  if (!l) throw new HttpError(404, "not_found");
  // Only the draft row goes; the live lesson is hidden (never deleted) on publication.
  const files = (await c.env.DB.prepare("SELECT file_key FROM draft_lesson_resources WHERE lesson_id = ? AND file_key IS NOT NULL").bind(l.id).all()).results;
  await c.env.DB.batch([
    c.env.DB.prepare("DELETE FROM draft_lesson_resources WHERE lesson_id = ?").bind(l.id),
    c.env.DB.prepare("DELETE FROM draft_lessons WHERE id = ?").bind(l.id),
    auditStmt(c.env, c.user.id, "lesson.delete", "lesson", l.id, { title: l.title }),
  ]);
  await draftChanged(c.env, l.course_id);
  await pruneFiles(c.env, files.map((f) => f.file_key));
  return redirect(`/admin/courses/${l.course_id}?ok=deleted`);
}

export async function addResource(c) {
  const b = await c.readBody();
  const url = str(b.url, 1000);
  if (!/^https:\/\//.test(url)) return redirect(`/admin/lessons/${c.params.id}?err=Resource%20links%20must%20use%20https`);
  const l = await c.env.DB.prepare("SELECT course_id FROM draft_lessons WHERE id = ?").bind(c.params.id).first();
  if (!l) throw new HttpError(404, "not_found");
  await c.env.DB.prepare("INSERT INTO draft_lesson_resources (id, lesson_id, title, kind, url, created_at) VALUES (?,?,?, 'link', ?, ?)").bind(newId("res_"), c.params.id, str(b.title, 200), url, nowIso()).run();
  await draftChanged(c.env, l.course_id);
  return redirect(`/admin/lessons/${c.params.id}?ok=saved`);
}

const UPLOAD_TYPES = {
  "application/pdf": ".pdf", "text/csv": ".csv", "text/plain": ".txt", "image/png": ".png", "image/jpeg": ".jpg", "application/zip": ".zip",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
};

const startsWith = (head, sig) => sig.every((b, i) => head[i] === b);
function contentMatches(type, head) {
  if (type === "application/pdf") return startsWith(head, [0x25, 0x50, 0x44, 0x46]);
  if (type === "image/png") return startsWith(head, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (type === "image/jpeg") return startsWith(head, [0xff, 0xd8, 0xff]);
  if (type === "application/zip" || type.includes("openxmlformats")) return startsWith(head, [0x50, 0x4b, 0x03, 0x04]);
  // Text: no NUL bytes and not an HTML/SVG document.
  const text = new TextDecoder().decode(head).trimStart().toLowerCase();
  return !head.includes(0) && !text.startsWith("<");
}

export async function uploadResource(c) {
  if (!c.env.FILES) throw new HttpError(404, "not_found");
  const lesson = await c.env.DB.prepare("SELECT course_id FROM draft_lessons WHERE id = ?").bind(c.params.id).first();
  if (!lesson) throw new HttpError(404, "not_found");
  const form = await c.req.formData();
  const file = form.get("file");
  if (!file || typeof file === "string") return redirect(`/admin/lessons/${c.params.id}?err=No%20file`);
  if (file.size > 25 * 1024 * 1024) return redirect(`/admin/lessons/${c.params.id}?err=Files%20are%20limited%20to%2025%20MB`);
  const ext = UPLOAD_TYPES[file.type];
  if (!ext) return redirect(`/admin/lessons/${c.params.id}?err=Unsupported%20file%20type`);
  // The declared type must match the file's contents (magic bytes).
  const head = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  if (!contentMatches(file.type, head)) return redirect(`/admin/lessons/${c.params.id}?err=${encodeURIComponent("The file's contents do not match its type.")}`);
  const key = `resources/${c.params.id}/${newId("")}${ext}`;
  // R2 needs a body of known length: pass the Blob itself, not an unsized stream.
  await c.env.FILES.put(key, file, { httpMetadata: { contentType: file.type, contentDisposition: "attachment" } });
  await c.env.DB.prepare("INSERT INTO draft_lesson_resources (id, lesson_id, title, kind, file_key, mime, size_bytes, created_at) VALUES (?,?,?, 'file', ?, ?, ?, ?)")
    .bind(newId("res_"), c.params.id, str(form.get("title"), 200) || file.name.slice(0, 200), key, file.type, file.size, nowIso())
    .run();
  await draftChanged(c.env, lesson.course_id);
  await audit(c, "resource.upload", "lesson", c.params.id, { key, size: file.size });
  return redirect(`/admin/lessons/${c.params.id}?ok=saved`);
}

export async function deleteResource(c) {
  const r = await c.env.DB.prepare("SELECT r.*, l.course_id FROM draft_lesson_resources r JOIN draft_lessons l ON l.id = r.lesson_id WHERE r.id = ?").bind(c.params.id).first();
  if (!r) throw new HttpError(404, "not_found");
  await c.env.DB.prepare("DELETE FROM draft_lesson_resources WHERE id = ?").bind(r.id).run();
  await draftChanged(c.env, r.course_id);
  // The stored file goes only once neither the live course nor any draft uses it.
  await pruneFiles(c.env, [r.file_key]);
  return redirect(`/admin/lessons/${r.lesson_id}?ok=deleted`);
}

// ───────────── Videos ─────────────

const VIDEO_STATUSES = ["planned", "scripted", "rendering", "in_review", "approved", "retired"];

export async function videos(c) {
  const rows = (await c.env.DB.prepare("SELECT v.*, (SELECT COUNT(DISTINCT id) FROM (SELECT id FROM lessons WHERE video_id = v.id UNION SELECT id FROM draft_lessons WHERE video_id = v.id)) AS uses FROM video_assets v ORDER BY v.created_at DESC").all()).results;
  const body = html`<div class="alert alert-info">Only videos with status “approved” and a playable URL are shown to learners. Generating new Synthesia renders is a separate, approved production step — this page records and approves finished assets.</div>
  ${table(["Title", "Provider", "Status", "Duration", "Used by", ""], rows.map((v) => html`<tr><td class="wrap-cell">${v.title}</td><td>${v.provider}</td><td>${statusBadge(v.status)}</td><td>${v.duration_seconds ? `${Math.round(v.duration_seconds / 60)} min` : "—"}</td><td>${v.uses} lesson(s)</td><td><a href="/admin/videos/${v.id}">Edit</a></td></tr>`))}
  <form method="post" action="/admin/videos" class="row mt-2">${hidden(c)}<input name="title" placeholder="New video title" required class="grow" aria-label="Video title"><button class="btn btn-secondary btn-sm">Add video</button></form>`;
  return adminPage(c, { title: "Instructional videos", active: "/admin/videos", body });
}

export async function createVideo(c) {
  const b = await c.readBody();
  const id = newId("vid_");
  const now = nowIso();
  await c.env.DB.prepare("INSERT INTO video_assets (id, title, provider, status, created_at, updated_at) VALUES (?,?, 'synthesia', 'planned', ?, ?)").bind(id, str(b.title, 200) || "Untitled video", now, now).run();
  return redirect(`/admin/videos/${id}?ok=created`);
}

export async function editVideo(c) {
  const v = await c.env.DB.prepare("SELECT * FROM video_assets WHERE id = ?").bind(c.params.id).first();
  if (!v) throw new HttpError(404, "not_found");
  const [instructors, captions] = await Promise.all([
    c.env.DB.prepare("SELECT id, name FROM instructors ORDER BY sort_order").all(),
    c.env.DB.prepare("SELECT id, locale, label, status FROM video_captions WHERE video_id = ?").bind(v.id).all(),
  ]);
  const body = html`<form class="form-card" method="post" action="/admin/videos/${v.id}">${hidden(c)}
    ${input("title", "Title", v.title, { required: true })}
    <div class="grid-2">
      ${select("provider", "Provider", ["synthesia", "r2", "stream", "external"], v.provider)}
      ${select("status", "Production status", VIDEO_STATUSES, v.status, { hint: "Setting “approved” records you as the approver." })}
      ${select("instructor_id", "Instructor", [["", "None"], ...instructors.results.map((i) => [i.id, i.name])], v.instructor_id)}
      ${input("duration_seconds", "Duration (seconds)", v.duration_seconds, { type: "number" })}
    </div>
    ${input("hls_url", "HLS stream URL (.m3u8)", v.hls_url, { hint: "Adaptive streaming; played natively where supported (Safari, iOS, Android)." })}
    ${input("mp4_url", "MP4 URL", v.mp4_url, { hint: "Progressive fallback used by other browsers." })}
    ${input("poster_url", "Poster image URL", v.poster_url)}
    ${input("provider_ref", "Provider reference (e.g. Synthesia video ID)", v.provider_ref)}
    ${textarea("script_md", "Script / transcript (Markdown)", v.script_md, { rows: 14, cls: "code", hint: "Shown to learners as the transcript." })}
    ${v.approved_at ? html`<p class="small muted">Approved ${v.approved_at.slice(0, 10)}.</p>` : ""}
    <button class="btn btn-primary">Save video</button></form>
  <section class="form-card mt-3"><h2 class="h2">Captions (WebVTT)</h2>
    ${table(["Locale", "Label", "Status", ""], captions.results.map((cap) => html`<tr><td>${cap.locale}</td><td>${cap.label}</td><td>${statusBadge(cap.status)}</td><td><a href="/captions/${cap.id}.vtt">View</a> · <form class="inline" method="post" action="/admin/captions/${cap.id}/delete">${hidden(c)}<button class="link-btn tiny">Remove</button></form></td></tr>`))}
    <form method="post" action="/admin/videos/${v.id}/captions" class="mt-2">${hidden(c)}
      <div class="grid-2">${select("locale", "Locale", LOCALES.map((l) => [l.code, l.englishName]), "en", { id: "a-caption_locale" })}${select("status", "Caption status", ["machine", "reviewed"], "reviewed", { id: "a-caption_status" })}</div>
      ${textarea("vtt", "WebVTT content", "WEBVTT\n\n", { rows: 8, cls: "code", required: true })}
      <button class="btn btn-secondary btn-sm">Add captions</button></form></section>`;
  return adminPage(c, { title: v.title, active: "/admin/videos", body });
}

/**
 * A video shown by a released course's live lessons is immutable, like the
 * revision itself: media, transcript and captions change only by linking a new
 * asset in the course draft, which voids the reviews until they are recorded
 * again and is then published as a new revision.
 */
async function liveVideoLock(env, videoId) {
  return env.DB.prepare(
    `SELECT c.title FROM lessons l JOIN courses c ON c.id = l.course_id
      WHERE l.video_id = ? AND c.published_at IS NOT NULL AND l.slug NOT LIKE '\\_\\_rev\\_%' ESCAPE '\\' LIMIT 1`,
  )
    .bind(videoId)
    .first();
}
const lockedMessage = (lock) =>
  encodeURIComponent(`This video is live in “${lock.title}”. To change it, add a new video asset, link it to the lesson in the course draft, record the reviews and publish the revision.`);

export async function saveVideo(c) {
  const b = await c.readBody();
  const v = await c.env.DB.prepare("SELECT * FROM video_assets WHERE id = ?").bind(c.params.id).first();
  if (!v) throw new HttpError(404, "not_found");
  const lock = await liveVideoLock(c.env, v.id);
  if (lock) return redirect(`/admin/videos/${v.id}?err=${lockedMessage(lock)}`);
  const status = VIDEO_STATUSES.includes(b.status) ? b.status : v.status;
  const urlOk = (u) => !u || /^https:\/\//.test(u);
  const hls = str(b.hls_url, 1000);
  const mp4 = str(b.mp4_url, 1000);
  const poster = str(b.poster_url, 1000);
  if (![hls, mp4, poster].every(urlOk)) return redirect(`/admin/videos/${v.id}?err=Video%20URLs%20must%20use%20https`);
  if (status === "approved" && !hls && !mp4) return redirect(`/admin/videos/${v.id}?err=${encodeURIComponent("An approved video needs an HLS or MP4 URL.")}`);
  // Watch-to-complete is measured against this length; the browser's report is never trusted for it.
  if (status === "approved" && !(intOrNull(b.duration_seconds) > 0)) return redirect(`/admin/videos/${v.id}?err=${encodeURIComponent("An approved video needs its duration in seconds.")}`);
  const now = nowIso();
  const approving = status === "approved" && v.status !== "approved";
  await c.env.DB.batch([
    c.env.DB.prepare(
      `UPDATE video_assets SET title=?, provider=?, status=?, instructor_id=?, duration_seconds=?, hls_url=?, mp4_url=?, poster_url=?, provider_ref=?, script_md=?,
         approved_by = CASE WHEN ? THEN ? ELSE approved_by END, approved_at = CASE WHEN ? THEN ? ELSE approved_at END, updated_at=? WHERE id=?`,
    ).bind(
      str(b.title, 200) || v.title,
      ["synthesia", "r2", "stream", "external"].includes(b.provider) ? b.provider : v.provider,
      status,
      b.instructor_id || null,
      intOrNull(b.duration_seconds),
      hls || null,
      mp4 || null,
      poster || null,
      str(b.provider_ref, 200) || null,
      String(b.script_md ?? "").slice(0, 100000),
      approving ? 1 : 0,
      c.user.id,
      approving ? 1 : 0,
      now,
      now,
      v.id,
    ),
    auditStmt(c.env, c.user.id, approving ? "video.approve" : "video.update", "video", v.id, { status }),
  ]);
  return redirect(`/admin/videos/${v.id}?ok=saved`);
}

export async function addCaptions(c) {
  const b = await c.readBody();
  const vtt = String(b.vtt || "").replace(/\r\n?/g, "\n").slice(0, 500000);
  if (!vtt.startsWith("WEBVTT")) return redirect(`/admin/videos/${c.params.id}?err=Captions%20must%20be%20WebVTT`);
  const lock = await liveVideoLock(c.env, c.params.id);
  if (lock) return redirect(`/admin/videos/${c.params.id}?err=${lockedMessage(lock)}`);
  const loc = LOCALES.find((l) => l.code === b.locale) || LOCALES[0];
  await c.env.DB.prepare(
    `INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES (?,?,?,?,?,?,?)
     ON CONFLICT(video_id, locale) DO UPDATE SET vtt = excluded.vtt, status = excluded.status, label = excluded.label`,
  )
    .bind(newId("cap_"), c.params.id, loc.code, loc.nativeName, vtt, b.status === "machine" ? "machine" : "reviewed", nowIso())
    .run();
  return redirect(`/admin/videos/${c.params.id}?ok=saved`);
}

export async function deleteCaptions(c) {
  const cap = await c.env.DB.prepare("SELECT video_id FROM video_captions WHERE id = ?").bind(c.params.id).first();
  if (!cap) throw new HttpError(404, "not_found");
  const lock = await liveVideoLock(c.env, cap.video_id);
  if (lock) return redirect(`/admin/videos/${cap.video_id}?err=${lockedMessage(lock)}`);
  await c.env.DB.prepare("DELETE FROM video_captions WHERE id = ?").bind(c.params.id).run();
  return redirect(`/admin/videos/${cap.video_id}?ok=deleted`);
}

// ───────────── Instructors ─────────────

export async function instructors(c) {
  const rows = (await c.env.DB.prepare("SELECT * FROM instructors ORDER BY sort_order, name").all()).results;
  const edit = c.url.searchParams.get("id") ? rows.find((r) => r.id === c.url.searchParams.get("id")) : null;
  const i = edit || {};
  const body = html`${table(["Name", "Title", "AI avatar", "Status", ""], rows.map((r) => html`<tr><td>${r.name}</td><td>${r.title}</td><td>${r.is_ai_avatar ? "Yes" : "—"}</td><td>${statusBadge(r.status)}</td><td><a href="/admin/instructors?id=${r.id}">Edit</a></td></tr>`))}
  <form class="form-card mt-3" method="post" action="/admin/instructors">${hidden(c)}<input type="hidden" name="id" value="${i.id || ""}">
    <h2 class="h2">${edit ? `Edit ${i.name}` : "Add instructor"}</h2>
    <div class="grid-2">${input("name", "Name", i.name, { required: true })}${input("title", "Title / role", i.title)}</div>
    ${textarea("bio", "Biography", i.bio, { rows: 4 })}
    ${input("avatar_url", "Photo URL (https, optional)", i.avatar_url)}
    ${checkbox("is_ai_avatar", "This is an AI-generated presenter avatar", i.is_ai_avatar, "Learners are always told when an instructor is an AI avatar.")}
    ${textarea("disclosure", "Disclosure shown to learners", i.disclosure, { rows: 2 })}
    <div class="grid-2">${input("sort_order", "Sort order", i.sort_order ?? 0, { type: "number" })}${select("status", "Status", ["active", "hidden"], i.status || "active")}</div>
    <button class="btn btn-primary">${edit ? "Save" : "Add"}</button></form>`;
  return adminPage(c, { title: "Instructors", active: "/admin/instructors", body });
}

export async function saveInstructor(c) {
  const b = await c.readBody();
  const name = str(b.name, 120);
  if (!name) return redirect("/admin/instructors?err=Name%20is%20required");
  const avatar = str(b.avatar_url, 500);
  if (avatar && !/^https:\/\//.test(avatar) && !avatar.startsWith("/static/")) return redirect("/admin/instructors?err=Photo%20URL%20must%20use%20https");
  const now = nowIso();
  const vals = [name, str(b.title, 200), str(b.bio, 3000), avatar || null, bool(b.is_ai_avatar), str(b.disclosure, 500) || null, intOrNull(b.sort_order) || 0, b.status === "hidden" ? "hidden" : "active"];
  if (b.id) {
    // Like videos, a profile shown by a released course is part of its reviewed
    // revision: change it by linking a new profile in the course draft.
    const lock = await c.env.DB.prepare(
      "SELECT c.title FROM course_instructors ci JOIN courses c ON c.id = ci.course_id WHERE ci.instructor_id = ? AND c.published_at IS NOT NULL LIMIT 1",
    )
      .bind(b.id)
      .first();
    if (lock) {
      return redirect(
        `/admin/instructors?err=${encodeURIComponent(`This profile is shown by “${lock.title}”. Create a new instructor profile, link it in the course draft, record the reviews and publish the revision.`)}`,
      );
    }
    await c.env.DB.prepare("UPDATE instructors SET name=?, title=?, bio=?, avatar_url=?, is_ai_avatar=?, disclosure=?, sort_order=?, status=?, updated_at=? WHERE id=?").bind(...vals, now, b.id).run();
  } else {
    let slug = slugify(name);
    if (await c.env.DB.prepare("SELECT 1 FROM instructors WHERE slug = ?").bind(slug).first()) slug = `${slug}-${Date.now().toString(36)}`;
    await c.env.DB.prepare("INSERT INTO instructors (id, slug, name, title, bio, avatar_url, is_ai_avatar, disclosure, sort_order, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
      .bind(newId("ins_"), slug, ...vals, now, now)
      .run();
  }
  await audit(c, "instructor.save", "instructor", b.id || null, { name });
  return redirect("/admin/instructors?ok=saved");
}

// ───────────── Programs and learning paths ─────────────

export async function programsAdmin(c) {
  const [programs, paths, courses, links] = await Promise.all([
    c.env.DB.prepare("SELECT * FROM programs ORDER BY sort_order").all(),
    c.env.DB.prepare("SELECT * FROM learning_paths ORDER BY sort_order").all(),
    c.env.DB.prepare("SELECT id, title FROM courses ORDER BY title").all(),
    c.env.DB.prepare("SELECT * FROM learning_path_courses").all(),
  ]);
  const body = html`<h2 class="h2">Programs</h2>
  ${programs.results.map(
    (p) => html`<form class="panel mt-2" method="post" action="/admin/programs/${p.id}">${hidden(c)}
      <div class="grid-2">${input(`title`, "Title", p.title, { id: `prg-title-${p.id}` })}${input("code", "Code", p.code, { id: `prg-code-${p.id}` })}</div>
      ${input("summary", "Summary", p.summary, { id: `prg-summary-${p.id}` })}
      <div class="row">${select("status", "Status", ["draft", "published", "archived"], p.status, { id: `prg-status-${p.id}` })}${input("sort_order", "Order", p.sort_order, { type: "number", id: `prg-order-${p.id}` })}<button class="btn btn-sm btn-secondary">Save program</button></div></form>`,
  )}
  <h2 class="h2 mt-4">Learning paths (by professional role)</h2>
  ${paths.results.map((p) => {
    const ids = new Set(links.results.filter((l) => l.path_id === p.id).map((l) => l.course_id));
    return html`<form class="panel mt-2" method="post" action="/admin/paths/${p.id}">${hidden(c)}
      <div class="grid-2">${input("title", "Title", p.title, { id: `path-title-${p.id}` })}${select("role", "Role", PROFESSIONAL_ROLES, p.role, { id: `path-role-${p.id}` })}</div>
      ${input("summary", "Summary", p.summary, { id: `path-summary-${p.id}` })}
      <fieldset><legend>Courses (in order of selection below)</legend><div class="topic-chips">${courses.results.map((x) => html`<label class="chip"><input type="checkbox" name="courses" value="${x.id}" ${ids.has(x.id) ? raw("checked") : ""}> ${x.title}</label>`)}</div></fieldset>
      <div class="row">${select("status", "Status", ["draft", "published", "archived"], p.status, { id: `path-status-${p.id}` })}<button class="btn btn-sm btn-secondary">Save path</button></div></form>`;
  })}`;
  return adminPage(c, { title: "Programs & learning paths", active: "/admin/programs", body });
}

export async function saveProgram(c) {
  const b = await c.readBody();
  await c.env.DB.prepare("UPDATE programs SET title=?, code=?, summary=?, status=?, sort_order=?, updated_at=? WHERE id=?")
    .bind(str(b.title, 200), str(b.code, 10), str(b.summary, 600), ["draft", "published", "archived"].includes(b.status) ? b.status : "draft", intOrNull(b.sort_order) || 0, nowIso(), c.params.id)
    .run();
  return redirect("/admin/programs?ok=saved");
}

export async function savePath(c) {
  const b = await c.readBody();
  const ids = list(b.courses);
  await c.env.DB.batch([
    c.env.DB.prepare("UPDATE learning_paths SET title=?, role=?, summary=?, status=?, updated_at=? WHERE id=?").bind(
      str(b.title, 200),
      PROFESSIONAL_ROLES.includes(b.role) ? b.role : "student",
      str(b.summary, 600),
      ["draft", "published", "archived"].includes(b.status) ? b.status : "draft",
      nowIso(),
      c.params.id,
    ),
    c.env.DB.prepare("DELETE FROM learning_path_courses WHERE path_id = ?").bind(c.params.id),
    ...ids.map((id, i) => c.env.DB.prepare("INSERT OR IGNORE INTO learning_path_courses (path_id, course_id, sort_order) VALUES (?,?,?)").bind(c.params.id, id, i)),
  ]);
  return redirect("/admin/programs?ok=saved");
}
