// Admin: learner support, roles, enrollments, and certificate management.
import { html, raw } from "../../lib/html.js";
import { redirect, HttpError } from "../../lib/http.js";
import { newId, nowIso, credentialId } from "../../lib/util.js";
import { auditStmt, audit, revokeAllSessions } from "../../lib/security.js";
import { adminPage, table, statusBadge, hidden, input, select, str } from "./shell.js";
import { issueToken } from "../../services/users.js";
import { sendEmail } from "../../services/email.js";
import { revokeCertificate, reinstateCertificate, signCertificate, issueIfEligible } from "../../services/certificates.js";
import { enroll } from "../../services/progress.js";
import { getCourseById } from "../../services/content.js";

const ROLES = ["super_admin", "academy_admin", "instructor", "content_editor", "learner"];

export async function learners(c) {
  const q = str(c.url.searchParams.get("q"), 120);
  const rows = (
    await c.env.DB.prepare(
      `SELECT u.id, u.email, u.display_name, u.status, u.email_verified_at, u.created_at, u.last_login_at, u.locale,
              (SELECT COUNT(*) FROM enrollments e WHERE e.user_id = u.id) AS enrollments,
              (SELECT COUNT(*) FROM certificates x WHERE x.user_id = u.id AND x.status = 'active') AS certs,
              (SELECT GROUP_CONCAT(role) FROM user_roles r WHERE r.user_id = u.id AND r.role != 'learner') AS staff_roles
         FROM users u ${q ? "WHERE u.email LIKE ? OR u.display_name LIKE ?" : ""} ORDER BY u.created_at DESC LIMIT 200`,
    )
      .bind(...(q ? [`%${q}%`, `%${q}%`] : []))
      .all()
  ).results;
  const body = html`<form method="get" class="search-bar"><label class="sr-only" for="lq">Search</label><input id="lq" name="q" value="${q}" placeholder="Search by name or email"><button class="btn btn-secondary">Search</button></form>
  ${table(
    ["Learner", "Email", "Status", "Language", "Enrollments", "Certificates", "Joined", ""],
    rows.map(
      (u) => html`<tr><td>${u.display_name} ${u.staff_roles ? html`<span class="badge badge-lime">${u.staff_roles.replace(/,/g, ", ")}</span>` : ""}</td><td>${u.email} ${u.email_verified_at ? "" : html`<span class="badge badge-warn">unverified</span>`}</td>
        <td>${statusBadge(u.status)}</td><td>${u.locale}</td><td>${u.enrollments}</td><td>${u.certs}</td><td>${u.created_at.slice(0, 10)}</td><td><a href="/admin/learners/${u.id}">Open</a></td></tr>`,
    ),
  )}`;
  return adminPage(c, { title: "Learners", active: "/admin/learners", body });
}

export async function learnerDetail(c) {
  const u = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(c.params.id).first();
  if (!u) throw new HttpError(404, "not_found");
  const [roles, enrollments, attempts, certs, courses] = await Promise.all([
    c.env.DB.prepare("SELECT role, granted_by, granted_at FROM user_roles WHERE user_id = ?").bind(u.id).all(),
    c.env.DB.prepare("SELECT e.*, c.title FROM enrollments e JOIN courses c ON c.id = e.course_id WHERE e.user_id = ? ORDER BY e.enrolled_at DESC").bind(u.id).all(),
    c.env.DB.prepare("SELECT t.*, a.title, a.kind FROM attempts t JOIN assessments a ON a.id = t.assessment_id WHERE t.user_id = ? ORDER BY t.started_at DESC LIMIT 50").bind(u.id).all(),
    c.env.DB.prepare("SELECT * FROM certificates WHERE user_id = ? ORDER BY issued_at DESC").bind(u.id).all(),
    c.env.DB.prepare("SELECT id, title FROM courses WHERE status = 'published' ORDER BY title").all(),
  ]);
  const has = new Set(roles.results.map((r) => r.role));
  const canRoles = c.can("*") || c.roles.includes("super_admin");
  const body = html`
  <section class="panel"><dl class="kv">
    <dt>Email</dt><dd>${u.email} ${u.email_verified_at ? html`<span class="badge badge-green">verified</span>` : html`<span class="badge badge-warn">unverified</span>`}</dd>
    <dt>Credential name</dt><dd>${u.credential_name || u.display_name}</dd>
    <dt>Status</dt><dd>${statusBadge(u.status)}</dd><dt>Language</dt><dd>${u.locale}</dd>
    <dt>Joined</dt><dd>${u.created_at.slice(0, 10)}</dd><dt>Last sign-in</dt><dd>${u.last_login_at ? u.last_login_at.slice(0, 16).replace("T", " ") : "—"}</dd></dl>
    <div class="row mt-2">
      ${!u.email_verified_at && c.can("learners.manage") ? html`<form method="post" action="/admin/learners/${u.id}/resend">${hidden(c)}<button class="btn btn-sm btn-secondary">Resend verification email</button></form>` : ""}
      ${c.can("learners.manage") && u.id !== c.user.id
        ? html`<form method="post" action="/admin/learners/${u.id}/status" data-confirm="Change this account's status?">${hidden(c)}<input type="hidden" name="status" value="${u.status === "active" ? "disabled" : "active"}">
            <button class="btn btn-sm ${u.status === "active" ? "btn-danger" : "btn-secondary"}">${u.status === "active" ? "Disable account" : "Re-enable account"}</button></form>`
        : ""}
    </div></section>
  ${canRoles
    ? html`<form class="form-card mt-3" method="post" action="/admin/learners/${u.id}/roles">${hidden(c)}<h2 class="h2">Roles</h2>
        <div class="topic-chips">${ROLES.map((r) => html`<label class="chip"><input type="checkbox" name="roles" value="${r}" ${has.has(r) ? raw("checked") : ""} ${r === "learner" ? raw("disabled") : ""}> ${r.replace(/_/g, " ")}</label>`)}</div>
        <button class="btn btn-sm btn-primary mt-2">Save roles</button></form>`
    : html`<p class="small mt-2">Roles: ${[...has].join(", ")}</p>`}
  <h2 class="h2 mt-4">Enrollments</h2>
  ${table(["Course", "Status", "Progress", "Enrolled", "Completed"], enrollments.results.map((e) => html`<tr><td>${e.title}</td><td>${statusBadge(e.status)}</td><td>${e.progress_pct}%</td><td>${e.enrolled_at.slice(0, 10)}</td><td>${e.completed_at?.slice(0, 10) || "—"}</td></tr>`))}
  ${c.can("learners.manage")
    ? html`<form method="post" action="/admin/learners/${u.id}/enroll" class="row mt-1">${hidden(c)}<select name="course_id" aria-label="Course">${courses.results.map((x) => html`<option value="${x.id}">${x.title}</option>`)}</select><button class="btn btn-sm btn-secondary">Enroll in course</button></form>`
    : ""}
  <h2 class="h2 mt-4">Assessment attempts</h2>
  ${table(["Assessment", "Attempt", "Status", "Score", "Date"], attempts.results.map((t) => html`<tr><td>${t.title} <span class="tiny muted">(${t.kind})</span></td><td>#${t.attempt_no}</td><td>${statusBadge(t.status)}</td><td>${t.score_pct != null ? `${t.score_pct}%` : "—"}</td><td>${t.started_at.slice(0, 10)}</td></tr>`))}
  <h2 class="h2 mt-4">Certificates</h2>
  ${table(["Credential", "Course", "Issued", "Status", ""], certs.results.map((x) => html`<tr><td><code>${x.credential_id}</code></td><td>${x.course_title}</td><td>${x.issued_at.slice(0, 10)}</td><td>${statusBadge(x.status)}</td><td><a href="/admin/certificates?q=${x.credential_id}">Manage</a></td></tr>`))}`;
  return adminPage(c, { title: u.display_name, active: "/admin/learners", body });
}

export async function resendVerification(c) {
  const u = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(c.params.id).first();
  if (!u) throw new HttpError(404, "not_found");
  const token = await issueToken(c.env, u.id, "verify_email");
  await sendEmail(c, { user: u, template: "verify_email", vars: { url: `${c.cfg.origin}/verify-email?token=${token}` } });
  await audit(c, "learner.resend_verification", "user", u.id);
  return redirect(`/admin/learners/${u.id}?ok=sent`);
}

export async function setStatus(c) {
  const b = await c.readBody();
  if (c.params.id === c.user.id) throw new HttpError(409, "cannot_change_self");
  const status = b.status === "disabled" ? "disabled" : "active";
  await c.env.DB.batch([
    c.env.DB.prepare("UPDATE users SET status = ?, updated_at = ? WHERE id = ? AND status != 'deleted'").bind(status, nowIso(), c.params.id),
    auditStmt(c.env, c.user.id, `learner.${status}`, "user", c.params.id),
  ]);
  if (status === "disabled") await revokeAllSessions(c.env, c.params.id);
  return redirect(`/admin/learners/${c.params.id}?ok=saved`);
}

export async function setRoles(c) {
  if (!c.roles.includes("super_admin")) throw new HttpError(403, "forbidden");
  const b = await c.readBody();
  const wanted = new Set([].concat(b.roles ?? []).filter((r) => ROLES.includes(r)));
  wanted.add("learner");
  if (c.params.id === c.user.id && !wanted.has("super_admin")) {
    const others = await c.env.DB.prepare("SELECT COUNT(*) AS n FROM user_roles WHERE role = 'super_admin' AND user_id != ?").bind(c.user.id).first();
    if (!others.n) return redirect(`/admin/learners/${c.params.id}?err=${encodeURIComponent("You are the only super administrator.")}`);
  }
  const now = nowIso();
  await c.env.DB.batch([
    c.env.DB.prepare("DELETE FROM user_roles WHERE user_id = ?").bind(c.params.id),
    ...[...wanted].map((r) => c.env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_by, granted_at) VALUES (?,?,?,?)").bind(c.params.id, r, c.user.id, now)),
    auditStmt(c.env, c.user.id, "roles.set", "user", c.params.id, { roles: [...wanted] }),
  ]);
  return redirect(`/admin/learners/${c.params.id}?ok=saved`);
}

export async function enrollLearner(c) {
  const b = await c.readBody();
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(c.params.id).first();
  const course = await getCourseById(c.env, b.course_id);
  if (!user || !course) throw new HttpError(404, "not_found");
  try {
    await enroll({ ...c, user }, course);
  } catch (e) {
    if (e instanceof HttpError) return redirect(`/admin/learners/${user.id}?err=${encodeURIComponent(e.code)}`);
    throw e;
  }
  await audit(c, "learner.enroll", "user", user.id, { course_id: course.id });
  return redirect(`/admin/learners/${user.id}?ok=saved`);
}

// ───────────── Certificates ─────────────

export async function certificates(c) {
  const q = str(c.url.searchParams.get("q"), 120);
  const rows = (
    await c.env.DB.prepare(
      `SELECT x.*, u.email FROM certificates x LEFT JOIN users u ON u.id = x.user_id
        ${q ? "WHERE x.credential_id = ? OR x.credential_name LIKE ? OR u.email LIKE ?" : ""} ORDER BY x.issued_at DESC LIMIT 200`,
    )
      .bind(...(q ? [q.toUpperCase(), `%${q}%`, `%${q}%`] : []))
      .all()
  ).results;
  const courses = (await c.env.DB.prepare("SELECT id, title FROM courses WHERE certificate_enabled = 1 ORDER BY title").all()).results;
  const body = html`<form method="get" class="search-bar"><label class="sr-only" for="cq">Search</label><input id="cq" name="q" value="${q}" placeholder="Credential ID, name or email"><button class="btn btn-secondary">Search</button></form>
  ${rows.map(
    (x) => html`<article class="panel mt-2"><div class="row-between"><div><code>${x.credential_id}</code> ${statusBadge(x.status)}<div><strong>${x.credential_name}</strong> · ${x.course_title}</div>
        <div class="tiny muted">${x.email || "account deleted"} · issued ${x.issued_at.slice(0, 10)}${x.revoked_reason ? ` · revoked: ${x.revoked_reason}` : ""}</div></div>
      <div class="row"><a class="btn btn-sm btn-quiet" href="/verify/${x.credential_id}">Public page</a>
      ${x.status === "active"
        ? html`<form method="post" action="/admin/certificates/${x.id}/revoke" class="row" data-confirm="Revoke this credential? The public verification page will show it as revoked.">${hidden(c)}
            <input name="reason" required placeholder="Reason" aria-label="Revocation reason"><button class="btn btn-sm btn-danger">Revoke</button></form>`
        : x.user_id
          ? html`<form method="post" action="/admin/certificates/${x.id}/reinstate">${hidden(c)}<button class="btn btn-sm btn-secondary">Reinstate</button></form>`
          : ""}</div></div></article>`,
  )}
  ${rows.length ? "" : html`<p class="muted">No certificates found.</p>`}
  <section class="form-card mt-4"><h2 class="h2">Issue a certificate</h2>
    <p class="small muted">Use “Check eligibility and issue” for learners who met the requirements. Manual issuance bypasses the automated checks and requires a documented reason; it is recorded in the audit log.</p>
    <form method="post" action="/admin/certificates/issue">${hidden(c)}
      <div class="grid-2">${input("email", "Learner email", "", { type: "email", required: true })}${select("course_id", "Course", courses.map((x) => [x.id, x.title]), "")}</div>
      ${select("mode", "Mode", [["eligible", "Check eligibility and issue"], ["manual", "Manual issuance (override)"]], "eligible")}
      ${input("reason", "Reason (required for manual issuance)", "")}
      <button class="btn btn-primary">Issue</button></form></section>`;
  return adminPage(c, { title: "Certificates", active: "/admin/certificates", body });
}

export async function revoke(c) {
  const b = await c.readBody();
  const reason = str(b.reason, 300);
  if (!reason) return redirect("/admin/certificates?err=A%20reason%20is%20required");
  await revokeCertificate(c.env, c.params.id, c.user.id, reason);
  return redirect("/admin/certificates?ok=revoked");
}

export async function reinstate(c) {
  try {
    await reinstateCertificate(c.env, c.params.id, c.user.id);
  } catch (e) {
    if (e instanceof HttpError && e.status === 409) return redirect("/admin/certificates?err=The%20learner%20already%20holds%20an%20active%20credential%20for%20this%20course");
    throw e;
  }
  return redirect("/admin/certificates?ok=reinstated");
}

export async function issue(c) {
  const b = await c.readBody();
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE email = ? AND status = 'active'").bind(String(b.email || "").trim().toLowerCase()).first();
  const course = await getCourseById(c.env, b.course_id);
  if (!user || !course) return redirect("/admin/certificates?err=Learner%20or%20course%20not%20found");
  if (b.mode !== "manual") {
    const r = await issueIfEligible(c.env, c.cfg, user, course, { actorId: c.user.id, defer: c.defer });
    if (!r.certificate) return redirect(`/admin/certificates?err=${encodeURIComponent(`Not eligible: ${(r.reasons || []).join(", ")}`)}`);
    return redirect(`/admin/certificates?q=${r.certificate.credential_id}&ok=issued`);
  }
  const reason = str(b.reason, 300);
  if (!reason) return redirect("/admin/certificates?err=Manual%20issuance%20requires%20a%20reason");
  const existing = await c.env.DB.prepare("SELECT credential_id FROM certificates WHERE user_id = ? AND course_id = ? AND status = 'active'").bind(user.id, course.id).first();
  if (existing) return redirect(`/admin/certificates?q=${existing.credential_id}&err=Learner%20already%20holds%20this%20credential`);
  const program = course.program_id ? await c.env.DB.prepare("SELECT title FROM programs WHERE id = ?").bind(course.program_id).first() : null;
  const cert = {
    id: newId("crt_"),
    credential_id: credentialId(),
    user_id: user.id,
    course_id: course.id,
    credential_name: (user.credential_name || user.display_name).trim(),
    course_title: course.title,
    program_title: program?.title ?? null,
    issued_at: nowIso(),
  };
  cert.signature = await signCertificate(c.cfg, cert);
  await c.env.DB.batch([
    c.env.DB.prepare(
      "INSERT INTO certificates (id, credential_id, user_id, course_id, credential_name, course_title, program_title, issued_at, status, signature, created_at) VALUES (?,?,?,?,?,?,?,?, 'active', ?, ?)",
    ).bind(cert.id, cert.credential_id, cert.user_id, cert.course_id, cert.credential_name, cert.course_title, cert.program_title, cert.issued_at, cert.signature, cert.issued_at),
    c.env.DB.prepare("INSERT INTO certificate_events (id, certificate_id, event, actor_id, detail, created_at) VALUES (?,?, 'issued', ?, ?, ?)").bind(newId("ce_"), cert.id, c.user.id, JSON.stringify({ manual: true, reason }), cert.issued_at),
    auditStmt(c.env, c.user.id, "certificate.issue_manual", "certificate", cert.id, { credential_id: cert.credential_id, reason, user_id: user.id }),
  ]);
  await sendEmail(c, { user, template: "certificate_issued", vars: { course: course.title, credential: cert.credential_id, url: `${c.cfg.origin}/certificates/${cert.credential_id}` } });
  return redirect(`/admin/certificates?q=${cert.credential_id}&ok=issued`);
}
