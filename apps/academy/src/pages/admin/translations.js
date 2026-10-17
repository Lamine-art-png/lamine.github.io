// Admin: translation workflow. UI copy comes from bundled catalogs with
// database overrides; course content translations are stored per field with a
// review status (machine → draft → reviewed). Certification exams only use
// reviewed translations. Export/import supports external translators.
import { html, raw } from "../../lib/html.js";
import { redirect, HttpError, json } from "../../lib/http.js";
import { nowIso, sha256Hex, parseJson } from "../../lib/util.js";
import { audit } from "../../lib/security.js";
import { LOCALES, catalogCoverage, clearOverrideCache, localeInfo } from "../../lib/i18n.js";
import { CATALOGS } from "../../i18n/index.js";
import { adminPage, table, statusBadge, hidden, select, textarea, str } from "./shell.js";

const ENTITY_FIELDS = {
  course: { table: "courses", fields: ["title", "subtitle", "description", "objectives_json", "prerequisites_text"], label: "title" },
  module: { table: "modules", fields: ["title", "summary"], label: "title" },
  lesson: { table: "lessons", fields: ["title", "summary", "body_md"], label: "title" },
  question: { table: "questions", fields: ["prompt", "data_json", "explanation"], label: "prompt" },
  question_case: { table: "question_cases", fields: ["title", "body_md"], label: "title" },
  assessment: { table: "assessments", fields: ["title", "instructions"], label: "title" },
  program: { table: "programs", fields: ["title", "summary", "description"], label: "title" },
  learning_path: { table: "learning_paths", fields: ["title", "summary"], label: "title" },
};

export async function overview(c) {
  const coverage = catalogCoverage();
  const content = (await c.env.DB.prepare("SELECT locale, status, COUNT(*) AS n FROM content_translations GROUP BY locale, status").all()).results;
  const overrides = (await c.env.DB.prepare("SELECT locale, COUNT(*) AS n FROM ui_translations GROUP BY locale").all()).results;
  const byLocale = (code, status) => content.find((r) => r.locale === code && r.status === status)?.n || 0;
  const body = html`<div class="alert alert-info"><div>The language inventory is derived from the Enterprise Portal manifest (<code>shared/supported-locales.json</code>): <strong>${LOCALES.length} languages</strong>.
    Interface catalogs are machine-prepared and unreviewed unless marked otherwise. Certification exams display only translations marked <em>reviewed</em>; otherwise learners see the English source with a notice.</div></div>
  <div class="row mb-2"><a class="btn btn-sm btn-secondary" href="/admin/translations/content">Course content translations</a></div>
  ${table(
    ["Language", "Code", "Direction", "UI catalog", "Provenance", "UI overrides", "Content: machine", "Content: reviewed", ""],
    coverage.map(
      (l) => html`<tr><td>${l.englishName} <span class="muted">· ${l.nativeName}</span></td><td><code>${l.code}</code></td><td>${l.dir}</td>
        <td>${l.translated}/${l.total} (${l.pct}%)</td><td>${statusBadge(l.provenance === "source" ? "reviewed" : l.provenance === "missing" ? "draft" : "machine")} <span class="tiny">${l.provenance}</span></td>
        <td>${overrides.find((o) => o.locale === l.code)?.n || 0}</td><td>${byLocale(l.code, "machine")}</td><td>${byLocale(l.code, "reviewed")}</td>
        <td><a href="/admin/translations/ui?locale=${l.code}">Edit UI</a> · <a href="/admin/translations/content?locale=${l.code}">Content</a></td></tr>`,
    ),
  )}`;
  return adminPage(c, { title: "Translations", active: "/admin/translations", body });
}

export async function uiEditor(c) {
  const locale = LOCALES.find((l) => l.code === c.url.searchParams.get("locale"))?.code || "en";
  const q = str(c.url.searchParams.get("q"), 80).toLowerCase();
  const missingOnly = c.url.searchParams.get("missing") === "1";
  const en = CATALOGS.en;
  const cat = CATALOGS[locale] || {};
  const ov = new Map((await c.env.DB.prepare("SELECT key, value, status FROM ui_translations WHERE locale = ?").bind(locale).all()).results.map((r) => [r.key, r]));
  let keys = Object.keys(en);
  if (q) keys = keys.filter((k) => k.toLowerCase().includes(q) || en[k].toLowerCase().includes(q) || (cat[k] || "").toLowerCase().includes(q));
  if (missingOnly) keys = keys.filter((k) => !(k in cat) && !ov.has(k));
  const shown = keys.slice(0, 80);
  const info = localeInfo(locale);
  const body = html`<form method="get" class="row mb-2">
      ${select("locale", "Language", LOCALES.map((l) => [l.code, `${l.englishName} (${l.code})`]), locale)}
      <div class="field grow"><label for="tq">Search keys or text</label><input id="tq" name="q" value="${q}"></div>
      <label class="check"><input type="checkbox" name="missing" value="1" ${missingOnly ? raw("checked") : ""}> Missing only</label>
      <button class="btn btn-secondary btn-sm">Filter</button></form>
    <p class="small muted">${keys.length} matching keys${keys.length > shown.length ? `, showing the first ${shown.length}` : ""}. Saving creates a reviewed override that takes effect within a minute, without a deployment.</p>
    ${shown.map((k) => {
      const o = ov.get(k);
      return html`<form class="panel mt-1" method="post" action="/admin/translations/ui">${hidden(c)}<input type="hidden" name="locale" value="${locale}"><input type="hidden" name="key" value="${k}">
        <div class="row-between"><code class="tiny">${k}</code>${o ? statusBadge(o.status) : k in cat ? statusBadge("machine") : statusBadge("draft")}</div>
        <p class="small muted mb-1" lang="en">${en[k]}</p>
        <label class="sr-only" for="v-${k}">Translation</label>
        <textarea id="v-${k}" name="value" rows="2" dir="${info.dir}" lang="${locale}">${o?.value ?? cat[k] ?? ""}</textarea>
        <div class="row mt-1"><select name="status" aria-label="Status"><option value="reviewed">reviewed</option><option value="machine" ${o?.status === "machine" ? raw("selected") : ""}>machine</option></select>
          <button class="btn btn-sm btn-secondary">Save</button>${o ? html`<button class="btn btn-sm btn-quiet" name="clear" value="1">Revert to catalog</button>` : ""}</div></form>`;
    })}`;
  return adminPage(c, { title: `Interface strings — ${info.englishName}`, active: "/admin/translations", body });
}

export async function uiSave(c) {
  const b = await c.readBody();
  const locale = LOCALES.find((l) => l.code === b.locale)?.code;
  const key = String(b.key || "");
  if (!locale || !(key in CATALOGS.en)) throw new HttpError(400, "invalid_key");
  if (b.clear === "1") await c.env.DB.prepare("DELETE FROM ui_translations WHERE locale = ? AND key = ?").bind(locale, key).run();
  else {
    const value = String(b.value ?? "").slice(0, 4000);
    // Placeholders such as {name} must survive translation.
    const need = (CATALOGS.en[key].match(/\{\w+\}/g) || []).sort().join();
    const got = (value.match(/\{\w+\}/g) || []).sort().join();
    if (need !== got) return redirect(`/admin/translations/ui?locale=${locale}&q=${encodeURIComponent(key)}&err=${encodeURIComponent(`Keep the placeholders ${need || "(none)"} unchanged.`)}`);
    await c.env.DB.prepare(
      `INSERT INTO ui_translations (locale, key, value, status, updated_by, updated_at) VALUES (?,?,?,?,?,?)
       ON CONFLICT(locale, key) DO UPDATE SET value = excluded.value, status = excluded.status, updated_by = excluded.updated_by, updated_at = excluded.updated_at`,
    )
      .bind(locale, key, value, b.status === "machine" ? "machine" : "reviewed", c.user.id, nowIso())
      .run();
  }
  clearOverrideCache();
  await audit(c, "translation.ui_save", "ui_translation", `${locale}:${key}`);
  return redirect(`/admin/translations/ui?locale=${locale}&q=${encodeURIComponent(key)}&ok=saved`);
}

export async function contentEditor(c) {
  const locale = LOCALES.find((l) => l.code === c.url.searchParams.get("locale") && l.code !== "en")?.code || "pt-BR";
  const type = ENTITY_FIELDS[c.url.searchParams.get("type")] ? c.url.searchParams.get("type") : "course";
  const spec = ENTITY_FIELDS[type];
  const id = c.url.searchParams.get("id");
  const info = localeInfo(locale);
  const nav = html`<form method="get" class="row mb-2">
    ${select("locale", "Target language", LOCALES.filter((l) => l.code !== "en").map((l) => [l.code, `${l.englishName} (${l.code})`]), locale)}
    ${select("type", "Content type", Object.keys(ENTITY_FIELDS).map((k) => [k, k.replace("_", " ")]), type)}
    <button class="btn btn-secondary btn-sm">Show</button>
    <a class="btn btn-quiet btn-sm" href="/admin/translations/export?locale=${locale}">Export ${locale} (JSON)</a></form>`;

  if (!id) {
    const rows = (
      await c.env.DB.prepare(
        `SELECT e.id, e.${spec.label} AS label,
           (SELECT GROUP_CONCAT(t.field || ':' || t.status) FROM content_translations t WHERE t.entity_type = ? AND t.entity_id = e.id AND t.locale = ?) AS done
           FROM ${spec.table} e ORDER BY e.rowid DESC LIMIT 300`,
      )
        .bind(type, locale)
        .all()
    ).results;
    const body = html`${nav}${table(
      ["Item", "Translated fields", ""],
      rows.map((r) => html`<tr><td class="wrap-cell">${String(r.label).slice(0, 120)}</td><td class="tiny">${r.done || "—"}</td><td><a href="/admin/translations/content?locale=${locale}&type=${type}&id=${r.id}">Translate</a></td></tr>`),
    )}
    <section class="form-card mt-3"><h2 class="h2">Import translations (JSON)</h2>
      <p class="small muted">Paste a file produced by Export after translation. Imported values are stored with the status you choose; mark them reviewed only after a qualified reviewer has checked them.</p>
      <form method="post" action="/admin/translations/import">${hidden(c)}${textarea("payload", "JSON", "", { rows: 8, cls: "code", required: true })}
        ${select("status", "Import as", [["machine", "machine (unreviewed draft)"], ["draft", "draft (hidden from learners)"], ["reviewed", "reviewed"]], "machine")}
        <button class="btn btn-secondary">Import</button></form></section>`;
    return adminPage(c, { title: "Content translations", active: "/admin/translations", body });
  }

  const row = await c.env.DB.prepare(`SELECT * FROM ${spec.table} WHERE id = ?`).bind(id).first();
  if (!row) throw new HttpError(404, "not_found");
  const existing = new Map((await c.env.DB.prepare("SELECT field, value, status, source_hash FROM content_translations WHERE entity_type = ? AND entity_id = ? AND locale = ?").bind(type, id, locale).all()).results.map((r) => [r.field, r]));
  const fieldForms = await Promise.all(
    spec.fields.map(async (f) => {
      const src = row[f] ?? "";
      const tr = existing.get(f);
      const stale = tr && tr.source_hash && tr.source_hash !== (await sha256Hex(String(src)));
      return html`<form class="panel mt-2" method="post" action="/admin/translations/content">${hidden(c)}
        <input type="hidden" name="type" value="${type}"><input type="hidden" name="id" value="${id}"><input type="hidden" name="locale" value="${locale}"><input type="hidden" name="field" value="${f}">
        <div class="row-between"><strong>${f}</strong><span>${tr ? statusBadge(tr.status) : statusBadge("draft")} ${stale ? html`<span class="badge badge-warn">source changed since translation</span>` : ""}</span></div>
        <details class="mt-1"><summary class="small">English source</summary><pre class="small">${src}</pre></details>
        <label class="sr-only" for="ct-${f}">Translation</label>
        <textarea id="ct-${f}" name="value" rows="${f.endsWith("_md") || f === "description" ? 12 : f.endsWith("_json") ? 6 : 2}" dir="${f.endsWith("_json") ? "ltr" : info.dir}" lang="${locale}" class="${f.endsWith("_json") || f.endsWith("_md") ? "code" : ""}">${tr?.value ?? ""}</textarea>
        ${f.endsWith("_json") ? html`<p class="field-hint">Keep the JSON structure and every "id" unchanged; translate only the text values.</p>` : ""}
        <div class="row mt-1"><select name="status" aria-label="Status"><option value="machine" ${tr?.status === "machine" ? raw("selected") : ""}>machine</option><option value="draft" ${tr?.status === "draft" ? raw("selected") : ""}>draft</option><option value="reviewed" ${tr?.status === "reviewed" ? raw("selected") : ""}>reviewed</option></select>
          <button class="btn btn-sm btn-secondary">Save</button></div></form>`;
    }),
  );
  const body = html`${nav}<p><a href="/admin/translations/content?locale=${locale}&type=${type}">← All ${type.replace("_", " ")} items</a></p>${fieldForms}`;
  return adminPage(c, { title: `Translate ${type.replace("_", " ")} → ${info.englishName}`, active: "/admin/translations", body });
}

async function upsertContent(c, { type, id, locale, field, value, status }) {
  const spec = ENTITY_FIELDS[type];
  if (!spec || !spec.fields.includes(field) || !LOCALES.some((l) => l.code === locale) || locale === "en") throw new HttpError(400, "invalid_translation");
  const row = await c.env.DB.prepare(`SELECT ${field} AS v FROM ${spec.table} WHERE id = ?`).bind(id).first();
  if (!row) throw new HttpError(404, "not_found");
  if (field.endsWith("_json")) {
    const src = parseJson(row.v, null);
    const tr = parseJson(value, null);
    // Same shape and the same ids; only text may differ.
    const shape = (o) =>
      Array.isArray(o)
        ? o.map(shape)
        : o && typeof o === "object"
          ? Object.fromEntries(Object.keys(o).sort().map((k) => [k, k === "id" ? o[k] : shape(o[k])]))
          : typeof o;
    if (tr == null || JSON.stringify(shape(src)) !== JSON.stringify(shape(tr))) throw new HttpError(400, "json_structure_changed");
  }
  if (!String(value).trim()) {
    await c.env.DB.prepare("DELETE FROM content_translations WHERE entity_type = ? AND entity_id = ? AND field = ? AND locale = ?").bind(type, id, field, locale).run();
    return;
  }
  await c.env.DB.prepare(
    `INSERT INTO content_translations (entity_type, entity_id, field, locale, value, status, source_hash, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?)
     ON CONFLICT(entity_type, entity_id, field, locale) DO UPDATE SET value = excluded.value, status = excluded.status, source_hash = excluded.source_hash, updated_by = excluded.updated_by, updated_at = excluded.updated_at`,
  )
    .bind(type, id, field, locale, String(value).slice(0, 200000), ["machine", "draft", "reviewed"].includes(status) ? status : "machine", await sha256Hex(String(row.v ?? "")), c.user.id, nowIso())
    .run();
}

export async function contentSave(c) {
  const b = await c.readBody();
  try {
    await upsertContent(c, b);
  } catch (e) {
    if (e instanceof HttpError) return redirect(`/admin/translations/content?locale=${encodeURIComponent(b.locale)}&type=${encodeURIComponent(b.type)}&id=${encodeURIComponent(b.id)}&err=${encodeURIComponent(e.code)}`);
    throw e;
  }
  await audit(c, "translation.content_save", b.type, b.id, { locale: b.locale, field: b.field, status: b.status });
  return redirect(`/admin/translations/content?locale=${encodeURIComponent(b.locale)}&type=${encodeURIComponent(b.type)}&id=${encodeURIComponent(b.id)}&ok=saved`);
}

export async function exportContent(c) {
  const locale = LOCALES.find((l) => l.code === c.url.searchParams.get("locale") && l.code !== "en")?.code;
  if (!locale) throw new HttpError(400, "invalid_locale");
  const items = [];
  for (const [type, spec] of Object.entries(ENTITY_FIELDS)) {
    const rows = (await c.env.DB.prepare(`SELECT id, ${spec.fields.join(", ")} FROM ${spec.table}`).all()).results;
    const tr = (await c.env.DB.prepare("SELECT entity_id, field, value, status FROM content_translations WHERE entity_type = ? AND locale = ?").bind(type, locale).all()).results;
    for (const r of rows)
      for (const f of spec.fields) {
        if (r[f] == null || r[f] === "") continue;
        const t = tr.find((x) => x.entity_id === r.id && x.field === f);
        items.push({ type, id: r.id, field: f, source: r[f], translation: t?.value ?? "", status: t?.status ?? null });
      }
  }
  return new Response(JSON.stringify({ format: "agroai-academy-translations/v1", source_locale: "en", target_locale: locale, exported_at: nowIso(), items }, null, 2), {
    headers: { "Content-Type": "application/json; charset=utf-8", "Content-Disposition": `attachment; filename="academy-content-${locale}.json"` },
  });
}

export async function importContent(c) {
  const b = await c.readBody();
  const data = parseJson(b.payload, null);
  if (!data || data.format !== "agroai-academy-translations/v1" || !Array.isArray(data.items)) return redirect("/admin/translations/content?err=Unrecognized%20file%20format");
  let ok = 0;
  let failed = 0;
  for (const it of data.items.slice(0, 5000)) {
    if (!it.translation) continue;
    try {
      await upsertContent(c, { type: it.type, id: it.id, locale: data.target_locale, field: it.field, value: it.translation, status: b.status });
      ok++;
    } catch {
      failed++;
    }
  }
  await audit(c, "translation.import", "content_translations", data.target_locale, { imported: ok, failed, status: b.status });
  return redirect(`/admin/translations/content?locale=${encodeURIComponent(data.target_locale)}&ok=saved${failed ? `&err=${encodeURIComponent(`${failed} item(s) were rejected (unknown item or changed JSON structure).`)}` : ""}`);
}

export { json };
