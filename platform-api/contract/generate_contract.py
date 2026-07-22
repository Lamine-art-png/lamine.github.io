#!/usr/bin/env python3
"""
Derive the public Platform API contract from the *real backend* and write the
snapshot that the developer-platform docs/reference are generated from.

This is the single source of truth. The docs must never invent endpoints,
key prefixes, or response shapes — they are rendered from this file, and this
file is produced only by the backend's own curated OpenAPI generator
(`GET /v1/platform/openapi.json`, gated by PLATFORM_API_PUBLIC_DOCS_ENABLED).

Run from the repository root:

    python3 platform-api/contract/generate_contract.py            # write + verify
    python3 platform-api/contract/generate_contract.py --check     # verify only (CI)

Exit non-zero if:
  * the generated contract's canonical digest does not match the backend's
    reviewed snapshot (agroai_api/tests/contracts/platform_api_openapi.sha256)
  * any private / admin / portal (developer control-plane) route leaks
  * any documented path is not under /platform/
  * the Platform API bearer scheme or operation security is weakened
  * the committed snapshot differs from a fresh generation (--check)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API_DIR = REPO / "agroai_api"
SNAPSHOT = REPO / "platform-api" / "contract" / "platform_api_openapi.json"
DIGEST_FILE = REPO / "platform-api" / "contract" / "platform_api_openapi.sha256"
BACKEND_DIGEST = API_DIR / "tests" / "contracts" / "platform_api_openapi.sha256"

# The public contract must expose only these first-party key prefixes and never
# advertise anything the backend gates behind a feature flag.
EXPECTED_KEY_PREFIXES = ("agro_test_", "agro_live_")
FORBIDDEN_PATH_MARKERS = ("/developer", "/admin", "/internal", "/portal")
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def generate_contract() -> dict:
    """Call the backend's own curated generator. No invention happens here."""
    sys.path.insert(0, str(API_DIR))
    from app.core.config import settings  # noqa: E402

    settings.PLATFORM_API_PUBLIC_DOCS_ENABLED = True
    from fastapi.testclient import TestClient  # noqa: E402
    from app.main import app  # noqa: E402

    resp = TestClient(app).get("/v1/platform/openapi.json")
    if resp.status_code != 200:
        raise SystemExit(f"backend openapi endpoint returned {resp.status_code}")
    return resp.json()


def canonical_digest(contract: dict) -> str:
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _uses_platform_api_key(operation: object) -> bool:
    if not isinstance(operation, dict):
        return False
    security = operation.get("security")
    if not isinstance(security, list):
        return False
    return any(
        isinstance(requirement, dict)
        and "PlatformApiKey" in requirement
        and requirement.get("PlatformApiKey") == []
        for requirement in security
    )


def audit(contract: dict) -> list[str]:
    problems: list[str] = []
    paths = contract.get("paths", {})

    if not isinstance(paths, dict) or not paths:
        problems.append("contract has no paths")
        paths = {}

    for path, path_item in paths.items():
        if not path.startswith("/platform/"):
            problems.append(f"path outside /platform/: {path}")
        for marker in FORBIDDEN_PATH_MARKERS:
            if marker in path:
                problems.append(f"private/control-plane route leaked into public contract: {path}")

        if not isinstance(path_item, dict):
            problems.append(f"path item is not an object: {path}")
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                problems.append(f"operation is not an object: {method.upper()} {path}")
                continue
            if operation.get("x-agroai-authentication") != "platform_api_key":
                problems.append(f"public operation lacks platform_api_key marker: {method.upper()} {path}")
            if not _uses_platform_api_key(operation):
                problems.append(f"public operation lacks PlatformApiKey security: {method.upper()} {path}")

    schemes = contract.get("components", {}).get("securitySchemes", {})
    scheme = schemes.get("PlatformApiKey") if isinstance(schemes, dict) else None
    if not isinstance(scheme, dict):
        problems.append("PlatformApiKey security scheme missing from contract")
    else:
        if scheme.get("type") != "http":
            problems.append("PlatformApiKey security scheme must use type=http")
        if str(scheme.get("scheme", "")).lower() != "bearer":
            problems.append("PlatformApiKey security scheme must use scheme=bearer")
        bearer_format = str(scheme.get("bearerFormat", ""))
        missing_prefixes = [prefix for prefix in EXPECTED_KEY_PREFIXES if prefix not in bearer_format]
        if missing_prefixes:
            problems.append(
                "PlatformApiKey bearerFormat is missing reviewed key prefixes: "
                + ", ".join(missing_prefixes)
            )

    # Digest must match the backend's reviewed snapshot exactly.
    if BACKEND_DIGEST.exists():
        expected = BACKEND_DIGEST.read_text(encoding="utf-8").strip()
        actual = canonical_digest(contract)
        if actual != expected:
            problems.append(
                f"contract digest {actual} != backend reviewed snapshot {expected}; "
                "the public contract changed without a reviewed backend update"
            )
    else:
        problems.append(f"backend reviewed digest not found at {BACKEND_DIGEST}")

    return problems


def write_snapshot(contract: dict) -> None:
    SNAPSHOT.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    DIGEST_FILE.write_text(canonical_digest(contract) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify only; do not write")
    args = ap.parse_args()

    contract = generate_contract()
    problems = audit(contract)

    if args.check:
        if not SNAPSHOT.exists():
            problems.append("committed snapshot missing; run without --check to generate")
        else:
            committed = SNAPSHOT.read_text(encoding="utf-8")
            fresh = json.dumps(contract, indent=2, sort_keys=True) + "\n"
            if committed != fresh:
                problems.append(
                    "committed platform-api/contract/platform_api_openapi.json is out of date; "
                    "regenerate with `python3 platform-api/contract/generate_contract.py`"
                )
    else:
        write_snapshot(contract)
        print(f"wrote {SNAPSHOT.relative_to(REPO)} ({len(contract.get('paths', {}))} paths)")
        print(f"wrote {DIGEST_FILE.relative_to(REPO)} ({canonical_digest(contract)})")

    if problems:
        print(f"\nContract audit failed ({len(problems)} problem(s)):", file=sys.stderr)
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        return 1
    print("Contract audit passed: docs snapshot matches the real backend contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
