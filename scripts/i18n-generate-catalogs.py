#!/usr/bin/env python3
"""Build-time locale catalog authoring through AGRO-AI's deployed edge model.

This script never enables a locale by itself. It produces a source-fingerprinted
catalog that must pass the release validator before the locale is advertised.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOKENS = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
DEFAULT_ENDPOINT = "https://local-ai.agroai-pilot.com/api/chat"
MAX_KEYS = 20
MAX_SOURCE_CHARS = 1200
MAX_ATTEMPTS = 4
PARALLELISM = 3

RTL_ROOTS = {"ar", "fa", "ur"}
PROTECTED_EXACT = {"AGRO-AI", "GPT", "API", "OAuth", "CSV", "PDF", "JSON", "OpenET", "WiseConn", "Talgil", "Stripe"}


def clean_json_text(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"^\`\`\`(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*\`\`\`$", "", value)
    return value.strip()


def validate_chunk(source: dict[str, str], candidate: object) -> dict[str, str]:
    if not isinstance(candidate, dict) or set(source) != set(candidate):
        raise ValueError("translation_key_mismatch")
    out: dict[str, str] = {}
    for key, original in source.items():
        value = candidate[key]
        if not isinstance(value, str) or not value.strip() or "[object Object]" in value or "\ufffd" in value:
            raise ValueError(f"translation_invalid_value:{key}")
        value = value.strip()
        if sorted(TOKENS.findall(original)) != sorted(TOKENS.findall(value)):
            raise ValueError(f"translation_placeholder_mismatch:{key}")
        value.encode("utf-8", errors="strict")
        out[key] = value
    return out


def call_edge(locale: str, source: dict[str, str], endpoint: str) -> dict[str, str]:
    system = (
        f"Translate every JSON string value into the customer's language ({locale}). "
        "Return exactly one JSON object with the same keys. Preserve placeholders in braces, "
        "URLs, AGRO-AI, product names, technical identifiers, units and numeric values. "
        "Use natural enterprise-agriculture language for the requested locale. "
        "For pt-BR use Brazilian Portuguese. No explanations."
    )
    user = "QUESTION: " + json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    payload = {
        "model": "locale-catalog-authoring",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 2200},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = json.load(response)
    if body.get("done") is not True or body.get("provider") != "cloudflare-workers-ai":
        raise RuntimeError("edge_authoring_invalid_provider_response")
    raw = body.get("message", {}).get("content") or body.get("response") or ""
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("edge_authoring_empty_response")
    return validate_chunk(source, json.loads(clean_json_text(raw)))


def translate_chunk(locale: str, source: dict[str, str], endpoint: str) -> dict[str, str]:
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return call_edge(locale, source, endpoint)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(6, attempt * 1.25))
    raise RuntimeError(f"locale_chunk_failed:{locale}:{type(last).__name__ if last else 'unknown'}") from None


def chunks(source: dict[str, str]) -> list[dict[str, str]]:
    groups: list[dict[str, str]] = []
    current: dict[str, str] = {}
    chars = 0
    for key, value in source.items():
        cost = len(value) + len(key) + 12
        if current and (len(current) >= MAX_KEYS or chars + cost > MAX_SOURCE_CHARS):
            groups.append(current)
            current = {}
            chars = 0
        current[key] = value
        chars += cost
    if current:
        groups.append(current)
    return groups


def validate_full(source: dict[str, str], catalog: dict[str, str], locale: str) -> None:
    validate_chunk(source, catalog)
    if locale != "en":
        changed = sum(1 for key, original in source.items() if catalog[key].strip() != original.strip())
        minimum = max(25, len(source) // 20)
        if changed < minimum:
            raise ValueError(f"translation_no_meaningful_progress:{locale}:{changed}<{minimum}")


def generate_locale(locale: str, source_envelope: dict, outdir: Path, endpoint: str) -> Path:
    source: dict[str, str] = source_envelope["catalog"]
    locale = locale.strip()
    if locale == "en":
        catalog = dict(source)
    else:
        catalog: dict[str, str] = {}
        work = chunks(source)
        with ThreadPoolExecutor(max_workers=PARALLELISM) as executor:
            future_map = {executor.submit(translate_chunk, locale, chunk, endpoint): index for index, chunk in enumerate(work)}
            completed = 0
            for future in as_completed(future_map):
                catalog.update(future.result())
                completed += 1
                print(f"{locale} chunks {completed}/{len(work)} keys={len(catalog)}/{len(source)}", flush=True)
    validate_full(source, catalog, locale)
    root = locale.split("-", 1)[0].lower()
    envelope = {
        "schemaVersion": 2,
        "locale": locale,
        "direction": "rtl" if root in RTL_ROOTS else "ltr",
        "sourceFingerprint": source_envelope["sourceFingerprint"],
        "status": "complete-generated",
        "provider": "agroai_cloudflare_workers_ai_build_time",
        "catalog": dict(sorted(catalog.items())),
    }
    outdir.mkdir(parents=True, exist_ok=True)
    dest = outdir / f"{locale}.json"
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(dest)
    print(json.dumps({"status": "ok", "locale": locale, "keys": len(catalog), "sourceFingerprint": source_envelope["sourceFingerprint"]}))
    return dest


def validate_dir(source_envelope: dict, directory: Path, locales: list[str]) -> None:
    source = source_envelope["catalog"]
    expected_fp = source_envelope["sourceFingerprint"]
    for locale in locales:
        path = directory / f"{locale}.json"
        if not path.exists():
            raise FileNotFoundError(f"missing_catalog:{locale}")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("schemaVersion") != 2 or envelope.get("locale") != locale:
            raise ValueError(f"invalid_catalog_envelope:{locale}")
        if envelope.get("sourceFingerprint") != expected_fp or envelope.get("status") != "complete-generated":
            raise ValueError(f"stale_catalog:{locale}")
        validate_full(source, envelope.get("catalog") or {}, locale)
    print(json.dumps({"status": "ok", "validatedLocales": len(locales), "sourceFingerprint": expected_fp}))


def parse_locales(raw: str) -> list[str]:
    values = [value.strip() for value in raw.split(",") if value.strip()]
    for value in values:
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value):
            raise ValueError(f"invalid_locale_identifier:{value}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locales", required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--validate-dir")
    parser.add_argument("--outdir", default=str(ROOT / "shared/localization/catalogs"))
    parser.add_argument("--endpoint", default=os.environ.get("I18N_AUTHORING_ENDPOINT", DEFAULT_ENDPOINT))
    args = parser.parse_args()

    locales = parse_locales(args.locales)
    source = json.loads((ROOT / "shared/localization/source.json").read_text(encoding="utf-8"))

    if args.preflight:
        result = translate_chunk(locales[0], {"createAccount": "Create account", "fullName": "Full name"}, args.endpoint)
        print(json.dumps({"status": "ok", "locale": locales[0], "catalog": result}, ensure_ascii=False))
        return

    if args.validate_dir:
        validate_dir(source, Path(args.validate_dir), locales)
        return

    outdir = Path(args.outdir)
    for locale in locales:
        generate_locale(locale, source, outdir, args.endpoint)


if __name__ == "__main__":
    main()
