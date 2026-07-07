from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
from typing import Any

API_URL = os.environ.get("API_URL", "https://app.agroai-pilot.com").rstrip("/")
TOKEN = os.environ.get("QUEUE_CONSUMER_TOKEN", "").strip()
OUTPUT_DIR = pathlib.Path(os.environ.get("I18N_MATRIX_OUTPUT_DIR", "i18n-matrix"))
MAX_WORKERS = int(os.environ.get("I18N_MATRIX_WORKERS", "6"))
MAX_ATTEMPTS = int(os.environ.get("I18N_MATRIX_ATTEMPTS", "3"))
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("I18N_MATRIX_TIMEOUT_SECONDS", "120"))


def _json_request(path: str, *, payload: dict[str, Any] | None = None, authenticated: bool = False) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if authenticated:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{API_URL}{path}", data=body, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"non-object JSON from {path}")
    return parsed


def _safe_name(locale: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in locale)


def _valid_canary(locale: str, result: dict[str, Any]) -> bool:
    return (
        result.get("status") == "ok"
        and result.get("locale") == locale
        and result.get("key_count") == 4
        and isinstance(result.get("changed_count"), int)
        and result["changed_count"] >= 2
        and isinstance(result.get("changed_keys"), list)
        and len(result["changed_keys"]) >= 2
        and isinstance(result.get("catalog_sha256"), str)
        and len(result["catalog_sha256"]) == 64
        and isinstance(result.get("providers"), list)
        and len(result["providers"]) >= 1
        and isinstance(result.get("models"), list)
        and len(result["models"]) >= 1
    )


def verify_locale(locale: str) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = _json_request("/v1/i18n/internal/canary", payload={"locale": locale}, authenticated=True)
            if _valid_canary(locale, result):
                print(f"PASS {locale} attempt={attempt}", flush=True)
                return result
            last_error = f"invalid canary payload: {json.dumps(result, ensure_ascii=False, sort_keys=True)}"
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
        print(f"RETRY {locale} attempt={attempt} reason={last_error}", flush=True)
        time.sleep(attempt * 2)
    raise RuntimeError(f"locale {locale} failed after {MAX_ATTEMPTS} attempts: {last_error}")


def main() -> int:
    if not TOKEN:
        raise RuntimeError("QUEUE_CONSUMER_TOKEN is required")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results_dir = OUTPUT_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    language_payload = _json_request("/v1/i18n/languages")
    if language_payload.get("status") != "ok" or int(language_payload.get("count", 0)) < 61:
        raise RuntimeError(f"invalid live language registry: {language_payload}")

    languages = language_payload.get("languages")
    if not isinstance(languages, list):
        raise RuntimeError("language registry does not contain a language list")
    locales = [item.get("code") for item in languages if isinstance(item, dict) and item.get("code") not in {"auto", "en"}]
    locales = [locale for locale in locales if isinstance(locale, str) and locale]
    if len(locales) < 59 or len(locales) != len(set(locales)):
        raise RuntimeError(f"unexpected production locale matrix size: {len(locales)}")

    (OUTPUT_DIR / "languages.json").write_text(json.dumps(language_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "locales.txt").write_text("\n".join(locales) + "\n", encoding="utf-8")

    matrix: list[dict[str, Any]] = []
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_locale = {executor.submit(verify_locale, locale): locale for locale in locales}
        for future in concurrent.futures.as_completed(future_to_locale):
            locale = future_to_locale[future]
            try:
                result = future.result()
                matrix.append(result)
                (results_dir / f"{_safe_name(locale)}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 - matrix must aggregate every failure
                failures.append(f"{locale}: {exc}")
                (results_dir / f"{_safe_name(locale)}.error.txt").write_text(str(exc), encoding="utf-8")

    matrix.sort(key=lambda item: str(item.get("locale", "")))
    (OUTPUT_DIR / "matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        (OUTPUT_DIR / "failures.txt").write_text("\n".join(sorted(failures)) + "\n", encoding="utf-8")
        raise RuntimeError("production locale matrix failed:\n" + "\n".join(sorted(failures)))
    if len(matrix) != len(locales):
        raise RuntimeError(f"matrix reconciliation mismatch expected={len(locales)} actual={len(matrix)}")
    if any(not _valid_canary(str(item.get("locale", "")), item) for item in matrix):
        raise RuntimeError("matrix contains an invalid canary result")

    release_sha = os.environ.get("GITHUB_SHA", "")
    summary = {
        "status": "ok",
        "checked_at_epoch": int(time.time()),
        "release_sha": release_sha,
        "locale_count": len(matrix),
        "matrix_sha256": hashlib.sha256(json.dumps(matrix, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "locales": [item["locale"] for item in matrix],
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
