from __future__ import annotations

import concurrent.futures
import hashlib
import http.client
import json
import os
import pathlib
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

API_URL = os.environ.get("API_URL", "https://app.agroai-pilot.com").rstrip("/")
TOKEN = os.environ.get("QUEUE_CONSUMER_TOKEN", "").strip()
OUT = pathlib.Path(os.environ.get("I18N_MATRIX_OUTPUT_DIR", "i18n-matrix"))
WORKERS = int(os.environ.get("I18N_MATRIX_WORKERS", "3"))
ATTEMPTS = int(os.environ.get("I18N_MATRIX_ATTEMPTS", "4"))
TIMEOUT = int(os.environ.get("I18N_MATRIX_TIMEOUT_SECONDS", "120"))
UA = "AGRO-AI-Production-I18n-Matrix/2.0"
TRANSIENT = (
    urllib.error.URLError,
    urllib.error.HTTPError,
    TimeoutError,
    socket.timeout,
    ConnectionError,
    http.client.RemoteDisconnected,
    ssl.SSLError,
    json.JSONDecodeError,
    RuntimeError,
)


def describe_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace")[:1600]
        except Exception:  # noqa: BLE001
            body = ""
        return f"HTTPError:{exc.code}:{body or exc.reason}"
    return f"{type(exc).__name__}:{exc}"


def request_json(path: str, payload: dict[str, Any] | None = None, auth: bool = False) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Accept": "application/json", "User-Agent": UA, "Cache-Control": "no-cache"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        value = json.loads(response.read().decode())
    if not isinstance(value, dict):
        raise RuntimeError(f"non_object_json:{path}")
    return value


def retry_get(path: str) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return request_json(path)
        except TRANSIENT as exc:
            error = exc
            print(f"RETRY GET {path} attempt={attempt} {describe_error(exc)}", flush=True)
            time.sleep(attempt * 2)
    raise RuntimeError(f"GET failed {path}: {describe_error(error) if error else 'unknown'}") from error


def valid(locale: str, result: dict[str, Any]) -> bool:
    return (
        result.get("status") == "ok"
        and result.get("locale") == locale
        and result.get("key_count") == 4
        and isinstance(result.get("changed_count"), int)
        and result["changed_count"] >= 2
        and isinstance(result.get("catalog_sha256"), str)
        and len(result["catalog_sha256"]) == 64
        and bool(result.get("providers"))
        and bool(result.get("models"))
    )


def verify(locale: str) -> dict[str, Any]:
    error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            result = request_json("/v1/i18n/internal/canary", {"locale": locale}, auth=True)
            if valid(locale, result):
                print(f"PASS {locale} attempt={attempt}", flush=True)
                return result
            error = f"invalid_payload:{json.dumps(result, ensure_ascii=False, sort_keys=True)}"
        except TRANSIENT as exc:
            error = describe_error(exc)
        print(f"RETRY {locale} attempt={attempt} {error}", flush=True)
        time.sleep(attempt * 3)
    raise RuntimeError(f"{locale}:{error}")


def run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results_dir = OUT / "results"
    results_dir.mkdir(exist_ok=True)
    (OUT / "started.json").write_text(
        json.dumps({"status": "started", "api_url": API_URL, "workers": WORKERS, "attempts": ATTEMPTS, "release_sha": os.environ.get("GITHUB_SHA", "")}, indent=2),
        encoding="utf-8",
    )
    if not TOKEN:
        raise RuntimeError("QUEUE_CONSUMER_TOKEN missing")

    registry = retry_get("/v1/i18n/languages")
    if registry.get("status") != "ok" or int(registry.get("count", 0)) < 61:
        raise RuntimeError(f"invalid_registry:{registry}")
    locales = [x.get("code") for x in registry.get("languages", []) if isinstance(x, dict) and x.get("code") not in {"auto", "en"}]
    locales = [x for x in locales if isinstance(x, str) and x]
    if len(locales) < 59 or len(set(locales)) != len(locales):
        raise RuntimeError(f"unexpected_locale_count:{len(locales)}")
    (OUT / "languages.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "locales.txt").write_text("\n".join(locales) + "\n", encoding="utf-8")

    matrix: list[dict[str, Any]] = []
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(verify, locale): locale for locale in locales}
        for future in concurrent.futures.as_completed(futures):
            locale = futures[future]
            try:
                result = future.result()
                matrix.append(result)
                (results_dir / f"{locale.replace('/', '_')}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{locale}: {exc}")
                (results_dir / f"{locale.replace('/', '_')}.error.txt").write_text(str(exc), encoding="utf-8")

    matrix.sort(key=lambda item: str(item.get("locale", "")))
    (OUT / "matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        (OUT / "failures.txt").write_text("\n".join(sorted(failures)) + "\n", encoding="utf-8")
        raise RuntimeError("matrix_failed:" + " | ".join(sorted(failures)))
    if len(matrix) != len(locales) or any(not valid(str(x.get("locale", "")), x) for x in matrix):
        raise RuntimeError(f"matrix_reconciliation_failed:{len(matrix)}/{len(locales)}")

    digest = hashlib.sha256(json.dumps(matrix, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    summary = {"status": "ok", "release_sha": os.environ.get("GITHUB_SHA", ""), "locale_count": len(matrix), "matrix_sha256": digest, "locales": [x["locale"] for x in matrix]}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:  # noqa: BLE001
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "fatal-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"FATAL {type(exc).__name__}: {exc}", flush=True)
        raise
