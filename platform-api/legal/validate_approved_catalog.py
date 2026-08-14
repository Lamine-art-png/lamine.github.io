#!/usr/bin/env python3
"""Fail-closed validator for the counsel-approved Platform API legal catalog.

This script never creates legal approval. It only validates evidence that has
already been committed by an authorized human process.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "platform-api" / "legal" / "approved-catalog.json"
ALLOWED_TYPES = {"api_terms", "acceptable_use", "privacy", "data_processing_addendum"}
MINIMUM_TYPES = {"api_terms", "acceptable_use", "privacy"}
SHA256 = re.compile(r"^[a-f0-9]{64}$")
VERSION = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"legal activation gate failed: {message}")


def parse_iso8601(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        fail(f"invalid ISO-8601 approved_at: {value!r} ({exc})")


def main() -> int:
    if not CATALOG.is_file():
        fail("platform-api/legal/approved-catalog.json is absent; counsel approval has not been recorded")
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"approved-catalog.json is invalid JSON: {exc}")

    if catalog.get("status") != "counsel_approved":
        fail("catalog status must be exactly counsel_approved")
    reviewer = str(catalog.get("reviewer") or "").strip()
    if len(reviewer) < 3:
        fail("reviewer evidence is missing")
    approval_reference = str(catalog.get("approval_reference") or "").strip()
    if len(approval_reference) < 3:
        fail("approval_reference evidence is missing")
    approved_at = str(catalog.get("approved_at") or "").strip()
    if not approved_at:
        fail("approved_at is missing")
    parse_iso8601(approved_at)

    documents = catalog.get("documents")
    if not isinstance(documents, list) or not documents:
        fail("documents must be a non-empty list")

    seen: set[str] = set()
    normalized: list[dict] = []
    for index, item in enumerate(documents):
        if not isinstance(item, dict):
            fail(f"document #{index + 1} must be an object")
        document_type = str(item.get("document_type") or "").strip()
        version = str(item.get("version") or "").strip()
        asset = str(item.get("asset") or "").strip()
        digest = str(item.get("sha256") or "").strip().lower()
        if document_type not in ALLOWED_TYPES:
            fail(f"unsupported document_type: {document_type!r}")
        if document_type in seen:
            fail(f"duplicate document_type: {document_type}")
        seen.add(document_type)
        if not VERSION.fullmatch(version):
            fail(f"unsafe or empty version for {document_type}: {version!r}")
        if not SHA256.fullmatch(digest):
            fail(f"invalid sha256 for {document_type}")

        expected = f"platform-api/assets/legal/{document_type}-{version}.html"
        if asset != expected:
            fail(f"{document_type} asset must be exactly {expected!r}, got {asset!r}")
        path = (ROOT / asset).resolve()
        legal_root = (ROOT / "platform-api" / "assets" / "legal").resolve()
        if legal_root not in path.parents:
            fail(f"asset escapes public legal root: {asset}")
        if not path.is_file():
            fail(f"approved public asset does not exist: {asset}")
        payload = path.read_bytes()
        if len(payload) < 500:
            fail(f"approved public asset is implausibly small: {asset}")
        calculated = hashlib.sha256(payload).hexdigest()
        if calculated != digest:
            fail(f"digest mismatch for {document_type}: catalog={digest}, actual={calculated}")
        if b"LEGAL REVIEW REQUIRED" in payload or b"NOT EFFECTIVE" in payload:
            fail(f"approved public asset still contains draft/non-effective marker: {asset}")
        if b"<html" not in payload.lower() or b"</html>" not in payload.lower():
            fail(f"approved public asset must be a complete HTML document: {asset}")
        normalized.append(
            {
                "document_type": document_type,
                "version": version,
                "asset": asset,
                "sha256": digest,
                "reacceptance_required": bool(item.get("reacceptance_required", False)),
            }
        )

    missing = MINIMUM_TYPES - seen
    if missing:
        fail(f"minimum public legal catalog is missing: {', '.join(sorted(missing))}")

    print(json.dumps({
        "status": "ok",
        "catalog_status": "counsel_approved",
        "approved_at": approved_at,
        "reviewer": reviewer,
        "approval_reference": approval_reference,
        "documents": normalized,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
