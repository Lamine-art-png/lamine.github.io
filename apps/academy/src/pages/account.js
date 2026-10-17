// Account settings: profile, credential name, password, notification and
// privacy preferences, sessions, data export and account deletion.
import { html, raw } from "../lib/html.js";
import { redirect, HttpError, serializeCookie } from "../lib/http.js";
import { nowIso } from "../lib/util.js";
import { verifyPassword, passwordProblem, revokeAllSessions, audit, cookieNames, rateLimit } from "../lib/security.js";
import { LOCALES, matchLocale } from "../lib/i18n.js";
import { pdfRepresentable } from "../lib/pdf.js";
import { alert, csrfField, field, selectField, pageHead } from "../views/components.js";
import { PROFESSIONAL_ROLES, setPassword, deleteAccount } from "../services/users.js";
import { sendEmail, queueEmail, deliverById } from "../services/email.js";
import { countryOptions, COUNTRY_CODES } from "./auth.js";

const FLASH = { saved: "account.saved", password: "account.password_changed", sessions: "account.sessions_revoked", prefs: "account.prefs_saved" };

export async function accountPage(c, { errors = {} } = {}) {
  const t = c.t;
  const u = c.user;
  const [prefs, sessions, google] = await Promise.all([
    c.env.DB.prepare("SELECT * FROM user_preferences WHERE user_id = ?").bind(u.id).first(),
    c.env.DB.prepare("SELECT id_hash, created_at, last_seen_at, user_agent FROM sessions WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ? ORDER BY last_seen_at DESC").bind(u.id, nowIso()).all(),
    c.env.DB.prepare("SELECT email, created_at FROM oauth_accounts WHERE user_id = ? AND provider = 'google'").bind(u.id).first(),
  ]);
  const flash = FLASH[c.url.searchParams.get("ok")];
  const p = prefs || {};
  const toggle = (name, label, hint, on) => html`<div class="field"><label class="check"><input type="checkbox" name="${name}" value="1" ${on ? raw("checked") : ""}>
    <span><strong>${label}</strong><span class="field-hint">${hint}</span></span></label></div>`;
  const credName = u.credential_name || u.display_name;

  const body = html`${pageHead({ eyebrow: t("account.eyebrow"), title: t("account.title"), crumbs: [[t("nav.dashboard"), "/dashboard"], [t("account.title")]] })}
  <section class="section-tight"><div class="wrap medium">
    ${flash ? alert("success", t(flash)) : ""}
    ${errors._form ? alert("error", t(errors._form)) : ""}

    <form class="form-card" method="post" action="/account/profile" id="profile">
      ${csrfField(c)}<h2 class="h2">${t("account.profile")}</h2>
      <div class="grid-2">
        ${field(c, { name: "display_name", label: t("form.full_name"), value: u.display_name, required: true, autocomplete: "name", error: errors.display_name && t(errors.display_name) })}
        ${field(c, { name: "credential_name", label: t("account.credential_name"), value: u.credential_name, hint: t("account.credential_name_hint") })}
      </div>
      ${!pdfRepresentable(credName) ? alert("info", t("cert.pdf_script_note")) : ""}
      <div class="grid-2">
        ${selectField(c, { name: "locale", label: t("form.language"), required: true, value: u.locale, options: LOCALES.map((l) => [l.code, `${l.nativeName} · ${l.englishName}`]) })}
        ${selectField(c, { name: "country", label: t("form.country"), value: u.country, options: [["", t("form.choose")], ...countryOptions(c)] })}
        ${selectField(c, { name: "professional_role", label: t("form.role"), value: u.professional_role, options: [["", t("form.choose")], ...PROFESSIONAL_ROLES.map((r) => [r, t(`role.${r}`)])] })}
        ${field(c, { name: "organization", label: t("account.organization"), value: u.organization, autocomplete: "organization" })}
      </div>
      <div class="field"><label for="f-bio">${t("account.bio")} <span class="muted small">(${t("form.optional")})</span></label><textarea id="f-bio" name="bio" maxlength="600">${u.bio || ""}</textarea></div>
      <p class="small muted">${t("account.email_label")}: <strong>${u.email}</strong> ${u.email_verified_at ? html`<span class="badge badge-green">${t("account.verified")}</span>` : html`<span class="badge badge-warn">${t("account.unverified")}</span>`}</p>
      <button class="btn btn-primary" type="submit">${t("action.save")}</button>
    </form>

    <form class="form-card mt-3" method="post" action="/account/preferences" id="notifications">
      ${csrfField(c)}<h2 class="h2">${t("account.notifications")}</h2>
      <p class="small muted">${t("account.notifications_lead")}</p>
      ${toggle("notify_course_updates", t("account.pref_updates"), t("account.pref_updates_hint"), p.notify_course_updates)}
      ${toggle("notify_course_reminders", t("account.pref_reminders"), t("account.pref_reminders_hint"), p.notify_course_reminders)}
      <h2 class="h2 mt-3">${t("account.privacy")}</h2>
      ${toggle("share_country_analytics", t("account.pref_country"), t("account.pref_country_hint"), p.share_country_analytics)}
      <button class="btn btn-primary" type="submit">${t("action.save")}</button>
    </form>

    <form class="form-card mt-3" method="post" action="/account/password" id="password">
      ${csrfField(c)}<h2 class="h2">${u.has_password ? t("account.change_password") : t("account.set_password")}</h2>
      ${errors.password ? alert("error", t(errors.password)) : ""}
      ${u.has_password ? field(c, { name: "current_password", label: t("form.current_password"), type: "password", required: true, autocomplete: "current-password" }) : html`<p class="small muted">${t("account.no_password_yet")}</p>`}
      ${field(c, { name: "new_password", label: t("form.new_password"), type: "password", required: true, autocomplete: "new-password", hint: t("auth.password_hint"), attrs: 'minlength="10" maxlength="200"' })}
      <button class="btn btn-primary" type="submit">${t("auth.set_password")}</button>
    </form>

    <section class="form-card mt-3" id="sessions"><h2 class="h2">${t("account.sessions")}</h2>
      <ul>${sessions.results.map((s) => html`<li class="list-row"><div class="grow small">${s.user_agent || t("account.unknown_device")}<div class="tiny muted">${t("account.last_active", { date: c.fmtDate(s.last_seen_at, { dateStyle: "medium", timeStyle: "short" }) })}</div></div>
        ${s.id_hash === c.session.idHash ? html`<span class="badge badge-green">${t("account.this_device")}</span>` : ""}</li>`)}</ul>
      ${sessions.results.length > 1 ? html`<form method="post" action="/account/sessions/revoke">${csrfField(c)}<button class="btn btn-secondary" type="submit">${t("account.sign_out_others")}</button></form>` : ""}
      ${google ? html`<p class="small mt-2">${t("account.google_linked", { email: google.email })}</p>` : ""}
    </section>

    <section class="form-card mt-3" id="data"><h2 class="h2">${t("account.your_data")}</h2>
      <p class="small muted">${t("account.export_lead")}</p>
      <a class="btn btn-secondary" href="/account/export" download>${t("account.export")}</a>
    </section>

    <form class="form-card mt-3" method="post" action="/account/delete" id="delete" data-confirm="${t("account.delete_confirm_dialog")}">
      ${csrfField(c)}<h2 class="h2">${t("account.delete_title")}</h2>
      <p class="small">${t("account.delete_lead")}</p>
      ${errors.delete ? alert("error", t(errors.delete)) : ""}
      ${u.has_password ? field(c, { name: "password", label: t("form.current_password"), type: "password", required: true, autocomplete: "current-password" }) : ""}
      ${field(c, { name: "confirm", label: t("account.delete_type", { word: "DELETE" }), required: true, attrs: 'autocomplete="off" spellcheck="false"' })}
      <button class="btn btn-danger" type="submit">${t("account.delete_button")}</button>
    </form>
  </div></section>`;
  return c.page({ title: t("account.title"), body, noindex: true, status: Object.keys(errors).length ? 422 : 200 });
}

export async function saveProfile(c) {
  const b = await c.readBody();
  const name = String(b.display_name || "").trim().replace(/\s+/g, " ").slice(0, 120);
  if (name.length < 2) return accountPage(c, { errors: { display_name: "form.error.name" } });
  const locale = matchLocale(b.locale) || c.user.locale;
  const credentialName = String(b.credential_name || "").trim().replace(/\s+/g, " ").slice(0, 120) || null;
  await c.env.DB.prepare(
    "UPDATE users SET display_name = ?, credential_name = ?, locale = ?, country = ?, professional_role = ?, organization = ?, bio = ?, updated_at = ? WHERE id = ?",
  )
    .bind(
      name,
      credentialName,
      locale,
      COUNTRY_CODES.includes(b.country) ? b.country : null,
      PROFESSIONAL_ROLES.includes(b.professional_role) ? b.professional_role : null,
      String(b.organization || "").trim().slice(0, 160) || null,
      String(b.bio || "").trim().slice(0, 600) || null,
      nowIso(),
      c.user.id,
    )
    .run();
  c.setCookie(serializeCookie("aca_lang", locale, { maxAge: 31536000, secure: c.cfg.secure, httpOnly: false }));
  return redirect("/account?ok=saved");
}

export async function savePreferences(c) {
  const b = await c.readBody();
  const on = (k) => (b[k] === "1" ? 1 : 0);
  await c.env.DB.prepare(
    `INSERT INTO user_preferences (user_id, notify_course_reminders, notify_course_updates, share_country_analytics, updated_at) VALUES (?,?,?,?,?)
     ON CONFLICT(user_id) DO UPDATE SET notify_course_reminders = excluded.notify_course_reminders, notify_course_updates = excluded.notify_course_updates,
       share_country_analytics = excluded.share_country_analytics, updated_at = excluded.updated_at`,
  )
    .bind(c.user.id, on("notify_course_reminders"), on("notify_course_updates"), on("share_country_analytics"), nowIso())
    .run();
  return redirect("/account?ok=prefs#notifications");
}

export async function changePassword(c) {
  const b = await c.readBody();
  await rateLimit(c, "password-change", { limit: 10, windowSeconds: 3600, key: c.user.id });
  const row = await c.env.DB.prepare("SELECT password_hash FROM users WHERE id = ?").bind(c.user.id).first();
  if (row.password_hash && !(await verifyPassword(String(b.current_password || ""), row.password_hash))) return accountPage(c, { errors: { password: "auth.error.current_password" } });
  const problem = passwordProblem(String(b.new_password || ""), c.user.email);
  if (problem) return accountPage(c, { errors: { password: problem } });
  await setPassword(c.env, c.user.id, String(b.new_password), c.session.idHash);
  await audit(c, "user.password_change", "user", c.user.id);
  await sendEmail(c, { user: c.user, template: "password_changed", vars: { url: `${c.cfg.origin}/forgot-password` } });
  return redirect("/account?ok=password#password");
}

export async function revokeOtherSessions(c) {
  await revokeAllSessions(c.env, c.user.id, c.session.idHash);
  await audit(c, "user.sessions_revoke", "user", c.user.id);
  return redirect("/account?ok=sessions#sessions");
}

export async function exportData(c) {
  await rateLimit(c, "export", { limit: 10, windowSeconds: 3600, key: c.user.id });
  const q = (sql) => c.env.DB.prepare(sql).bind(c.user.id).all().then((r) => r.results);
  const { password_hash, failed_logins, locked_until, ...profile } = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(c.user.id).first();
  void password_hash, failed_logins, locked_until;
  const data = {
    exported_at: nowIso(),
    service: "AGRO-AI Academy",
    profile,
    preferences: await c.env.DB.prepare("SELECT * FROM user_preferences WHERE user_id = ?").bind(c.user.id).first(),
    roles: await q("SELECT role, granted_at FROM user_roles WHERE user_id = ?"),
    enrollments: await q("SELECT course_id, status, progress_pct, enrolled_at, completed_at FROM enrollments WHERE user_id = ?"),
    lesson_progress: await q("SELECT lesson_id, course_id, status, position_seconds, started_at, completed_at, last_viewed_at FROM lesson_progress WHERE user_id = ?"),
    notes: await q("SELECT lesson_id, body, position_seconds, created_at FROM notes WHERE user_id = ?"),
    bookmarks: await q("SELECT lesson_id, position_seconds, label, created_at FROM bookmarks WHERE user_id = ?"),
    goals: await q("SELECT title, weekly_minutes, target_date, status, created_at FROM learning_goals WHERE user_id = ?"),
    attempts: await q("SELECT assessment_id, attempt_no, status, started_at, submitted_at, score_pct, passed FROM attempts WHERE user_id = ?"),
    certificates: await q("SELECT credential_id, course_title, credential_name, issued_at, status FROM certificates WHERE user_id = ?"),
    achievements: await q("SELECT code, earned_at FROM achievements WHERE user_id = ?"),
    course_feedback: await q("SELECT course_id, rating, comment, created_at FROM course_feedback WHERE user_id = ?"),
  };
  return new Response(JSON.stringify(data, null, 2), {
    headers: { "Content-Type": "application/json; charset=utf-8", "Content-Disposition": 'attachment; filename="agroai-academy-data.json"', "Cache-Control": "no-store" },
  });
}

export async function deleteAccountAction(c) {
  const b = await c.readBody();
  await rateLimit(c, "delete-account", { limit: 5, windowSeconds: 3600, key: c.user.id });
  if (String(b.confirm || "").trim() !== "DELETE") return accountPage(c, { errors: { delete: "account.delete_error_confirm" } });
  const row = await c.env.DB.prepare("SELECT password_hash FROM users WHERE id = ?").bind(c.user.id).first();
  if (row.password_hash && !(await verifyPassword(String(b.password || ""), row.password_hash))) return accountPage(c, { errors: { delete: "auth.error.current_password" } });
  if (c.roles.includes("super_admin")) {
    const others = await c.env.DB.prepare("SELECT COUNT(*) AS n FROM user_roles WHERE role = 'super_admin' AND user_id != ?").bind(c.user.id).first();
    if (!others.n) throw new HttpError(409, "last_super_admin");
  }
  // Queue the confirmation before personal data is erased; the outbox row is
  // removed with the account, so deliver it immediately.
  const user = { ...c.user };
  const mailId = await queueEmail(c.env, c.cfg, { user, template: "account_deleted", vars: {} });
  if (mailId) await deliverById(c.env, c.cfg, mailId);
  await deleteAccount(c.env, user.id, user.id);
  c.setCookie(serializeCookie(cookieNames(c.cfg).session, "", { maxAge: 0, secure: c.cfg.secure }));
  return redirect("/login?deleted=1");
}
