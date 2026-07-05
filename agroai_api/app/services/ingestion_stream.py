from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings


_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StreamedUpload:
    path: str
    filename: str
    size_bytes: int
    sha256: str
    content_type: str | None


def _safe_component(value: str, fallback: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("_", (value or "").strip()).strip("._")
    return cleaned[:180] or fallback


def max_upload_bytes() -> int:
    raw = os.getenv("CONNECTOR_MAX_UPLOAD_BYTES")
    if raw:
        try:
            return max(1024, int(raw))
        except ValueError:
            pass
    return int(getattr(settings, "CONNECTOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024))


def stream_chunk_bytes() -> int:
    raw = os.getenv("CONNECTOR_STREAM_CHUNK_BYTES")
    if raw:
        try:
            return min(max(64 * 1024, int(raw)), 8 * 1024 * 1024)
        except ValueError:
            pass
    return int(getattr(settings, "CONNECTOR_STREAM_CHUNK_BYTES", 1024 * 1024))


async def stream_upload_to_spool(
    upload: UploadFile,
    *,
    tenant_id: str,
    connection_id: str,
) -> StreamedUpload:
    base = Path(settings.CONNECTOR_UPLOAD_DIR)
    tenant = _safe_component(tenant_id, "tenant")
    connection = _safe_component(connection_id, "connection")
    filename = _safe_component(upload.filename or "upload", "upload")
    directory = base / tenant / connection
    directory.mkdir(parents=True, exist_ok=True)

    final_path = directory / f"{uuid.uuid4().hex}-{filename}"
    partial_path = final_path.with_suffix(final_path.suffix + ".part")
    digest = hashlib.sha256()
    total = 0
    limit = max_upload_bytes()
    chunk_size = stream_chunk_bytes()

    try:
        with partial_path.open("xb") as handle:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "error": "upload_too_large",
                            "max_bytes": limit,
                            "received_bytes": total,
                        },
                    )
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial_path, final_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    return StreamedUpload(
        path=str(final_path),
        filename=filename,
        size_bytes=total,
        sha256=digest.hexdigest(),
        content_type=upload.content_type,
    )


def read_spooled_bytes(receipt: StreamedUpload) -> bytes:
    path = Path(receipt.path)
    if not path.is_file():
        raise FileNotFoundError(receipt.path)
    size = path.stat().st_size
    if size != receipt.size_bytes:
        raise RuntimeError("spooled upload size changed before ingestion")
    if size > max_upload_bytes():
        raise RuntimeError("spooled upload exceeds configured ingestion bound")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != receipt.sha256:
        raise RuntimeError("spooled upload checksum mismatch")
    return data
