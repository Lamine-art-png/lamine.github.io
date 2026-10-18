// Curriculum queries and the content-translation overlay.
import { parseJson, sha256Hex } from "../lib/util.js";
import { HttpError } from "../lib/http.js";

export const VISIBLE_STATUSES = ["published", "scheduled", "review"];

/**
 * Overlay translated fields onto rows. For certification-grade content
 * (requireReviewed) only reviewed translations are used; everything else may
 * use clearly labelled machine drafts. A translation whose source changed
 * since it was written (recorded source hash no longer matches) is stale and
 * is not used; neither is a translated JSON field whose ids differ from the
 * source (e.g. options of an edited question). Each row gets a `_tr` descriptor.
 */
export async function localize(env, entityType, rows, fields, locale, { requireReviewed = false, sourceLocale = "en" } = {}) {
  const list = Array.isArray(rows) ? rows : [rows];
  if (!list.length || !list[0]) return rows;
  if (locale === sourceLocale) {
    for (const r of list) if (r) r._tr = { status: "source", fallback: false };
    return rows;
  }
  const ids = [...new Set(list.map((r) => r.id))];
  const found = new Map();
  for (let i = 0; i < ids.length; i += 90) {
    const slice = ids.slice(i, i + 90);
    const q = `SELECT entity_id, field, value, status, source_hash FROM content_translations WHERE entity_type = ? AND locale = ? AND entity_id IN (${slice.map(() => "?").join(",")})`;
    const res = await env.DB.prepare(q).bind(entityType, locale, ...slice).all();
    for (const t of res.results) {
      if (requireReviewed && t.status !== "reviewed") continue;
      if (t.status === "draft") continue;
      if (!found.has(t.entity_id)) found.set(t.entity_id, {});
      found.get(t.entity_id)[t.field] = t;
    }
  }
  for (const r of list) {
    if (!r) continue;
    const tr = found.get(r.id) || {};
    let any = false;
    let machine = false;
    for (const f of fields) {
      if (tr[f] && (await currentFor(tr[f], r[f], f))) {
        r[f] = tr[f].value;
        any = true;
        if (tr[f].status === "machine") machine = true;
      }
    }
    r._tr = { status: any ? (machine ? "machine" : "reviewed") : "missing", fallback: !any };
  }
  return rows;
}

const jsonIds = (o) => (Array.isArray(o) ? o.flatMap(jsonIds) : o && typeof o === "object" ? Object.entries(o).flatMap(([k, v]) => (k === "id" ? [String(v)] : jsonIds(v))) : []);

/** Whether a stored translation still matches the current source value. */
async function currentFor(t, source, field) {
  if (source === undefined) return false;
  if (t.source_hash && t.source_hash !== (await sha256Hex(String(source ?? "")))) return false;
  if (field.endsWith("_json")) {
    const a = parseJson(source, null);
    const b = parseJson(t.value, null);
    if (!b || JSON.stringify(jsonIds(a).sort()) !== JSON.stringify(jsonIds(b).sort())) return false;
  }
  return true;
}

export const COURSE_FIELDS = ["title", "subtitle", "description", "objectives_json", "prerequisites_text"];

export function hydrateCourse(c) {
  if (!c) return c;
  c.objectives = parseJson(c.objectives_json, []);
  c.audience = parseJson(c.audience_json, []);
  c.topics = parseJson(c.topics_json, []);
  c.isAvailable = c.status === "published";
  c.isUpcoming = c.status === "scheduled" || c.status === "review";
  return c;
}

export async function listCourses(env, locale, { q = "", topic = "", level = "", program = "", language = "", maxMinutes = 0, includeUpcoming = true, ids = null, limit = 200 } = {}) {
  const where = [];
  const binds = [];
  if (ids) {
    if (!ids.length) return [];
    where.push(`c.id IN (${ids.map(() => "?").join(",")})`);
    binds.push(...ids);
  } else {
    where.push(`c.status IN (${(includeUpcoming ? VISIBLE_STATUSES : ["published"]).map(() => "?").join(",")})`);
    binds.push(...(includeUpcoming ? VISIBLE_STATUSES : ["published"]));
  }
  if (level) {
    where.push("c.level = ?");
    binds.push(level);
  }
  if (program) {
    where.push("p.slug = ?");
    binds.push(program);
  }
  if (topic) {
    where.push("c.topics_json LIKE ?");
    binds.push(`%"${topic.replace(/["%_]/g, "")}"%`);
  }
  if (maxMinutes) {
    where.push("c.duration_minutes <= ?");
    binds.push(maxMinutes);
  }
  if (language && language !== "en") {
    where.push("(c.source_locale = ? OR EXISTS (SELECT 1 FROM content_translations t WHERE t.entity_type='course' AND t.entity_id=c.id AND t.locale=? AND t.field='title' AND t.status IN ('machine','reviewed')))");
    binds.push(language, language);
  }
  if (q) {
    const like = `%${q.replace(/[%_]/g, "").slice(0, 80)}%`;
    where.push(
      "(c.title LIKE ? OR c.subtitle LIKE ? OR c.description LIKE ? OR c.topics_json LIKE ? OR EXISTS (SELECT 1 FROM content_translations t WHERE t.entity_type='course' AND t.entity_id=c.id AND t.value LIKE ?))",
    );
    binds.push(like, like, like, like, like);
  }
  const sql = `SELECT c.*, p.title AS program_title, p.slug AS program_slug, p.code AS program_code,
      (SELECT COUNT(*) FROM lessons l WHERE l.course_id = c.id AND l.status='ready') AS lesson_count
    FROM courses c LEFT JOIN programs p ON p.id = c.program_id
    WHERE ${where.join(" AND ")}
    ORDER BY CASE c.status WHEN 'published' THEN 0 ELSE 1 END, COALESCE(p.sort_order, 99), c.sort_order, c.title
    LIMIT ?`;
  const rows = (await env.DB.prepare(sql).bind(...binds, limit).all()).results;
  await localize(env, "course", rows, COURSE_FIELDS, locale);
  return rows.map(hydrateCourse);
}

/**
 * A course by slug. Drafts are staff-only. Archived courses are taken down:
 * only staff and learners already enrolled (who keep their classroom and
 * records) can open them; everyone else, search engines included, gets 404.
 */
export async function getCourseBySlug(env, slug, locale, { staff = false, userId = null } = {}) {
  const c = await env.DB.prepare(
    `SELECT c.*, p.title AS program_title, p.slug AS program_slug, p.code AS program_code
       FROM courses c LEFT JOIN programs p ON p.id = c.program_id WHERE c.slug = ?`,
  )
    .bind(slug)
    .first();
  if (!c) throw new HttpError(404, "not_found");
  if (!staff && c.status === "draft") throw new HttpError(404, "not_found");
  if (!staff && c.status === "archived") {
    const enrolled = userId && (await env.DB.prepare("SELECT 1 FROM enrollments WHERE user_id = ? AND course_id = ? AND status != 'withdrawn'").bind(userId, c.id).first());
    if (!enrolled) throw new HttpError(404, "not_found");
  }
  await localize(env, "course", c, COURSE_FIELDS, locale);
  return hydrateCourse(c);
}

export async function getCourseById(env, id) {
  return hydrateCourse(await env.DB.prepare("SELECT * FROM courses WHERE id = ?").bind(id).first());
}

/** Modules with their lessons, in order, localized. */
export async function getSyllabus(env, courseId, locale, { includeDrafts = false } = {}) {
  // Retired modules and lessons removed by a later revision (slug '__rev_…') stay
  // in the database for progress history but are never shown.
  const modules = (await env.DB.prepare("SELECT * FROM modules WHERE course_id = ? AND status = 'active' ORDER BY sort_order, created_at").bind(courseId).all()).results;
  const lessons = (
    await env.DB.prepare(
      `SELECT l.id, l.course_id, l.module_id, l.slug, l.title, l.type, l.summary, l.est_minutes, l.video_id, l.assessment_id,
              l.is_required, l.is_preview, l.sort_order, l.status, v.status AS video_status
         FROM lessons l LEFT JOIN video_assets v ON v.id = l.video_id
        WHERE l.course_id = ? ${includeDrafts ? "AND l.slug NOT LIKE '\\_\\_rev\\_%' ESCAPE '\\'" : "AND l.status = 'ready'"}
        ORDER BY l.sort_order, l.created_at`,
    )
      .bind(courseId)
      .all()
  ).results;
  await localize(env, "module", modules, ["title", "summary"], locale);
  await localize(env, "lesson", lessons, ["title", "summary"], locale);
  for (const m of modules) m.lessons = lessons.filter((l) => l.module_id === m.id);
  const flat = modules.flatMap((m) => m.lessons);
  return { modules: modules.filter((m) => m.lessons.length || includeDrafts), lessons: flat };
}

export async function getInstructorsForCourse(env, courseId) {
  return (
    await env.DB.prepare(
      `SELECT i.* FROM instructors i JOIN course_instructors ci ON ci.instructor_id = i.id
        WHERE ci.course_id = ? AND i.status = 'active' ORDER BY ci.sort_order`,
    )
      .bind(courseId)
      .all()
  ).results;
}

export async function getPrerequisites(env, courseId, locale) {
  const rows = (
    await env.DB.prepare(
      `SELECT c.id, c.slug, c.title, c.status, cp.is_required FROM course_prerequisites cp
         JOIN courses c ON c.id = cp.prerequisite_course_id WHERE cp.course_id = ?`,
    )
      .bind(courseId)
      .all()
  ).results;
  await localize(env, "course", rows, ["title"], locale);
  return rows;
}

export async function listPrograms(env, locale) {
  const rows = (
    await env.DB.prepare(
      `SELECT p.*,
         (SELECT COUNT(*) FROM courses c WHERE c.program_id = p.id AND c.status IN ('published','scheduled','review')) AS course_count,
         (SELECT COUNT(*) FROM courses c WHERE c.program_id = p.id AND c.status = 'published') AS available_count
       FROM programs p WHERE p.status = 'published' ORDER BY p.sort_order`,
    ).all()
  ).results;
  await localize(env, "program", rows, ["title", "summary", "description"], locale);
  return rows;
}

export async function listPaths(env, locale) {
  const paths = (await env.DB.prepare("SELECT * FROM learning_paths WHERE status = 'published' ORDER BY sort_order").all()).results;
  await localize(env, "learning_path", paths, ["title", "summary"], locale);
  const links = (await env.DB.prepare("SELECT path_id, course_id, sort_order FROM learning_path_courses ORDER BY sort_order").all()).results;
  for (const p of paths) p.course_ids = links.filter((l) => l.path_id === p.id).map((l) => l.course_id);
  return paths;
}

export async function getLesson(env, courseId, lessonSlug, locale) {
  const l = await env.DB.prepare("SELECT * FROM lessons WHERE course_id = ? AND slug = ?").bind(courseId, lessonSlug).first();
  if (!l) throw new HttpError(404, "not_found");
  await localize(env, "lesson", l, ["title", "summary", "body_md"], locale);
  return l;
}

export async function getVideo(env, videoId, locale) {
  if (!videoId) return null;
  const v = await env.DB.prepare("SELECT * FROM video_assets WHERE id = ?").bind(videoId).first();
  if (!v) return null;
  v.captions = (await env.DB.prepare("SELECT id, locale, label, status FROM video_captions WHERE video_id = ? ORDER BY locale = ? DESC, locale").bind(videoId, locale).all()).results;
  v.playable = v.status === "approved" && Boolean(v.hls_url || v.mp4_url);
  return v;
}
