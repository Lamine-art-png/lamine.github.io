#!/usr/bin/env python3
"""Author UNREVIEWED A1 public lesson translations; never exam answer keys.
Creates Academy import-ready JSON, no writes to production or users.
Source is committed curriculum; source must be rechecked against live at import.
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from i18n_public_translate import translate_catalog

MIG=ROOT/"apps/academy/migrations"
OUT=ROOT/"apps/academy/localization-drafts/a1"
LANGS=json.loads((ROOT/"shared/supported-locales.json").read_text())["enabledUiLocales"]
FIELDS={
 "course":("courses",("title","subtitle","description","prerequisites_text","objectives_json")),
 "module":("modules",("title","summary")),
 "lesson":("lessons",("title","summary","body_md")),
}
PLACEHOLDER=re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
URL=re.compile(r"https?://[^\s)]+")


def sources():
    db=sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    for path in sorted(MIG.glob("*.sql")):
        if path.name>="0014": continue
        db.executescript(path.read_text(encoding="utf-8"))
    db.row_factory=sqlite3.Row
    out=[]
    for kind,(table,fields) in FIELDS.items():
        scope="id='crs_a1'" if kind=="course" else "course_id='crs_a1'"
        rows=db.execute("SELECT id,"+",".join(fields)+" FROM "+table+" WHERE "+scope+" ORDER BY id").fetchall()
        for row in rows:
            for field in fields:
                if row[field]:
                    out.append({"type":kind,"id":row["id"],"field":field,"source":row[field]})
    db.close()
    return out


def safe(src,dst,field):
    if not dst or not dst.strip() or len(dst)>5*max(len(src),100): return False
    if sorted(PLACEHOLDER.findall(src))!=sorted(PLACEHOLDER.findall(dst)): return False
    if sorted(URL.findall(src))!=sorted(URL.findall(dst)): return False
    if field=="body_md":
        for marker in ("**",chr(96),"|"):
            if src.count(marker)!=dst.count(marker): return False
    return True


def translate(lang,src,field):
    if field.endswith("_json"):
        data=json.loads(src)
        if not isinstance(data,list) or not all(isinstance(x,str) for x in data):
            raise ValueError("objective source JSON changed")
        t=translate_catalog(lang,{str(i):x for i,x in enumerate(data)})
        return json.dumps([t[str(i)] for i in range(len(data))],ensure_ascii=False)
    chunks=re.split(r"(\n\n+)",src)
    out=[]
    for chunk in chunks:
        if not chunk or chunk.isspace() or chunk.lstrip().startswith(chr(96)*3):
            out.append(chunk)
            continue
        parts=[chunk[i:i+1300] for i in range(0,len(chunk),1300)]
        tr=translate_catalog(lang,{str(i):p for i,p in enumerate(parts)})
        out.append("".join(tr[str(i)] for i in range(len(parts))))
    return "".join(out)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--locale",required=True)
    lang=p.parse_args().locale
    if lang in ("en","auto") or lang not in LANGS: raise ValueError("unsupported locale")
    source=sources()
    items=[]
    failures=[]
    for item in source:
        error=""
        for attempt in range(3):
            try:
                target=translate(lang,item["source"],item["field"])
                if not safe(item["source"],target,item["field"]):
                    raise ValueError("markdown/placeholder or URL structure changed")
                items.append({**item,"translation":target,"status":"machine"})
                error=""
                break
            except Exception as exc:
                error=str(exc)[:120]
                if attempt<2: time.sleep(2*(attempt+1))
        if error:
            failures.append({k:item[k] for k in ("type","id","field")}|{"reason":error})
    OUT.mkdir(parents=True,exist_ok=True)
    payload={
        "format":"agroai-academy-translations/v1",
        "source_locale":"en","target_locale":lang,"status":"machine",
        "translated_fields":len(items),"total_fields":len(source),
        "limitations":"Public A1 course/module/lesson text only; NO exam questions or answer keys.",
        "provenance":"unreviewed machine, source must match production before import",
        "items":items,"untranslated":failures,
    }
    (OUT/(lang+".json")).write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"{lang}: {len(items)}/{len(source)} machine fields, {len(failures)} require review",flush=True)
    if failures:
        raise RuntimeError(f"{lang}: incomplete: {len(failures)} fields failed format QA")

if __name__=="__main__":
    main()
