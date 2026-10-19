#!/usr/bin/env python3
"""Author complete, static Academy catalogs for every enabled AEP UI locale.

Uses the same build-time translation helper as the Enterprise Portal authoring
pipeline. No production visitor needs a runtime translation provider.
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from i18n_public_translate import translate_catalog, _translate_pack

SOURCE = ROOT / "cloudflare/academy-early-access-worker/academy-source.json"
DEST = ROOT / "cloudflare/academy-early-access-worker/src/academy-locales.json"
REGISTRY = ROOT / "shared/supported-locales.json"

data = json.loads(SOURCE.read_text(encoding="utf-8"))
english = data["english"]
seed = data["seeds"]
registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
codes = [code for code in registry["enabledUiLocales"] if code != "auto"]
assert set(codes) == set(registry["catalogCompleteLocales"])
options = [{"code": "auto", "nativeName": "Auto"}]
by_code = {row["code"]: row for row in registry["locales"]}
options += [{"code": code, "nativeName": by_code[code]["nativeName"]} for code in codes]
rtl = [code for code in codes if by_code[code].get("direction") == "rtl"]
assert all(code in by_code for code in codes)

# Fail closed: partial/mismatched/English-fallback catalogs never ship.
def validate(code: str, catalog: dict) -> dict:
    if not isinstance(catalog, dict) or set(catalog) != set(english):
        raise ValueError(f"{code}: catalog keys incomplete")
    for key, value in catalog.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{code}:{key}: empty translation")
        if any(marker in value for marker in ["<<<", ">>>", "<script", "</script", "[object Object]"]):
            raise ValueError(f"{code}:{key}: invalid markup or provider residue")
        if len(value) > 2500:
            raise ValueError(f"{code}:{key}: translated content too long")
        if code != "en" and key in ("heading", "formTitle", "consent", "success") and value == english[key]:
            raise ValueError(f"{code}:{key}: untranslated critical text")
    return catalog


def translate_one(code: str) -> tuple[str, dict]:
    if code == "en":
        return code, validate(code, english)
    existing = seed.get(code)
    if existing:
        # Retain the previously approved pt-BR, es and French copy verbatim.
        missing = {k: v for k, v in english.items() if k not in existing}
        if missing:
            existing = {**existing, **translate_catalog(code, missing)}
        return code, validate(code, existing)

    errors = []
    for attempt in range(4):
        try:
            return code, validate(code, translate_catalog(code, english))
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc)[:140]}")
            time.sleep(1.5 * (attempt + 1))

    # Markers can be garbled in low-resource language batches. Translate each
    # field independently before giving up, retaining all key-parity guarantees.
    translated = {}
    for key, value in english.items():
        for attempt in range(3):
            try:
                translated[key] = _translate_pack(code, [(key, value)])[key]
                break
            except Exception as exc:
                if attempt == 2:
                    raise RuntimeError(f"{code}:{key}: failed after retries; original: {errors}") from exc
                time.sleep(2 * (attempt + 1))
    return code, validate(code, translated)


if __name__ == "__main__":
    catalogs = {}
    failures = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(translate_one, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                _, catalog = future.result()
                catalogs[code] = catalog
                print(f"READY {code} ({len(catalog)} translated fields)", flush=True)
            except Exception as exc:
                failures[code] = str(exc)
                print(f"FAILED {code}: {exc}", flush=True)
    if failures:
        raise SystemExit(f"Refusing incomplete deployment: {json.dumps(failures, ensure_ascii=False)}")
    if set(catalogs) != set(codes):
        raise SystemExit("Missing enabled UI locales")

    payload = {
        "registryVersion": registry["version"],
        "options": options,
        "rtl": rtl,
        "catalogs": {code: catalogs[code] for code in codes},
    }
    DEST.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"ALL {len(codes)} AEP UI LANGUAGES READY; output bytes={DEST.stat().st_size}", flush=True)
