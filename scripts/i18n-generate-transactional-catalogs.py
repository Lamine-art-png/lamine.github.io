#!/usr/bin/env python3
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "shared/localization/transactional-source.json"
TOKENS = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
ENDPOINT = os.environ.get("I18N_TRANSACTIONAL_AUTHORING_ENDPOINT", "http://127.0.0.1:8787/api/chat")
MAX_ATTEMPTS = 4

def stable_fingerprint(catalog: dict[str, str]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def clean_json(raw: str) -> dict:
    value = raw.strip()
    value = re.sub(r"^\`\`\`(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*\`\`\`$", "", value).strip()
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("translation_not_object")
    return parsed

def validate(source: dict[str, str], translated: dict) -> dict[str, str]:
    if set(translated) != set(source):
        raise ValueError("transactional_key_mismatch")
    out={}
    changed=0
    for key, original in source.items():
        value=translated.get(key)
        if not isinstance(value,str) or not value.strip() or value.strip().lower()=="[object object]":
            raise ValueError(f"invalid_value:{key}")
        value=value.strip()
        if sorted(TOKENS.findall(original)) != sorted(TOKENS.findall(value)):
            raise ValueError(f"placeholder_mismatch:{key}")
        value.encode("utf-8",errors="strict")
        out[key]=value
        if value != original:
            changed += 1
    if changed < max(8, len(source)//3):
        raise ValueError(f"insufficient_translation_progress:{changed}")
    return out

def translate(locale: str, source: dict[str,str]) -> dict[str,str]:
    system=(
        f"Translate every JSON string value into {locale} for professional AGRO-AI account-verification email. "
        "Return exactly one JSON object with identical keys. Preserve {product} exactly. Preserve AGRO-AI, API, TEST, LIVE, URLs and numeric values. "
        "For pt-BR use natural Brazilian Portuguese. Do not add or remove legal/security claims. No markdown or explanation."
    )
    body={
        "model":"transactional-localization-authoring",
        "messages":[{"role":"system","content":system},{"role":"user","content":"QUESTION: "+json.dumps(source,ensure_ascii=False,separators=(",",":"))}],
        "stream":False,
        "options":{"temperature":0,"num_predict":2600},
    }
    last=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        try:
            req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode("utf-8"),headers={"content-type":"application/json","accept":"application/json"})
            with urllib.request.urlopen(req,timeout=55) as response:
                payload=json.load(response)
            raw=payload.get("message",{}).get("content") or payload.get("response") or ""
            if payload.get("done") is not True or not isinstance(raw,str) or not raw.strip():
                raise ValueError("invalid_provider_response")
            return validate(source,clean_json(raw))
        except Exception as exc:
            last=exc
            if attempt<MAX_ATTEMPTS:
                time.sleep(attempt*1.2)
    raise RuntimeError(f"transactional_locale_failed:{locale}:{last}")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--locales",required=True)
    parser.add_argument("--outdir",default=str(ROOT/"shared/localization/transactional-catalogs"))
    args=parser.parse_args()
    locales=[x.strip() for x in args.locales.split(",") if x.strip()]
    envelope=json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    source=envelope["catalog"]
    fingerprint=stable_fingerprint(source)
    outdir=Path(args.outdir);outdir.mkdir(parents=True,exist_ok=True)

    def one(locale):
        catalog=dict(source) if locale=="en" else translate(locale,source)
        result={"schemaVersion":1,"locale":locale,"sourceVersion":envelope["version"],"sourceFingerprint":fingerprint,"status":"complete-generated","catalog":dict(sorted(catalog.items()))}
        target=outdir/f"{locale}.json"
        target.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
        return locale

    failures=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(one,locale):locale for locale in locales}
        for future in as_completed(futures):
            locale=futures[future]
            try:
                future.result()
                print(f"PASS {locale}",flush=True)
            except Exception as exc:
                failures.append((locale,str(exc)))
                print(f"FAIL {locale}: {exc}",flush=True)
    if failures:
        raise SystemExit(json.dumps({"status":"failure","failures":failures},ensure_ascii=False))
    print(json.dumps({"status":"ok","locales":len(locales),"sourceFingerprint":fingerprint}))

if __name__=="__main__":
    main()
