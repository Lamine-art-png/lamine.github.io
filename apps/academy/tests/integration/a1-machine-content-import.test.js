import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { makeEnv } from "../helpers.js";

const root=join(dirname(fileURLToPath(import.meta.url)),"../..");
test("59 public A1 machine locale packs import safely without overwriting human reviews or changed English source", async () => {
 const tmp=mkdtempSync(join(tmpdir(),"academy-a1-i18n-"));
 try{
  const output=join(tmp,"a1.sql");
  execFileSync("node",[join(root,"scripts/build-a1-machine-content-migration.mjs"),output],{encoding:"utf8"});
  const migration=readFileSync(output,"utf8");
  assert.match(migration,/source fallbacks/);
  assert.doesNotMatch(migration,/INSERT OR IGNORE INTO (certificates|attempts|questions|users)/);
  const env=makeEnv();
  const current=await env.DB.prepare("SELECT title FROM courses WHERE id = 'crs_a1'").first();
  await env.DB.prepare("UPDATE courses SET title='Updated by founder after language draft' WHERE id='crs_a1'").run();
  await env.DB.prepare("INSERT INTO content_translations (entity_type,entity_id,field,locale,value,status,updated_at) VALUES ('lesson','les_a1_welcome','title','fr-FR','Human approved title','reviewed','2026-10-28')").run();
  const before=await env.DB.prepare("SELECT COUNT(*) AS n FROM enrollments").first();
  await env.DB.exec(migration);
  const imported=await env.DB.prepare("SELECT COUNT(*) AS n FROM content_translations WHERE status='machine'").first();
  assert.ok(imported.n>=3500&&imported.n<=3750,"missing or excessive A1 machine drafts");
  const approved=await env.DB.prepare("SELECT value,status FROM content_translations WHERE entity_type='lesson' AND entity_id='les_a1_welcome' AND field='title' AND locale='fr-FR'").first();
  assert.deepEqual(approved,{value:"Human approved title",status:"reviewed"});
  const changed=await env.DB.prepare("SELECT COUNT(*) AS n FROM content_translations WHERE entity_type='course' AND entity_id='crs_a1' AND field='title'").first();
  assert.equal(changed.n,0,"stale machine drafts should not override changed English source");
  const enrollments=await env.DB.prepare("SELECT COUNT(*) AS n FROM enrollments").first();
  assert.equal(enrollments.n,before.n);
  await env.DB.exec(migration);
  const twice=await env.DB.prepare("SELECT COUNT(*) AS n FROM content_translations WHERE status='machine'").first();
  assert.equal(twice.n,imported.n,"re-applying machine drafts is idempotent");
  const hash=await env.DB.prepare("SELECT source_hash FROM content_translations WHERE status='machine' LIMIT 1").first();
  assert.match(hash.source_hash,/^[0-9a-f]{64}$/);
  assert.ok(current.title.length>5);
 }finally{rmSync(tmp,{recursive:true,force:true});}
});
