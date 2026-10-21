// Registration, sign-in, email verification, password reset and Google sign-in.
import { html, raw } from "../lib/html.js";
import { redirect, HttpError, serializeCookie } from "../lib/http.js";
import { nowIso, addSeconds, randomToken, sha256Hex, b64url } from "../lib/util.js";
import { createSession, destroySession, verifyPassword, passwordProblem, rateLimit, cookieNames, audit, auditStmt, hashPassword } from "../lib/security.js";
import { LOCALES, matchLocale, TRANSLATED_INTERFACE_COUNT } from "../lib/i18n.js";
import countries from "../../../../shared/registries/countries.json" with { type: "json" };
import { icon } from "../views/icons.js";
import { asset } from "../views/assets.js";
import { BRAND } from "../brand.js";
import { artSvg } from "../views/art.js";
import { alert, csrfField, field, selectField } from "../views/components.js";
import { createUser, findUserByEmail, normalizeEmail, validEmail, issueToken, consumeToken, peekToken, setPassword, applyBootstrapRoles, PROFESSIONAL_ROLES } from "../services/users.js";
import { sendEmail } from "../services/email.js";
import { issueIfEligible } from "../services/certificates.js";
import { linkVerifiedUser } from "../services/earlyAccess.js";

export const COUNTRY_CODES = countries.countries.filter((x) => x.iso3166_assigned !== false).map((x) => x.code);

export function countryOptions(c) {
  let names;
  try {
    names = new Intl.DisplayNames([c.displayLocale, "en"], { type: "region" });
  } catch {
    names = new Intl.DisplayNames(["en"], { type: "region" });
  }
  return COUNTRY_CODES.map((code) => [code, names.of(code) || code]).sort((a, b) => a[1].localeCompare(b[1], c.displayLocale));
}

export function safeNext(next, fallback = "/dashboard") {
  const s = typeof next === "string" ? next : "";
  return s.startsWith("/") && !s.startsWith("//") && !s.startsWith("/\\") ? s : fallback;
}

function authShell(c, { title, body }) {
  const t = c.t;
  return c.page({
    title,
    noindex: true,
    body: html`<div class="auth-page">
      <aside class="auth-aside">${raw(artSvg("contours", "auth", "green", 800, 1000).replace("<svg ", '<svg class="bg-art" '))}
        <img class="auth-lockup" src="${asset(BRAND.logo.stackedLight)}" alt="${BRAND.name}" width="${BRAND.stackedSize.width}" height="${BRAND.stackedSize.height}">
        <h2>${t("auth.aside_title")}</h2>
        <ul class="check-list">${["free", "certificates", "languages", "progress"].map((k) => html`<li>${icon("check-circle", { size: 18 })} <span>${t(`auth.aside.${k}`, { n: LOCALES.length, translated: TRANSLATED_INTERFACE_COUNT })}</span></li>`)}</ul>
      </aside>
      <div class="auth-main"><div class="form-wrap">${body}</div></div>
    </div>`,
  });
}

function googleButton(c, next) {
  if (!c.cfg.googleEnabled) return "";
  return html`<a class="btn btn-secondary btn-block google-btn" href="/auth/google?next=${encodeURIComponent(next || "/dashboard")}">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.2-2.1 3.5-5.1 3.5-8.7z"/><path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z"/><path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8z"/><path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.8 3.6-4.9 6.7-4.9z"/></svg>
      ${c.t("auth.continue_google")}</a><div class="divider">${c.t("auth.or")}</div>`;
}

// ───────────── Registration ─────────────

export async function registerPage(c, { errors = {}, values = {} } = {}) {
  if (c.user) return redirect("/dashboard");
  const t = c.t;
  const next = safeNext(values.next ?? c.url.searchParams.get("next"));
  const body = html`
    <p class="eyebrow">${t("auth.register_eyebrow")}</p>
    <h1 class="display-sm">${t("auth.register_title")}</h1>
    <p class="muted">${t("auth.register_lead")}</p>
    ${errors._form ? alert("error", t(errors._form)) : ""}
    ${googleButton(c, next)}
    <form method="post" action="/register" novalidate>
      ${csrfField(c)}<input type="hidden" name="next" value="${next}">
      ${field(c, { name: "display_name", label: t("form.full_name"), value: values.display_name, required: true, autocomplete: "name", hint: t("auth.name_hint"), error: errors.display_name && t(errors.display_name) })}
      ${field(c, { name: "email", label: t("form.email"), type: "email", value: values.email, required: true, autocomplete: "email", error: errors.email && t(errors.email) })}
      ${field(c, { name: "password", label: t("form.password"), type: "password", required: true, autocomplete: "new-password", hint: t("auth.password_hint"), error: errors.password && t(errors.password), attrs: 'minlength="10" maxlength="200"' })}
      ${selectField(c, { name: "locale", label: t("form.language"), required: true, value: values.locale || c.locale, options: LOCALES.map((l) => [l.code, `${l.nativeName} · ${l.englishName}`]) })}
      <div class="grid-2">
        ${selectField(c, { name: "professional_role", label: t("form.role"), value: values.professional_role, options: [["", t("form.choose")], ...PROFESSIONAL_ROLES.map((r) => [r, t(`role.${r}`)])] })}
        ${selectField(c, { name: "country", label: t("form.country"), value: values.country, options: [["", t("form.choose")], ...countryOptions(c)] })}
      </div>
      <div class="field"><label class="check"><input type="checkbox" name="accept_terms" value="1" required ${values.accept_terms ? raw("checked") : ""}>
        <span>${raw(t("auth.accept_terms_html"))}</span></label>${errors.accept_terms ? html`<p class="field-error">${t(errors.accept_terms)}</p>` : ""}</div>
      <div class="field"><label class="check"><input type="checkbox" name="reminders" value="1" ${values.reminders ? raw("checked") : ""}><span>${t("auth.opt_in_reminders")}</span></label></div>
      <div class="sr-only" aria-hidden="true"><label for="f-website">Website</label><input id="f-website" name="website" tabindex="-1" autocomplete="off"></div>
      <button class="btn btn-primary btn-block btn-lg" type="submit">${t("auth.create_account")}</button>
    </form>
    <p class="center mt-3">${t("auth.have_account")} <a href="/login${next !== "/dashboard" ? `?next=${encodeURIComponent(next)}` : ""}">${t("nav.sign_in")}</a></p>`;
  const res = await authShell(c, { title: t("auth.register_title"), body });
  return Object.keys(errors).length ? new Response(res.body, { status: 422, headers: res.headers }) : res;
}

export async function register(c) {
  const b = await c.readBody();
  if (b.website) return redirect("/register");
  await rateLimit(c, "register", { limit: 10, windowSeconds: 3600 });
  const values = {
    display_name: String(b.display_name || "").trim().replace(/\s+/g, " ").slice(0, 120),
    email: normalizeEmail(b.email),
    locale: matchLocale(b.locale) || c.locale,
    professional_role: PROFESSIONAL_ROLES.includes(b.professional_role) ? b.professional_role : null,
    country: COUNTRY_CODES.includes(b.country) ? b.country : null,
    accept_terms: b.accept_terms === "1",
    reminders: b.reminders === "1",
    next: safeNext(b.next),
  };
  const errors = {};
  if (values.display_name.length < 2) errors.display_name = "form.error.name";
  if (!validEmail(values.email)) errors.email = "form.error.email";
  const pw = passwordProblem(String(b.password || ""), values.email);
  if (pw) errors.password = pw;
  if (!values.accept_terms) errors.accept_terms = "auth.error.terms";
  if (!errors.email && (await findUserByEmail(c.env, values.email))) errors.email = "auth.error.email_taken";
  if (Object.keys(errors).length) return registerPage(c, { errors, values });

  let userId;
  try {
    userId = await createUser(c.env, c.cfg, { email: values.email, password: String(b.password), displayName: values.display_name, locale: values.locale, country: values.country, professionalRole: values.professional_role });
  } catch (e) {
    if (e instanceof HttpError && e.code === "email_taken") return registerPage(c, { errors: { email: "auth.error.email_taken" }, values });
    throw e;
  }
  if (values.reminders) await c.env.DB.prepare("UPDATE user_preferences SET notify_course_reminders = 1 WHERE user_id = ?").bind(userId).run();
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(userId).first();
  const token = await issueToken(c.env, userId, "verify_email");
  await sendEmail(c, { user, template: "verify_email", vars: { url: `${c.cfg.origin}/verify-email?token=${token}` } });
  await createSession(c, userId);
  c.setCookie(serializeCookie("aca_lang", values.locale, { maxAge: 31536000, secure: c.cfg.secure, httpOnly: false }));
  return redirect(values.next === "/dashboard" ? "/dashboard?welcome=1" : values.next);
}

// ───────────── Sign in / out ─────────────

export async function loginPage(c, { error = null, email = "", status = 200 } = {}) {
  if (c.user) return redirect(safeNext(c.url.searchParams.get("next")));
  const t = c.t;
  const next = safeNext(c.url.searchParams.get("next") || c.body?.next);
  const reset = c.url.searchParams.get("reset") === "1";
  const body = html`
    <p class="eyebrow">${t("auth.login_eyebrow")}</p>
    <h1 class="display-sm">${t("auth.login_title")}</h1>
    ${reset ? alert("success", t("auth.password_updated")) : ""}
    ${c.url.searchParams.get("deleted") === "1" ? alert("success", t("account.deleted")) : ""}
    ${error ? alert("error", t(error)) : ""}
    ${googleButton(c, next)}
    <form method="post" action="/login">
      ${csrfField(c)}<input type="hidden" name="next" value="${next}">
      ${field(c, { name: "email", label: t("form.email"), type: "email", value: email, required: true, autocomplete: "email" })}
      ${field(c, { name: "password", label: t("form.password"), type: "password", required: true, autocomplete: "current-password" })}
      <p class="small"><a href="/forgot-password">${t("auth.forgot")}</a></p>
      <button class="btn btn-primary btn-block btn-lg" type="submit">${t("nav.sign_in")}</button>
    </form>
    <p class="center mt-3">${t("auth.no_account")} <a href="/register${next !== "/dashboard" ? `?next=${encodeURIComponent(next)}` : ""}">${t("auth.create_free")}</a></p>
    <p class="center small muted">${t("auth.portal_note")}</p>`;
  const res = await authShell(c, { title: t("auth.login_title"), body });
  return status === 200 ? res : new Response(res.body, { status, headers: res.headers });
}

const DUMMY_HASH = "pbkdf2_sha256$100000$AAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

export async function login(c) {
  const b = await c.readBody();
  await rateLimit(c, "login", { limit: 20, windowSeconds: 900 });
  const email = normalizeEmail(b.email);
  const password = String(b.password || "");
  await rateLimit(c, "login-account", { limit: 10, windowSeconds: 900, key: (await sha256Hex(email)).slice(0, 32) });
  const user = validEmail(email) ? await findUserByEmail(c.env, email) : null;
  const now = nowIso();
  if (user?.locked_until && user.locked_until > now) return loginPage(c, { error: "auth.error.locked", email, status: 429 });
  const ok = await verifyPassword(password, user?.password_hash || DUMMY_HASH);
  if (!user || !ok || user.status !== "active") {
    if (user) {
      const fails = (user.failed_logins || 0) + 1;
      await c.env.DB.prepare("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?").bind(fails, fails >= 5 ? addSeconds(now, 900) : null, user.id).run();
    }
    return loginPage(c, { error: user && !user.password_hash ? "auth.error.use_google" : "auth.error.invalid", email, status: 401 });
  }
  await c.env.DB.prepare("UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = ? WHERE id = ?").bind(now, user.id).run();
  await applyBootstrapRoles(c.env, c.cfg, user);
  await createSession(c, user.id);
  return redirect(safeNext(b.next));
}

export async function logout(c) {
  await destroySession(c);
  return redirect("/");
}

// ───────────── Email verification ─────────────

function verifyFailed(c) {
  return c.page({
    title: c.t("auth.verify_failed_title"),
    noindex: true,
    status: 400,
    body: html`<section class="wrap narrow error-page"><h1 class="display-sm">${c.t("auth.verify_failed_title")}</h1><p class="lead">${c.t("auth.verify_failed_body")}</p>
      <div class="actions"><a class="btn btn-primary" href="${c.user ? "/dashboard" : "/login"}">${c.user ? c.t("nav.dashboard") : c.t("nav.sign_in")}</a></div></section>`,
  });
}

/**
 * The emailed link only shows a confirmation button. Mail scanners and link
 * previews follow GET links automatically, so the token is consumed only by
 * the person's own (CSRF-protected) POST; a scanner can never verify an
 * address on someone else's behalf.
 */
export async function verifyEmailPage(c) {
  const token = String(c.url.searchParams.get("token") || "");
  if (!(await peekToken(c.env, token, "verify_email"))) return verifyFailed(c);
  return c.page({
    title: c.t("auth.verify_confirm_title"),
    noindex: true,
    body: html`<section class="wrap narrow section"><h1 class="display-sm">${c.t("auth.verify_confirm_title")}</h1><p class="lead">${c.t("auth.verify_confirm_body")}</p>
      <form method="post" action="/verify-email" class="actions">${csrfField(c)}<input type="hidden" name="token" value="${token}">
        <button class="btn btn-primary" type="submit">${c.t("auth.verify_confirm_button")}</button></form></section>`,
  });
}

export async function verifyEmail(c) {
  const b = await c.readBody();
  const userId = await consumeToken(c.env, String(b.token || ""), "verify_email");
  if (!userId) return verifyFailed(c);
  const now = nowIso();
  // Whoever chose the password of an unverified account may not own the
  // address (pre-account hijacking). Proving the mailbox signs out every other
  // session; unless the confirmation comes from the registrant's own signed-in
  // session, the password is cleared too and the mailbox owner sets a new one.
  const own = c.user?.id === userId;
  const unverified = "EXISTS (SELECT 1 FROM users WHERE id = ?3 AND email_verified_at IS NULL)";
  const results = await c.env.DB.batch([
    c.env.DB.prepare(`UPDATE sessions SET revoked_at = ?1 WHERE user_id = ?3 AND revoked_at IS NULL AND id_hash IS NOT ?2 AND ${unverified}`).bind(now, own ? c.session.idHash : null, userId),
    ...(own ? [] : [c.env.DB.prepare(`UPDATE users SET password_hash = NULL, updated_at = ?1 WHERE id = ?2 AND email_verified_at IS NULL AND password_hash IS NOT NULL`).bind(now, userId)]),
    c.env.DB.prepare("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?1), updated_at = ?1 WHERE id = ?2").bind(now, userId),
  ]);
  const cleared = !own && results[1].meta.changes > 0;
  if (cleared) await audit({ ...c, user: { id: userId } }, "account.unverified_password_cleared", "user", userId, { via: "email_verification" });
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(userId).first();
  await applyBootstrapRoles(c.env, c.cfg, user);
  await linkVerifiedUser(c.env, user);
  await sendEmail(c, { user, template: "welcome", vars: { url: `${c.cfg.origin}/courses` } });
  // Learners who finished a course before verifying receive their credentials now.
  const done = (await c.env.DB.prepare("SELECT c.* FROM enrollments e JOIN courses c ON c.id = e.course_id WHERE e.user_id = ? AND e.status = 'completed'").bind(userId).all()).results;
  for (const course of done) await issueIfEligible(c.env, c.cfg, user, course, { defer: c.defer });
  if (cleared) return redirect(`/reset-password?token=${await issueToken(c.env, userId, "reset_password")}`);
  return redirect(own ? "/dashboard?verified=1" : "/login?verified=1");
}

export async function resendVerification(c) {
  if (c.user.email_verified_at) return redirect("/dashboard");
  await rateLimit(c, "resend-verify", { limit: 3, windowSeconds: 3600, key: c.user.id });
  const token = await issueToken(c.env, c.user.id, "verify_email");
  await sendEmail(c, { user: c.user, template: "verify_email", vars: { url: `${c.cfg.origin}/verify-email?token=${token}` } });
  return redirect("/dashboard?verification_sent=1");
}

// ───────────── Password reset ─────────────

export async function forgotPage(c, { sent = false } = {}) {
  const t = c.t;
  const body = html`<h1 class="display-sm">${t("auth.forgot_title")}</h1>
    ${sent ? alert("success", t("auth.reset_sent")) : html`<p class="muted">${t("auth.forgot_lead")}</p>`}
    <form method="post" action="/forgot-password">${csrfField(c)}
      ${field(c, { name: "email", label: t("form.email"), type: "email", required: true, autocomplete: "email" })}
      <button class="btn btn-primary btn-block" type="submit">${t("auth.send_reset")}</button></form>
    <p class="center mt-3"><a href="/login">${t("auth.back_to_sign_in")}</a></p>`;
  return authShell(c, { title: t("auth.forgot_title"), body });
}

export async function forgot(c) {
  const b = await c.readBody();
  await rateLimit(c, "forgot", { limit: 5, windowSeconds: 3600 });
  const email = normalizeEmail(b.email);
  // The response is identical whether or not the account exists.
  const user = validEmail(email) ? await findUserByEmail(c.env, email) : null;
  // Every address has its own limit, and hitting it only suppresses the mail,
  // so throttling never reveals whether an account exists.
  let withinLimit = true;
  if (validEmail(email)) {
    try {
      await rateLimit(c, "forgot-account", { limit: 3, windowSeconds: 3600, key: (await sha256Hex(email)).slice(0, 32) });
    } catch (e) {
      if (e?.status !== 429) throw e;
      withinLimit = false;
    }
  }
  if (withinLimit && user && user.status === "active") {
    const token = await issueToken(c.env, user.id, "reset_password");
    await sendEmail(c, { user, template: "password_reset", vars: { url: `${c.cfg.origin}/reset-password?token=${token}` } });
  }
  return forgotPage(c, { sent: true });
}

export async function resetPage(c, { error = null } = {}) {
  const t = c.t;
  const token = c.url.searchParams.get("token") || c.body?.token || "";
  const valid = await peekToken(c.env, token, "reset_password");
  const body = valid
    ? html`<h1 class="display-sm">${t("auth.reset_title")}</h1>${error ? alert("error", t(error)) : ""}
      <form method="post" action="/reset-password">${csrfField(c)}<input type="hidden" name="token" value="${token}">
        ${field(c, { name: "password", label: t("form.new_password"), type: "password", required: true, autocomplete: "new-password", hint: t("auth.password_hint"), attrs: 'minlength="10" maxlength="200"' })}
        <button class="btn btn-primary btn-block" type="submit">${t("auth.set_password")}</button></form>`
    : html`<h1 class="display-sm">${t("auth.reset_invalid_title")}</h1><p class="muted">${t("auth.reset_invalid_body")}</p><a class="btn btn-primary" href="/forgot-password">${t("auth.send_reset")}</a>`;
  return authShell(c, { title: t("auth.reset_title"), body });
}

export async function reset(c) {
  const b = await c.readBody();
  await rateLimit(c, "reset", { limit: 10, windowSeconds: 3600 });
  const token = String(b.token || "");
  const pending = await peekToken(c.env, token, "reset_password");
  if (!pending) return resetPage(c);
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(pending.user_id).first();
  const problem = passwordProblem(String(b.password || ""), user.email);
  if (problem) return resetPage(c, { error: problem });
  const userId = await consumeToken(c.env, token, "reset_password");
  if (!userId) return resetPage(c);
  await setPassword(c.env, userId, String(b.password));
  // Proving control of the inbox also verifies the address.
  await c.env.DB.prepare("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) WHERE id = ?").bind(nowIso(), userId).run();
  await linkVerifiedUser(c.env, { ...user, email_verified_at: user.email_verified_at || nowIso() });
  await audit({ ...c, user: { id: userId } }, "user.password_reset", "user", userId);
  await sendEmail(c, { user, template: "password_changed", vars: { url: `${c.cfg.origin}/forgot-password` } });
  return redirect("/login?reset=1");
}

// ───────────── Google sign-in (OpenID Connect, code flow + PKCE) ─────────────

export async function googleStart(c) {
  if (!c.cfg.googleEnabled) throw new HttpError(404, "not_found");
  await rateLimit(c, "google-start", { limit: 30, windowSeconds: 600 });
  const state = randomToken(24);
  const verifier = randomToken(48);
  const challenge = b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
  const next = safeNext(c.url.searchParams.get("next"));
  c.setCookie(serializeCookie(cookieNames(c.cfg).oauth, `${state}.${verifier}.${encodeURIComponent(next)}`, { maxAge: 600, secure: c.cfg.secure, sameSite: "Lax" }));
  const p = new URLSearchParams({
    client_id: c.env.GOOGLE_CLIENT_ID,
    redirect_uri: `${c.cfg.origin}/auth/google/callback`,
    response_type: "code",
    scope: "openid email profile",
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
    prompt: "select_account",
  });
  return redirect(`https://accounts.google.com/o/oauth2/v2/auth?${p}`, 302);
}

export async function googleCallback(c) {
  if (!c.cfg.googleEnabled) throw new HttpError(404, "not_found");
  const name = cookieNames(c.cfg).oauth;
  const [state, verifier, ...rest] = String(c.cookies[name] || "").split(".");
  const nextEnc = rest.join(".");
  c.setCookie(serializeCookie(name, "", { maxAge: 0, secure: c.cfg.secure }));
  const q = c.url.searchParams;
  if (!state || q.get("state") !== state || !q.get("code")) return loginPage(c, { error: "auth.error.google_failed", status: 400 });
  const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code: q.get("code"),
      client_id: c.env.GOOGLE_CLIENT_ID,
      client_secret: c.env.GOOGLE_CLIENT_SECRET,
      redirect_uri: `${c.cfg.origin}/auth/google/callback`,
      grant_type: "authorization_code",
      code_verifier: verifier,
    }),
  });
  if (!tokenRes.ok) return loginPage(c, { error: "auth.error.google_failed", status: 400 });
  const tokens = await tokenRes.json();
  const infoRes = await fetch("https://openidconnect.googleapis.com/v1/userinfo", { headers: { Authorization: `Bearer ${tokens.access_token}` } });
  if (!infoRes.ok) return loginPage(c, { error: "auth.error.google_failed", status: 400 });
  const info = await infoRes.json();
  if (!info.sub || !info.email || info.email_verified !== true) return loginPage(c, { error: "auth.error.google_unverified", status: 400 });

  const now = nowIso();
  let link = await c.env.DB.prepare("SELECT user_id FROM oauth_accounts WHERE provider = 'google' AND subject = ?").bind(String(info.sub)).first();
  let userId = link?.user_id;
  if (!userId) {
    const existing = await findUserByEmail(c.env, info.email);
    if (existing) {
      userId = existing.id;
      if (!existing.email_verified_at) {
        // The account was registered with this address but never verified, so
        // whoever chose its password may not own the address (pre-account
        // hijacking). Google has verified the owner: clear that password and
        // sign out every existing session before linking.
        await c.env.DB.batch([
          c.env.DB.prepare("UPDATE users SET password_hash = NULL, email_verified_at = ?, updated_at = ? WHERE id = ?").bind(now, now, userId),
          c.env.DB.prepare("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL").bind(now, userId),
          auditStmt(c.env, userId, "account.unverified_password_cleared", "user", userId, { provider: "google" }),
        ]);
      }
    } else {
      userId = await createUser(c.env, c.cfg, {
        email: info.email,
        displayName: String(info.name || info.email.split("@")[0]).slice(0, 120),
        locale: matchLocale(info.locale) || c.locale,
        verified: true,
      });
    }
    await c.env.DB.prepare("INSERT OR IGNORE INTO oauth_accounts (provider, subject, user_id, email, created_at) VALUES ('google', ?, ?, ?, ?)").bind(String(info.sub), userId, normalizeEmail(info.email), now).run();
  }
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(userId).first();
  if (!user || user.status !== "active") return loginPage(c, { error: "auth.error.invalid", status: 403 });
  await c.env.DB.prepare("UPDATE users SET last_login_at = ? WHERE id = ?").bind(now, userId).run();
  await applyBootstrapRoles(c.env, c.cfg, user);
  await linkVerifiedUser(c.env, user);
  await createSession(c, userId);
  return redirect(safeNext(decodeURIComponent(nextEnc || "")));
}

export { hashPassword };
