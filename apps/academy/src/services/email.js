// Transactional email: localized templates, a durable outbox, and delivery
// through Resend (AGRO-AI's existing email provider). Nothing is sent when the
// provider is not configured; messages are kept as 'unconfigured' instead.
import { newId, nowIso } from "../lib/util.js";
import { escapeHtml } from "../lib/html.js";
import { makeTranslator, loadOverrides, localeInfo, displayLocale } from "../lib/i18n.js";
import { BRAND } from "../brand.js";

const TEMPLATES = {
  verify_email: { category: "security", cta: "email.verify.cta" },
  password_reset: { category: "security", cta: "email.reset.cta" },
  password_changed: { category: "security", cta: "email.reset.cta" },
  account_deleted: { category: "security" },
  welcome: { category: "transactional", cta: "email.welcome.cta" },
  early_access_invite: { category: "transactional", cta: "email.early_access_invite.cta" },
  enrollment: { category: "transactional", cta: "email.enrollment.cta", pref: "notify_course_updates" },
  course_complete: { category: "transactional", cta: "email.course_complete.cta", pref: "notify_course_updates" },
  exam_passed: { category: "transactional", cta: "email.exam_result.cta" },
  exam_failed: { category: "transactional", cta: "email.exam_result.cta" },
  certificate_issued: { category: "transactional", cta: "email.certificate.cta" },
  course_reminder: { category: "reminder", cta: "email.reminder.cta", pref: "notify_course_reminders" },
};

// Email-safe brand styling: inline styles only, web-safe fallbacks for the
// brand typeface, and an opaque logo image (some clients mishandle alpha).
const C = BRAND.colors;
const HEAD_FONT = "'Glacial Indifference','Century Gothic','Avenir Next',Avenir,'Helvetica Neue',Arial,sans-serif";
const BODY_FONT = "-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif";

function renderEmail(t, cfg, template, vars) {
  const dir = localeInfo(t.locale).dir;
  const subject = t(`email.${template}.subject`, vars);
  const paragraphs = t(`email.${template}.body`, vars).split("\n\n");
  const spec = TEMPLATES[template];
  const ctaLabel = spec.cta ? t(spec.cta, vars) : null;
  const url = vars.url;
  const footer = t("email.footer", { support: cfg.supportEmail });
  const html = `<!doctype html><html lang="${escapeHtml(t.locale)}" dir="${dir}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta name="color-scheme" content="light"><title>${escapeHtml(subject)}</title></head>
<body style="margin:0;background:#f2f4ec;font-family:${BODY_FONT};color:${C.ink}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f4ec;padding:32px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #e1e6d8">
<tr><td height="6" style="height:6px;line-height:6px;font-size:0;background:${C.green};background-image:linear-gradient(90deg,${C.forest},${C.leafBright} 70%,${C.lime})">&nbsp;</td></tr>
<tr><td style="padding:26px 32px 4px"><img src="${cfg.origin}/static/${BRAND.logo.email}" width="128" height="44" alt="${BRAND.name}" style="display:block;border:0;height:44px;width:auto"></td></tr>
<tr><td style="padding:22px 32px 8px;font-size:16px;line-height:1.6">
<h1 style="font-family:${HEAD_FONT};font-weight:700;font-size:25px;line-height:1.25;margin:0 0 16px;color:${C.ink};letter-spacing:-0.01em">${escapeHtml(subject)}</h1>
${paragraphs.map((p) => `<p style="margin:0 0 14px">${escapeHtml(p)}</p>`).join("")}
${ctaLabel && url ? `<p style="margin:26px 0"><a href="${escapeHtml(url)}" style="display:inline-block;background:${C.green};color:#ffffff;text-decoration:none;font-family:${HEAD_FONT};font-weight:700;font-size:16px;padding:14px 26px;border-radius:999px">${escapeHtml(ctaLabel)}</a></p><p style="font-size:13px;color:${C.muted};word-break:break-all">${escapeHtml(url)}</p>` : ""}
</td></tr>
<tr><td style="padding:18px 32px 28px;font-size:12px;line-height:1.55;color:${C.muted};border-top:1px solid #e1e6d8">${escapeHtml(footer)}<br>AGRO-AI Inc. · San Francisco, California · <a href="${cfg.origin}/account" style="color:${C.green}">${escapeHtml(t("email.manage_preferences"))}</a></td></tr>
</table></td></tr></table></body></html>`;
  const text = [subject, "", ...paragraphs, "", ctaLabel && url ? `${ctaLabel}: ${url}` : "", "", footer, "AGRO-AI Inc. · San Francisco, California"].filter((x) => x !== null).join("\n");
  return { subject, html, text, category: spec.category };
}

export const STAGING_TEST_DOMAIN = "academy-staging-test.invalid";
export const isStagingTestAddress = (email) => String(email || "").toLowerCase().endsWith(`@${STAGING_TEST_DOMAIN}`);

/**
 * Queue a templated email for a user. Returns the outbox row id, or null when
 * the learner's preferences opt out of this category.
 */
export async function queueEmail(env, cfg, { user, template, vars = {}, to = null }) {
  const spec = TEMPLATES[template];
  if (!spec) throw new Error(`unknown email template ${template}`);
  if (spec.pref && user?.id) {
    const pref = await env.DB.prepare(`SELECT ${spec.pref} AS on_ FROM user_preferences WHERE user_id = ?`).bind(user.id).first();
    if (pref && !pref.on_) return null;
  }
  // Written in the learner's language when the interface is translated into
  // it, otherwise in English (and laid out as English).
  const t = makeTranslator(displayLocale(user?.locale || "en"), await loadOverrides(env));
  const msg = renderEmail(t, cfg, template, { name: user?.display_name || "", ...vars });
  const id = newId("em_");
  const address = to || user.email;
  // Synthetic staging test accounts use the reserved .invalid domain and are never sent.
  const status = cfg.environment === "staging" && isStagingTestAddress(address) ? "suppressed" : cfg.emailEnabled ? "pending" : "unconfigured";
  await env.DB.prepare(
    `INSERT INTO email_outbox (id, user_id, to_email, template, category, locale, subject, html, text, status, created_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?)`,
  )
    .bind(id, user?.id ?? null, address, template, msg.category, t.locale, msg.subject, msg.html, msg.text, status, nowIso())
    .run();
  return id;
}

export async function deliver(env, cfg, row) {
  if (!cfg.emailEnabled) return false;
  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json", "Idempotency-Key": row.id },
      body: JSON.stringify({
        from: env.EMAIL_FROM,
        to: [row.to_email],
        reply_to: cfg.supportEmail,
        subject: row.subject,
        html: row.html,
        text: row.text,
        tags: [{ name: "product", value: "academy" }, { name: "template", value: row.template }],
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (res.ok) {
      await env.DB.prepare("UPDATE email_outbox SET status='sent', sent_at=?, provider_id=?, attempts=attempts+1, last_error=NULL WHERE id=?")
        .bind(nowIso(), String(body.id || ""), row.id)
        .run();
      return true;
    }
    const permanent = res.status >= 400 && res.status < 500 && res.status !== 429;
    await env.DB.prepare("UPDATE email_outbox SET status=?, attempts=attempts+1, last_error=? WHERE id=?")
      .bind(permanent ? "failed" : "pending", `HTTP ${res.status}: ${String(body.message || body.name || "").slice(0, 200)}`, row.id)
      .run();
  } catch (e) {
    await env.DB.prepare("UPDATE email_outbox SET attempts=attempts+1, last_error=? WHERE id=?").bind(String(e?.message || e).slice(0, 200), row.id).run();
  }
  return false;
}

export async function deliverById(env, cfg, id) {
  if (!id || !cfg.emailEnabled) return false;
  const row = await env.DB.prepare("SELECT * FROM email_outbox WHERE id = ? AND status = 'pending'").bind(id).first();
  return row ? deliver(env, cfg, row) : false;
}

/** Retry pending mail; used by the scheduled job. */
export async function flushOutbox(env, cfg, limit = 25) {
  if (!cfg.emailEnabled) return 0;
  const rows = (await env.DB.prepare("SELECT * FROM email_outbox WHERE status='pending' AND attempts < 6 ORDER BY created_at LIMIT ?").bind(limit).all()).results;
  let sent = 0;
  for (const r of rows) if (await deliver(env, cfg, r)) sent++;
  await env.DB.prepare("UPDATE email_outbox SET status='failed' WHERE status='pending' AND attempts >= 6").run();
  return sent;
}

/** Queue and attempt immediate delivery in the background. */
export async function sendEmail(c, args) {
  const id = await queueEmail(c.env, c.cfg, args);
  if (id) c.defer(deliverById(c.env, c.cfg, id));
  return id;
}
