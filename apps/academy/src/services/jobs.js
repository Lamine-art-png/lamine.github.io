// Scheduled maintenance, run by the Worker cron trigger.
import { config } from "../app.js";
import { nowIso, addSeconds } from "../lib/util.js";
import { auditStmt } from "../lib/security.js";
import { flushOutbox, queueEmail } from "./email.js";
import { submitAttempt } from "./assessments.js";
import { publishReadiness } from "./readiness.js";
import { publishDraft } from "./drafts.js";
import { notifyStmt } from "./activity.js";

export async function runScheduled(env, cron = "") {
  const cfg = config(env, new URL(env.APP_ORIGIN || "http://localhost"));
  const pending = [];
  const ctx = { env, cfg, defer: (p) => pending.push(Promise.resolve(p).catch(() => {})), locale: "en" };
  const now = nowIso();
  const report = {};

  // 1. Publish courses whose scheduled time has arrived — only if they still
  // pass every readiness check (content may have changed since scheduling).
  // A course that no longer qualifies returns to review (shown as upcoming).
  const due = (await env.DB.prepare("SELECT * FROM courses WHERE status = 'scheduled' AND scheduled_at <= ?").bind(now).all()).results;
  report.published = 0;
  report.publicationBlocked = 0;
  for (const c of due) {
    const readiness = await publishReadiness(env, c);
    if (readiness.ok) {
      await publishDraft(env, c, { hash: readiness.hash, by: "schedule" });
      report.published++;
    } else {
      const failed = readiness.checks.filter((x) => !x.ok).map((x) => x.label);
      const publishers = (
        await env.DB.prepare("SELECT DISTINCT user_id FROM user_roles WHERE role IN ('super_admin','academy_admin')").all()
      ).results;
      await env.DB.batch([
        env.DB.prepare("UPDATE courses SET status = 'review', scheduled_at = NULL, updated_at = ? WHERE id = ? AND status = 'scheduled'").bind(now, c.id),
        auditStmt(env, null, "course.schedule.blocked", "course", c.id, { failed }),
        ...publishers.map((p) => notifyStmt(env, p.user_id, { kind: "admin", title: `Scheduled publication stopped: ${c.title}`, body: failed.join(" · ").slice(0, 400), url: `/admin/courses/${c.id}` })),
      ]);
      report.publicationBlocked++;
    }
  }

  // 2. Auto-submit timed attempts that ran past their deadline (graded on autosaved answers).
  const expired = (await env.DB.prepare("SELECT * FROM attempts WHERE status = 'in_progress' AND deadline_at IS NOT NULL AND deadline_at < ? LIMIT 100").bind(addSeconds(now, -120)).all()).results;
  for (const a of expired) {
    const user = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(a.user_id).first();
    if (user) await submitAttempt({ ...ctx, user }, a, { auto: true });
  }
  report.autoSubmitted = expired.length;

  // 3. Retry pending email.
  report.emailsSent = await flushOutbox(env, cfg, 50);

  // 4. Weekly reminders, only for learners who opted in and paused an active course.
  if (cron === "0 15 * * 1") {
    const idle = (
      await env.DB.prepare(
        `SELECT u.*, c.title AS course_title, c.slug AS course_slug FROM enrollments e
           JOIN users u ON u.id = e.user_id JOIN courses c ON c.id = e.course_id JOIN user_preferences p ON p.user_id = u.id
          WHERE e.status = 'active' AND p.notify_course_reminders = 1 AND u.status = 'active' AND u.email_verified_at IS NOT NULL
            AND e.last_activity_at < ? AND e.last_activity_at > ?
          GROUP BY u.id LIMIT 500`,
      )
        .bind(addSeconds(now, -7 * 86400), addSeconds(now, -60 * 86400))
        .all()
    ).results;
    for (const u of idle) await queueEmail(env, cfg, { user: u, template: "course_reminder", vars: { course: u.course_title, url: `${cfg.origin}/learn/${u.course_slug}` } });
    report.reminders = idle.length;
    await flushOutbox(env, cfg, 100);
  }

  // 5. Housekeeping.
  await env.DB.batch([
    env.DB.prepare("DELETE FROM sessions WHERE expires_at < ? OR (revoked_at IS NOT NULL AND revoked_at < ?)").bind(now, addSeconds(now, -7 * 86400)),
    env.DB.prepare("DELETE FROM auth_tokens WHERE expires_at < ?").bind(addSeconds(now, -86400)),
    env.DB.prepare("DELETE FROM rate_limits WHERE window_start < ?").bind(Math.floor(Date.now() / 1000) - 2 * 86400),
    env.DB.prepare("DELETE FROM email_outbox WHERE created_at < ? AND status IN ('sent','unconfigured','suppressed')").bind(addSeconds(now, -90 * 86400)),
  ]);
  await Promise.all(pending);
  return report;
}
