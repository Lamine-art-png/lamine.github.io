#!/usr/bin/env python3
"""Build-time locale catalog authoring through AGRO-AI's deployed edge model.

This script never enables a locale by itself. It produces a source-fingerprinted
catalog that must pass the release validator before the locale is advertised.
"""
from __future__ import annotations

import ast

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from i18n_public_translate import translate_catalog as public_translate_catalog
from i18n_catalog_identity import write_envelope
from i18n_quality import collapsed_values, degenerate, do_not_translate, has_marker_residue, has_placeholder_bracket_residue, serbian_latin_to_cyrillic, english_leak_keys, quality_errors, quality_report

ROOT = Path(__file__).resolve().parents[1]
TOKENS = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
DEFAULT_ENDPOINT = "https://local-ai.agroai-pilot.com/api/chat"
# The customer API is never an implicit build-time fallback. Using it requires
# an explicitly configured endpoint plus bearer token so release authoring
# cannot accidentally hammer the authenticated production catalog route.
CATALOG_AUTHORING_ENDPOINT = os.environ.get("I18N_CATALOG_AUTHORING_ENDPOINT", "").strip()
CATALOG_AUTHORING_TOKEN = os.environ.get("I18N_CATALOG_AUTHORING_TOKEN", "").strip()
MAX_KEYS = 24
MAX_SOURCE_CHARS = 2200
MAX_ATTEMPTS = 2
PARALLELISM = 2
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_MODELS = (
    os.environ.get("I18N_CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct-fast").strip(),
    os.environ.get("I18N_CLOUDFLARE_FALLBACK_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8").strip(),
)

RTL_ROOTS = {"ar", "fa", "ur"}
PROTECTED_EXACT = {"AGRO-AI", "GPT", "API", "OAuth", "CSV", "PDF", "JSON", "OpenET", "WiseConn", "Talgil", "Stripe"}


def clean_json_text(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"^\`\`\`(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*\`\`\`$", "", value).strip()
    # Structured-output models occasionally prepend/append a short sentence
    # even when instructed not to. Accept exactly the outer JSON object while
    # still letting json.loads fail closed on malformed content.
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        value = value[start:end + 1]
    return value.strip()


def validate_chunk(source: dict[str, str], candidate: object) -> dict[str, str]:
    if not isinstance(candidate, dict) or set(source) != set(candidate):
        raise ValueError("translation_key_mismatch")
    out: dict[str, str] = {}
    for key, original in source.items():
        value = candidate[key]
        if not isinstance(value, str) or not value.strip() or "[object Object]" in value or "\ufffd" in value:
            raise ValueError(f"translation_invalid_value:{key}")
        if (has_marker_residue(value) and not has_marker_residue(original)) or has_placeholder_bracket_residue(value, original):
            raise ValueError(f"translation_marker_residue:{key}")
        if degenerate(value, original):
            raise ValueError(f"translation_degenerate_output:{key}")
        value = value.strip()
        if sorted(TOKENS.findall(original)) != sorted(TOKENS.findall(value)):
            raise ValueError(f"translation_placeholder_mismatch:{key}")
        value.encode("utf-8", errors="strict")
        out[key] = value
    return out


def cloudflare_rest_available() -> bool:
    return bool(CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID)


def catalog_api_available() -> bool:
    return bool(CATALOG_AUTHORING_ENDPOINT and CATALOG_AUTHORING_TOKEN)


def call_cloudflare_rest(locale: str, source: dict[str, str]) -> dict[str, str]:
    system = (
        f"Translate every JSON string value into the customer's language ({locale}). "
        "Return exactly one JSON object with the same keys. Preserve placeholders in braces, "
        "URLs, AGRO-AI, product names, technical identifiers, units and numeric values. "
        "Use natural enterprise-agriculture language for the requested locale. "
        "For pt-BR use Brazilian Portuguese. No explanations."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(source, ensure_ascii=False, separators=(",", ":"))},
    ]
    failures: list[str] = []
    for model in CLOUDFLARE_MODELS:
        if not model:
            continue
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"
        payload = {
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1400,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AGRO-AI-Localization-Release/2.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                body = json.load(response)
            if body.get("success") is not True:
                raise RuntimeError(f"cloudflare_rest_unsuccessful:{body.get('errors')}")
            result = body.get("result") or {}
            raw = (
                result.get("response")
                or result.get("result", {}).get("response")
                or result.get("choices", [{}])[0].get("message", {}).get("content")
                or ""
            )
            if not isinstance(raw, str) or not raw.strip():
                raise RuntimeError("cloudflare_rest_empty_response")
            cleaned = clean_json_text(raw)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                parsed = ast.literal_eval(cleaned)
            return validate_chunk(source, parsed)
        except Exception as exc:
            failures.append(f"{model}:{type(exc).__name__}:{str(exc)[:240]}")
    raise RuntimeError("cloudflare_rest_models_failed:" + "|".join(failures))


def call_catalog_api(locale: str, source: dict[str, str]) -> dict[str, str]:
    """Use an explicitly authorized catalog endpoint as an optional provider."""
    if not catalog_api_available():
        raise RuntimeError("catalog_api_not_configured")
    request = urllib.request.Request(
        CATALOG_AUTHORING_ENDPOINT,
        data=json.dumps({"locale": locale, "source": source}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://app.agroai-pilot.com",
            "Authorization": f"Bearer {CATALOG_AUTHORING_TOKEN}",
            "User-Agent": "AGRO-AI-Localization-Release/4.0",
            "X-Request-Id": f"catalog-authoring-{locale}-{int(time.time() * 1000)}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            diagnostic = error.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            diagnostic = ""
        raise RuntimeError(f"catalog_api_http_{error.code}:{diagnostic}") from None
    if body.get("status") != "ok" or body.get("locale") != locale:
        raise RuntimeError(f"catalog_api_invalid_response:{str(body)[:300]}")
    return validate_chunk(source, body.get("catalog"))


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
        "options": {"temperature": 0, "num_predict": 1400},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Mozilla/5.0 AGRO-AI-Localization-Release/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            diagnostic = error.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            diagnostic = ""
        raise RuntimeError(f"edge_http_{error.code}:{diagnostic}") from None
    if body.get("done") is not True or body.get("provider") != "cloudflare-workers-ai":
        raise RuntimeError("edge_authoring_invalid_provider_response")
    raw = body.get("message", {}).get("content") or body.get("response") or ""
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("edge_authoring_empty_response")
    cleaned = clean_json_text(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(cleaned)
    return validate_chunk(source, parsed)


def translate_chunk(locale: str, source: dict[str, str], endpoint: str) -> dict[str, str]:
    last: Exception | None = None
    explicit_authoring = endpoint.startswith("http://127.0.0.1:") or endpoint.startswith("http://localhost:")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # Deterministic release authoring starts with the same public batch
            # translation path used by AGRO-AI's edge fast path, then validates
            # exact keys/placeholders before accepting the chunk.
            try:
                return validate_chunk(source, public_translate_catalog(locale, source))
            except Exception as public_exc:
                last = public_exc
            # Release workflows deliberately start an isolated, production-equivalent
            # authoring worker as a secondary fallback.
            if explicit_authoring:
                try:
                    return call_edge(locale, source, endpoint)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as edge_exc:
                    last = edge_exc
            if cloudflare_rest_available():
                try:
                    return call_cloudflare_rest(locale, source)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as rest_exc:
                    last = rest_exc
            if catalog_api_available():
                try:
                    return call_catalog_api(locale, source)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as catalog_exc:
                    last = catalog_exc
            if not explicit_authoring:
                return call_edge(locale, source, endpoint)
            raise last or RuntimeError("local_authoring_unavailable")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(6, attempt * 1.25))
    detail = str(last)[:500] if last else "unknown"
    raise RuntimeError(f"locale_chunk_failed:{locale}:{type(last).__name__ if last else 'unknown'}:{detail}") from None


def translate_resilient(locale: str, source: dict[str, str], endpoint: str) -> dict[str, str]:
    """Translate a chunk, recursively bisecting failures down to one source string.

    A single malformed model response must never discard an otherwise healthy
    locale build. Smaller repair chunks also reduce structured-output pressure.
    """
    try:
        return translate_chunk(locale, source, endpoint)
    except RuntimeError:
        if len(source) <= 1:
            raise
        entries = list(source.items())
        midpoint = max(1, len(entries) // 2)
        left = dict(entries[:midpoint])
        right = dict(entries[midpoint:])
        merged: dict[str, str] = {}
        merged.update(translate_resilient(locale, left, endpoint))
        merged.update(translate_resilient(locale, right, endpoint))
        return merged


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
    errors = quality_errors(locale, source, catalog)
    if errors:
        raise ValueError(";".join(errors))
    if locale != "en":
        changed = sum(1 for key, original in source.items() if catalog[key].strip() != original.strip())
        minimum = max(25, len(source) // 20)
        if changed < minimum:
            raise ValueError(f"translation_no_meaningful_progress:{locale}:{changed}<{minimum}")


_HISTORY: dict[str, dict[str, str] | None] = {}


def historical_source(fingerprint: str) -> dict[str, str] | None:
    """Find the committed source.json that had this fingerprint (git history)."""
    if not fingerprint:
        return None
    if fingerprint in _HISTORY:
        return _HISTORY[fingerprint]
    import subprocess
    found = None
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "-n", "200", "--", "shared/localization/source.json"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split()
        for sha in shas:
            raw = subprocess.run(["git", "show", f"{sha}:shared/localization/source.json"], cwd=ROOT, capture_output=True, text=True)
            if raw.returncode != 0:
                continue
            candidate = json.loads(raw.stdout)
            if candidate.get("sourceFingerprint") == fingerprint:
                found = candidate.get("catalog") or {}
                break
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        found = None
    _HISTORY[fingerprint] = found
    return found


def seed_catalog(locale: str, source_envelope: dict, seed_dir: Path | None) -> dict[str, str]:
    """Reuse a previously validated catalog, dropping only entries that need work."""
    if not seed_dir:
        return {}
    path = seed_dir / f"{locale}.json"
    if not path.exists():
        return {}
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if envelope.get("locale") != locale:
        return {}
    source = source_envelope["catalog"]
    prior = envelope.get("catalog") or {}
    if envelope.get("sourceFingerprint") != source_envelope["sourceFingerprint"]:
        # Reuse only entries whose English text is unchanged since the seed
        # catalog was generated; everything else is translated fresh.
        historical = historical_source(envelope.get("sourceFingerprint") or "")
        if historical is None:
            return {}
        prior = {key: value for key, value in prior.items() if key in source and historical.get(key) == source[key]}
    leaks = set(english_leak_keys(locale, source, prior))
    # A stock phrase reused for many unrelated strings is provider failure, not
    # a translation: never carry it forward.
    collapsed = set(collapsed_values(source, prior))
    seeded: dict[str, str] = {}
    for key, original in source.items():
        value = prior.get(key)
        if key in leaks or not isinstance(value, str) or not value.strip() or value.strip() in collapsed:
            continue
        try:
            seeded.update(validate_chunk({key: original}, {key: value}))
        except ValueError:
            continue
    print(f"{locale} seeded {len(seeded)}/{len(source)} keys; {len(leaks)} flagged for re-translation", flush=True)
    return seeded


def repair_english_leaks(locale: str, source: dict[str, str], catalog: dict[str, str], endpoint: str) -> None:
    """Second pass for strings a provider returned untranslated."""
    leaks = english_leak_keys(locale, source, catalog)
    if not leaks:
        return
    print(f"{locale} repairing {len(leaks)} untranslated strings", flush=True)
    for group in chunks({key: source[key] for key in leaks}):
        candidates: list[dict[str, str]] = []
        if cloudflare_rest_available():
            try:
                candidates.append(call_cloudflare_rest(locale, group))
            except Exception as exc:  # repair is best-effort; the release gate decides
                print(f"{locale} repair model pass failed: {type(exc).__name__}", flush=True)
        try:
            candidates.append(translate_chunk(locale, group, endpoint))
        except Exception as exc:
            print(f"{locale} repair provider pass failed: {type(exc).__name__}", flush=True)
        for candidate in candidates:
            for key, value in candidate.items():
                if key in group and not english_leak_keys(locale, {key: source[key]}, {key: value}):
                    catalog[key] = value
                    group = {k: v for k, v in group.items() if k != key}


def generate_locale(locale: str, source_envelope: dict, outdir: Path, endpoint: str, seed_dir: Path | None = None) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    source: dict[str, str] = source_envelope["catalog"]
    locale = locale.strip()
    if locale == "en":
        catalog = dict(source)
    else:
        catalog: dict[str, str] = seed_catalog(locale, source_envelope, seed_dir)
        # Code samples and wire-protocol literals are never translated.
        for key, value in source.items():
            if do_not_translate(value):
                catalog[key] = value
        aliases_by_value: dict[str, list[str]] = {}
        for key, value in source.items():
            aliases_by_value.setdefault(value, []).append(key)
        representative_source = {
            keys[0]: value for value, keys in aliases_by_value.items()
        }
        work = chunks(representative_source)
        progress_path = outdir / f".{locale}.progress.json"
        if progress_path.exists():
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
                if progress.get("sourceFingerprint") == source_envelope["sourceFingerprint"]:
                    prior = progress.get("catalog") or {}
                    if isinstance(prior, dict):
                        for key, value in prior.items():
                            if key in source and isinstance(value, str) and value.strip():
                                catalog[key] = value
            except Exception:
                pass

        pending: list[tuple[int, dict[str, str]]] = []
        completed = 0
        for index, chunk in enumerate(work):
            missing = {key: value for key, value in chunk.items() if key not in catalog}
            if not missing:
                completed += 1
            else:
                pending.append((index, missing))

        if pending:
            with ThreadPoolExecutor(max_workers=PARALLELISM) as executor:
                futures = {
                    executor.submit(translate_resilient, locale, missing, endpoint): (index, missing)
                    for index, missing in pending
                }
                for future in as_completed(futures):
                    translated = future.result()
                    for key, value in translated.items():
                        for alias in aliases_by_value[source[key]]:
                            catalog[alias] = value
                    # Persist every validated completed chunk. A later provider
                    # failure or workflow cancellation can resume without
                    # discarding successful build-time translation work.
                    progress_path.write_text(json.dumps({
                        "sourceFingerprint": source_envelope["sourceFingerprint"],
                        "locale": locale,
                        "catalog": catalog,
                    }, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
                    completed += 1
                    print(f"{locale} chunks {completed}/{len(work)} keys={len(catalog)}/{len(source)}", flush=True)
        for key, value in source.items():
            if key not in catalog:
                sibling = next((catalog[alias] for alias in aliases_by_value[value] if alias in catalog), None)
                if sibling is not None:
                    catalog[key] = sibling
        if locale.split("-", 1)[0] == "sr":
            for key, value in list(catalog.items()):
                if not do_not_translate(source[key]):
                    catalog[key] = serbian_latin_to_cyrillic(value, source[key])
        repair_english_leaks(locale, source, catalog, endpoint)
    print(json.dumps({"quality": quality_report(locale, source, catalog)}), flush=True)
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
    write_envelope(tmp, envelope)  # stamps catalogSha256 (exact artifact identity)
    tmp.replace(dest)
    progress_path = outdir / f".{locale}.progress.json"
    if progress_path.exists():
        progress_path.unlink()
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
    parser.add_argument("--seed-dir", default="", help="reuse validated entries from an existing catalog directory")
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
        generate_locale(locale, source, outdir, args.endpoint, Path(args.seed_dir) if args.seed_dir else None)


if __name__ == "__main__":
    main()
