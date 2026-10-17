// Learning events (analytics), in-app notifications and achievements.
import { newId, nowIso } from "../lib/util.js";

export function eventStmt(env, { userId = null, event, courseId = null, lessonId = null, locale = null, country = null }) {
  return env.DB.prepare(
    "INSERT INTO learning_events (id, user_id, event, course_id, lesson_id, locale, country, created_at) VALUES (?,?,?,?,?,?,?,?)",
  ).bind(newId("ev_"), userId, event, courseId, lessonId, locale, country, nowIso());
}

/** Record an event; country is attached only when the learner opted in. */
export async function track(env, user, event, extra = {}) {
  let country = null;
  if (user?.id && user.country) {
    const pref = await env.DB.prepare("SELECT share_country_analytics FROM user_preferences WHERE user_id = ?").bind(user.id).first();
    if (pref?.share_country_analytics) country = user.country;
  }
  await eventStmt(env, { userId: user?.id ?? null, event, locale: user?.locale ?? extra.locale ?? null, country, ...extra }).run();
}

export function notifyStmt(env, userId, { kind, title, body = "", url = null }) {
  return env.DB.prepare("INSERT INTO notifications (id, user_id, kind, title, body, url, created_at) VALUES (?,?,?,?,?,?,?)").bind(
    newId("nt_"),
    userId,
    kind,
    title,
    body,
    url,
    nowIso(),
  );
}

export const ACHIEVEMENTS = [
  { code: "first_enrollment", icon: "book" },
  { code: "first_lesson", icon: "play" },
  { code: "ten_lessons", icon: "layers" },
  { code: "first_quiz_pass", icon: "check-circle" },
  { code: "perfect_score", icon: "star" },
  { code: "first_course", icon: "trophy" },
  { code: "first_certificate", icon: "award" },
  { code: "three_certificates", icon: "graduation" },
];

export async function grantAchievement(env, userId, code, detail = null) {
  const res = await env.DB.prepare("INSERT OR IGNORE INTO achievements (user_id, code, detail, earned_at) VALUES (?,?,?,?)")
    .bind(userId, code, detail, nowIso())
    .run();
  return res.meta.changes > 0;
}

export async function listAchievements(env, userId) {
  const rows = (await env.DB.prepare("SELECT code, detail, earned_at FROM achievements WHERE user_id = ?").bind(userId).all()).results;
  const earned = new Map(rows.map((r) => [r.code, r]));
  return ACHIEVEMENTS.map((a) => ({ ...a, earned: earned.get(a.code) || null }));
}
