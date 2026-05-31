"""Export storage helpers.

Production should store rendered binaries in object storage and keep only metadata
in the relational database. The database fallback is intentionally labeled for
local development and controlled demos; it is not the long-term production
storage architecture.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredExportContent:
    storage_backend: str
    storage_ref: str
    checksum_sha256: str
    content_base64: str | None
    content_bytes: int


def prepare_export_storage(export_id: str, content: bytes, storage_backend: str) -> StoredExportContent:
    checksum = hashlib.sha256(content).hexdigest()
    if storage_backend == "database_dev_fallback":
        return StoredExportContent(
            storage_backend="database_dev_fallback",
            storage_ref=f"db://compliance_exports/{export_id}/content_base64",
            checksum_sha256=checksum,
            content_base64=base64.b64encode(content).decode("ascii"),
            content_bytes=len(content),
        )
    # Object storage integration is intentionally abstract here: callers receive
    # metadata, while production deployments should replace this with S3/GCS/R2
    # upload code using server-side credentials.
    return StoredExportContent(
        storage_backend=storage_backend,
        storage_ref=f"object://compliance-exports/{export_id}",
        checksum_sha256=checksum,
        content_base64=None,
        content_bytes=len(content),
    )


def decode_export_content(package: dict) -> bytes:
    encoded = package.get("content_base64")
    if not encoded:
        raise ValueError("Export content is not available from the configured storage backend")
    return base64.b64decode(encoded)
