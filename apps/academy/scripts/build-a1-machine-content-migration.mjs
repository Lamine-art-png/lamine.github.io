#!/usr/bin/env node
// Deterministic D1 migration for PUBLIC A1 lessons, never exams/captions/users.
// All inserts machine/unreviewed, source-text guarded, never overwrite approved edits.
// This script only writes an SQL file; protected deploy.sh handles D1 writes.
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root=resolve(dirname(fileURLToPath(import.meta.url)),"../../..");
const packsDir=resolve(root,"apps/academy/localization-drafts/a1");
const output=process.argv[2] ? resolve(process.argv[2]) : resolve(root,"apps/academy/migrations/0014_a1_machine_content.sql");
const fields={
 course:{table:"courses",keys:["title","subtitle","description","prerequisites_text","objectives_json"]},
 module:{table:"modules",keys:["title","summary"]},
 lesson:{table:"lessons",keys:["title","summary","body_md"]},
};
const codes=JSON.parse(readFileSync(resolve(root,"shared/supported-locales.json"),"utf8")).enabledUiLocales.filter(x=>x!=="en"&&x!=="auto").sort();
const files=readdirSync(packsDir).filter(x=>x.endsWith(".json")).map(x=>x.slice(0,-5)).sort();
function check(ok,reason){if(!ok)throw new Error(reason);}
check(codes.length===59&&JSON.stringify(codes)===JSON.stringify(files),"Missing or extra locale packs");
const quote=(v)=>"'"+String(v).replaceAll("'","''")+"'";
const hash=(v)=>createHash("sha256").update(String(v),"utf8").digest("hex");
const statements=[
 "-- A1 public lesson machine translations; intentionally not reviewed.",
 "-- Gated by exact source English text; NEVER overwrites any existing translation.",
 "-- NO exam content, captions, course status, learner progress or certificates are touched.",
];
let n=0,omitted=0;
for(const lang of codes){
 const pack=JSON.parse(readFileSync(resolve(packsDir,lang+".json"),"utf8"));
 check(pack.format==="agroai-academy-translations/v1"&&pack.status==="machine"&&pack.target_locale===lang,lang+": invalid source format");
 check(pack.total_fields===64&&pack.items.length===64,lang+": incomplete pack");
 check(pack.items.filter(it=>it.status==="source_fallback").length===pack.untranslated.length,lang+": fallback provenance mismatch");
 const unique=new Set();
 for(const item of pack.items){
   const spec=fields[item.type];
   check(spec&&spec.keys.includes(item.field),lang+": forbidden field");
   check(item.status==="machine"||item.status==="source_fallback",lang+": inappropriate review status");
   check(typeof item.source==="string"&&item.source.trim()&&typeof item.translation==="string"&&item.translation.trim(),lang+": invalid text");
   check(item.type==="course"?item.id==="crs_a1":String(item.id).startsWith(item.type==="module"?"mod_a1_":"les_a1_"),lang+": unexpected non-A1 source ID");
   const key=item.type+":"+item.id+":"+item.field;
   check(!unique.has(key),lang+": duplicate field");unique.add(key);
   if(item.translation===item.source){omitted++;continue;}
   if(item.field==="objectives_json"){
     const src=JSON.parse(item.source),tr=JSON.parse(item.translation);
     check(Array.isArray(src)&&Array.isArray(tr)&&src.length===tr.length&&src.every(x=>typeof x==="string")&&tr.every(x=>typeof x==="string"),lang+": unsafe objectives shape");
   }
   const a=[item.type,item.id,item.field,lang,item.translation].map(quote);
   const statement="INSERT OR IGNORE INTO content_translations (entity_type,entity_id,field,locale,value,status,source_hash,updated_by,updated_at) "+
      "SELECT "+a.join(",")+",'machine',"+quote(hash(item.source))+",NULL,strftime('%Y-%m-%dT%H:%M:%fZ','now') FROM "+spec.table+
      " WHERE id="+quote(item.id)+" AND "+item.field+"="+quote(item.source)+";";
   statements.push(statement);n++;
 }
}
check(n>=3700&&omitted<=100,"Unacceptable translation coverage");
statements.push("-- machine field candidates "+n+", source fallbacks "+omitted+", 59 locales.");
mkdirSync(dirname(output),{recursive:true});
writeFileSync(output,statements.join("\n")+"\n","utf8");
console.log("Generated A1 machine draft D1 migration:",n,"guarded field inserts;",omitted,"English fallbacks");
