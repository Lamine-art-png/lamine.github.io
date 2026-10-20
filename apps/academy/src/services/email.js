// Transactional email: localized templates, a durable outbox, and delivery
// through Resend (AGRO-AI's existing email provider). Nothing is sent when the
// provider is not configured; messages are kept as 'unconfigured' instead.
import { newId, nowIso } from "../lib/util.js";
import { escapeHtml } from "../lib/html.js";
import { makeTranslator, loadOverrides, localeInfo } from "../lib/i18n.js";

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

function renderEmail(t, cfg, template, vars) {
  const dir = localeInfo(t.locale).dir;
  const subject = t(`email.${template}.subject`, vars);
  const paragraphs = t(`email.${template}.body`, vars).split("\n\n");
  const spec = TEMPLATES[template];
  const ctaLabel = spec.cta ? t(spec.cta, vars) : null;
  const url = vars.url;
  const footer = t("email.footer", { support: cfg.supportEmail });
  const html = `<!doctype html><html lang="${escapeHtml(t.locale)}" dir="${dir}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${escapeHtml(subject)}</title></head>
<body style="margin:0;background:#f3f2ec;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#10231b">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f2ec;padding:32px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e0e3d8">
<tr><td style="background:#1f3d27;padding:22px 28px;color:#ffffff;font-size:18px"><img src="${cfg.origin}/static/img/mark-64.png" width="28" height="28" alt="" style="vertical-align:middle;margin-inline-end:10px"><strong style="letter-spacing:.03em">AGRO-AI</strong> <span style="font-family:Georgia,serif">Academy</span></td></tr>
<tr><td style="padding:30px 28px 8px;font-size:16px;line-height:1.6">
<h1 style="font-family:Georgia,serif;font-weight:600;font-size:24px;line-height:1.25;margin:0 0 16px;color:#10231b">${escapeHtml(subject)}</h1>
${paragraphs.map((p) => `<p style="margin:0 0 14px">${escapeHtml(p)}</p>`).join("")}
${ctaLabel && url ? `<p style="margin:24px 0"><a href="${escapeHtml(url)}" style="display:inline-block;background:#1f3d27;color:#ffffff;text-decoration:none;font-weight:600;padding:13px 22px;border-radius:999px">${escapeHtml(ctaLabel)}</a></p><p style="font-size:13px;color:#5d6c62;word-break:break-all">${escapeHtml(url)}</p>` : ""}
</td></tr>
<tr><td style="padding:18px 28px 26px;font-size:12px;line-height:1.5;color:#5d6c62;border-top:1px solid #e0e3d8">${escapeHtml(footer)}<br>AGRO-AI Inc. · San Francisco, California · <a href="${cfg.origin}/account" style="color:#1f3d27">${escapeHtml(t("email.manage_preferences"))}</a></td></tr>
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
  const t = makeTranslator(user?.locale || "en", await loadOverrides(env));
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
