#!/usr/bin/env node
// Repair only the A1 course description for installations whose approved
// English description uses CRLF paragraph breaks. Public production HTML on
// 2026-10-28 showed CRLF; staging has LF. Never normalize arbitrary edits.
// This generates an insert-only, exact-source-guarded D1 migration.
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { A1 } from "../src/content/courses/a1.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const packsDir = resolve(root, "apps/academy/localization-drafts/a1");
const output = process.argv[2]
  ? resolve(process.argv[2])
  : resolve(root, "apps/academy/migrations/0015_a1_machine_description_crlf.sql");
const locales = JSON.parse(readFileSync(resolve(root, "shared/supported-locales.json"), "utf8"))
  .enabledUiLocales.filter((x) => x !== "en" && x !== "auto").sort();
const files = readdirSync(packsDir).filter((x) => x.endsWith(".json"))
  .map((x) => x.slice(0, -5)).sort();
const check = (ok, reason) => { if (!ok) throw new Error(reason); };
const quote = (s) => "'" + String(s).replaceAll("'", "''") + "'";
const hash = (s) => createHash("sha256").update(s, "utf8").digest("hex");

check(locales.length === 59 && JSON.stringify(locales) === JSON.stringify(files),
  "Expected exactly 59 matching A1 locale packs");
const canonical = A1.description;
check(typeof canonical === "string" && canonical.includes("\n\n") && !canonical.includes("\r"),
  "Canonical A1 English description must use LF paragraph breaks");
const crlf = canonical.replaceAll("\n", "\r\n");
check(crlf !== canonical, "CRLF variant must differ from canonical source");
const statements = [
  "-- Repair A1 course description only when stored English source EXACTLY matches the CRLF variant.",
  "-- Machine/unreviewed inserts only; never update or replace a reviewed translation.",
  "-- No course source edits, exams, captions, learners, certificates or video changes.",
];
for (const locale of locales) {
  const pack = JSON.parse(readFileSync(resolve(packsDir, locale + ".json"), "utf8"));
  check(pack.format === "agroai-academy-translations/v1" &&
    pack.status === "machine_draft_requires_review" && pack.target_locale === locale,
    locale + ": invalid machine-draft provenance");
  const matches = pack.items.filter((x) => x.type === "course" &&
    x.id === "crs_a1" && x.field === "description");
  check(matches.length === 1, locale + ": missing/duplicate description");
  const item = matches[0];
  check(item.status === "machine" && item.source === canonical &&
    typeof item.translation === "string" && item.translation.trim() &&
    item.translation !== canonical, locale + ": description not safely translated from canonical source");
  statements.push(
    "INSERT OR IGNORE INTO content_translations " +
    "(entity_type,entity_id,field,locale,value,status,source_hash,updated_by,updated_at) " +
    "SELECT 'course','crs_a1','description'," + quote(locale) + "," +
    quote(item.translation) + ",'machine'," + quote(hash(crlf)) +
    ",NULL,strftime('%Y-%m-%dT%H:%M:%fZ','now') FROM courses " +
    "WHERE id='crs_a1' AND description=" + quote(crlf) + ";"
  );
}
check(statements.length === 62, "Expected 59 source-guarded inserts");
statements.push("-- 59 CRLF-specific candidates. On LF or modified source: zero inserts.");
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, statements.join("\n") + "\n", "utf8");
console.log("Generated A1 CRLF description repair: 59 exact-source-guarded machine inserts");
