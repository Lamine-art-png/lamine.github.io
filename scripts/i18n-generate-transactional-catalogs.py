#!/usr/bin/env python3
from __future__ import annotations

import ast

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
MAX_KEYS = 8
MAX_CHARS = 900
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_MODELS = (
    os.environ.get("I18N_CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct-fast").strip(),
    os.environ.get("I18N_CLOUDFLARE_FALLBACK_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8").strip(),
)

def stable_fingerprint(catalog: dict[str, str]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def clean_json(raw: str) -> dict:
    value = raw.strip()
    value = re.sub(r"^\`\`\`(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*\`\`\`$", "", value).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        value = value[start:end + 1]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(value)
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

def cloudflare_rest_available() -> bool:
    return bool(CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID)


def call_cloudflare_rest(locale: str, source: dict[str,str]) -> dict[str,str]:
    system=(
        f"Translate every JSON string value into the requested locale ({locale}) for professional AGRO-AI account-verification email. "
        "Return exactly one JSON object with identical keys. Preserve {product} exactly. Preserve AGRO-AI, API, TEST, LIVE, URLs and numeric values. "
        "For pt-BR use natural Brazilian Portuguese. Do not add or remove legal/security claims. No markdown or explanation."
    )
    messages=[
        {"role":"system","content":system},
        {"role":"user","content":json.dumps(source,ensure_ascii=False,separators=(",",":"))},
    ]
    failures=[]
    for model in CLOUDFLARE_MODELS:
        if not model:
            continue
        url=f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"
        body={"messages":messages,"temperature":0,"max_tokens":1200}
        try:
            req=urllib.request.Request(
                url,
                data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
                headers={
                    "authorization":f"Bearer {CLOUDFLARE_API_TOKEN}",
                    "content-type":"application/json",
                    "accept":"application/json",
                    "user-agent":"AGRO-AI-Localization-Release/2.0",
                },
            )
            with urllib.request.urlopen(req,timeout=70) as response:
                payload=json.load(response)
            if payload.get("success") is not True:
                raise RuntimeError(f"cloudflare_rest_unsuccessful:{payload.get('errors')}")
            result=payload.get("result") or {}
            raw=result.get("response") or result.get("result",{}).get("response") or result.get("choices",[{}])[0].get("message",{}).get("content") or ""
            if not isinstance(raw,str) or not raw.strip():
                raise RuntimeError("cloudflare_rest_empty_response")
            parsed=clean_json(raw)
            out={}
            for key, original in source.items():
                value=parsed.get(key)
                if not isinstance(value,str) or not value.strip() or value.strip().lower()=="[object object]":
                    raise ValueError(f"invalid_value:{key}")
                value=value.strip()
                if sorted(TOKENS.findall(original)) != sorted(TOKENS.findall(value)):
                    raise ValueError(f"placeholder_mismatch:{key}")
                out[key]=value
            if set(out) != set(source):
                raise ValueError("transactional_key_mismatch")
            return out
        except Exception as exc:
            failures.append(f"{model}:{type(exc).__name__}:{str(exc)[:240]}")
    raise RuntimeError("cloudflare_rest_models_failed:"+"|".join(failures))


def call_translate(locale: str, source: dict[str,str]) -> dict[str,str]:
    system=(
        f"Translate every JSON string value into the requested locale ({locale}) for professional AGRO-AI account-verification email. "
        "Return exactly one JSON object with identical keys. Preserve {product} exactly. Preserve AGRO-AI, API, TEST, LIVE, URLs and numeric values. "
        "For pt-BR use natural Brazilian Portuguese. Do not add or remove legal/security claims. No markdown or explanation."
    )
    body={
        "model":"transactional-localization-authoring",
        "messages":[{"role":"system","content":system},{"role":"user","content":"QUESTION: "+json.dumps(source,ensure_ascii=False,separators=(",",":"))}],
        "stream":False,
        "options":{"temperature":0,"num_predict":1200},
    }
    last=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        try:
            if cloudflare_rest_available():
                try:
                    return call_cloudflare_rest(locale, source)
                except Exception as rest_exc:
                    # Deploy-capable Cloudflare credentials may not include
                    # Workers AI REST permission. Fall through to AGRO-AI's
                    # deployed edge authoring runtime instead of failing every
                    # transactional locale on a REST 401.
                    last=rest_exc
            req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode("utf-8"),headers={"content-type":"application/json","accept":"application/json","user-agent":"Mozilla/5.0 AGRO-AI-Localization-Release/1.0"})
            with urllib.request.urlopen(req,timeout=55) as response:
                payload=json.load(response)
            raw=payload.get("message",{}).get("content") or payload.get("response") or ""
            if payload.get("done") is not True or not isinstance(raw,str) or not raw.strip():
                raise ValueError("invalid_provider_response")
            parsed=clean_json(raw)
            if set(parsed) != set(source):
                raise ValueError("transactional_key_mismatch")
            out={}
            for key, original in source.items():
                value=parsed.get(key)
                if not isinstance(value,str) or not value.strip() or value.strip().lower()=="[object object]":
                    raise ValueError(f"invalid_value:{key}")
                value=value.strip()
                if sorted(TOKENS.findall(original)) != sorted(TOKENS.findall(value)):
                    raise ValueError(f"placeholder_mismatch:{key}")
                out[key]=value
            return out
        except Exception as exc:
            last=exc
            if attempt<MAX_ATTEMPTS:
                time.sleep(attempt*1.2)
    raise RuntimeError(f"transactional_chunk_failed:{locale}:{type(last).__name__ if last else 'unknown'}:{str(last)[:300] if last else ''}")


def split_source(source: dict[str,str]) -> list[dict[str,str]]:
    groups=[]
    current={}
    chars=0
    for key,value in source.items():
        cost=len(key)+len(value)+12
        if current and (len(current)>=MAX_KEYS or chars+cost>MAX_CHARS):
            groups.append(current); current={}; chars=0
        current[key]=value; chars+=cost
    if current: groups.append(current)
    return groups


def translate_resilient(locale: str, source: dict[str,str]) -> dict[str,str]:
    try:
        return call_translate(locale,source)
    except RuntimeError:
        if len(source)<=1:
            raise
        items=list(source.items())
        mid=max(1,len(items)//2)
        out={}
        out.update(translate_resilient(locale,dict(items[:mid])))
        out.update(translate_resilient(locale,dict(items[mid:])))
        return out


def translate(locale: str, source: dict[str,str]) -> dict[str,str]:
    out={}
    for chunk in split_source(source):
        out.update(translate_resilient(locale,chunk))
    return validate(source,out)

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
    for locale in locales:
        try:
            one(locale)
            print(f"PASS {locale}",flush=True)
        except Exception as exc:
            failures.append((locale,str(exc)))
            print(f"FAIL {locale}: {exc}",flush=True)
    if failures:
        raise SystemExit(json.dumps({"status":"failure","failures":failures},ensure_ascii=False))
    print(json.dumps({"status":"ok","locales":len(locales),"sourceFingerprint":fingerprint}))

if __name__=="__main__":
    main()
