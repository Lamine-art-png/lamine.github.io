#!/usr/bin/env python3
"""Build unreviewed Academy UI catalogs for the Portal's full enabled locale list.

Authoring only: operates on bundled text, never on production users, exams,
D1, certificate records or Cloudflare Stream. Uses the same translator as
scripts/generate-academy-locales.py (the existing Portal build-time pipeline).

Never upgrades a machine catalog to reviewed; human language review is separate.
An incomplete/invalid catalog fails closed without being advertised.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from i18n_public_translate import translate_catalog

REGISTRY = ROOT / "shared/supported-locales.json"
CATALOG_DIR = ROOT / "apps/academy/src/i18n"
ENGLISH_FILE = CATALOG_DIR / "en.json"
META_FILE = CATALOG_DIR / "_meta.json"
PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
TAG = re.compile(r"</?[a-z][a-z0-9-]*(?:\s+[^<>]*?)?/?>", re.I)
UNSAFE = re.compile(r"<script\b|</script|javascript:|<<<|>>>|\[object Object\]", re.I)


def exact_placeholders(text: str) -> list[str]:
    return sorted(PLACEHOLDER.findall(text))


def valid_entry(code: str, key: str, src: str, val: str) -> None:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{code}:{key}: blank or invalid")
    if len(val) > max(2500, len(src) * 5):
        raise ValueError(f"{code}:{key}: unexpectedly long")
    if UNSAFE.search(val):
        raise ValueError(f"{code}:{key}: untrusted markup/marker")
    if exact_placeholders(val) != exact_placeholders(src):
        raise ValueError(f"{code}:{key}: interpolated placeholders changed")
    if sorted(TAG.findall(val)) != sorted(TAG.findall(src)):
        raise ValueError(f"{code}:{key}: HTML tag structure changed")


def valid_catalog(code: str, translated: dict, en: dict) -> None:
    if not isinstance(translated, dict) or set(translated) != set(en):
        raise ValueError(f"{code}: incomplete/extra keys")
    for key, src in en.items():
        valid_entry(code, key, src, translated[key])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--retry", type=int, default=3)
    p.add_argument("--only", nargs="*", help="Limit work to selected locale codes")
    args = p.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    en = json.loads(ENGLISH_FILE.read_text(encoding="utf-8"))
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    target = [code for code in registry["enabledUiLocales"] if code != "auto"]
    if len(target) != 60 or len(set(target)) != len(target):
        raise RuntimeError("Portal manifest no longer exposes exactly 60 unique UI locales")
    if args.only:
        unsupported = set(args.only) - set(target)
        if unsupported:
            raise ValueError(f"Not in Portal manifest: {sorted(unsupported)}")
        target = [code for code in target if code in args.only]
    failures = {}
    for code in target:
        path = CATALOG_DIR / f"{code}.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if set(existing) - set(en):
            raise RuntimeError(f"{code}: deprecated/unknown source keys in existing catalog")
        missing = {key: val for key, val in en.items() if key not in existing}
        if not missing:
            valid_catalog(code, existing, en)
            print(f"EXISTING {code}: {len(en)} complete fields", flush=True)
            continue
        for attempt in range(args.retry):
            try:
                # Preserve every existing string; translate only the missing keys.
                # The five preexisting catalogs have six new keys each.
                authored = translate_catalog(code, missing)
                fallback_keys = []
                for key, src in missing.items():
                    try:
                        valid_entry(code, key, src, authored[key])
                    except (ValueError, KeyError):
                        # Retry only the damaged field; never accept altered
                        # placeholders, URLs, HTML or unsafe provider markup.
                        try:
                            single = translate_catalog(code, {key: src})[key]
                            valid_entry(code, key, src, single)
                            authored[key] = single
                        except Exception:
                            # Fail safe with visible source-language fallback.
                            # Workflow metadata records these keys as NOT translated.
                            authored[key] = src
                            fallback_keys.append(key)
                data = {**existing, **authored}
                valid_catalog(code, data, en)
                if fallback_keys:
                    print(f"ENGLISH FALLBACK {code}: {len(fallback_keys)} keys; requires language review", flush=True)
                path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                meta[code] = {"provenance": "machine-prepared", "reviewed": False}
                META_FILE.write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                print(f"GENERATED {code}: {len(data)} fields; UNREVIEWED", flush=True)
                break
            except Exception as exc:
                if attempt + 1 == args.retry:
                    failures[code] = f"{type(exc).__name__}: {str(exc)[:200]}"
                    print(f"FAILED {code}: {failures[code]}", flush=True)
                else:
                    time.sleep(3 * (attempt + 1))
    if failures:
        raise RuntimeError(f"Catalog authoring incomplete; do NOT ship: {failures}")
    if not args.only:
        completed = {p.stem for p in CATALOG_DIR.glob("*.json") if not p.name.startswith("_")}
        if completed != set(target):
            raise RuntimeError(f"Catalog mismatch: missing {set(target) - completed}")
        for code in target:
            valid_catalog(code, json.loads((CATALOG_DIR / f"{code}.json").read_text()), en)
        print("All 60 Academy UI catalogs present (machine-prepared is not reviewed)", flush=True)


if __name__ == "__main__":
    main()
