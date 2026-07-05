import asyncio
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(data))


def test_stream_upload_writes_file_with_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CONNECTOR_MAX_UPLOAD_BYTES", "1048576")
    monkeypatch.setenv("CONNECTOR_STREAM_CHUNK_BYTES", "65536")
    payload = b"timestamp,value\n" + b"2026-07-05,1\n" * 5000

    receipt = asyncio.run(
        stream_upload_to_spool(
            _upload("telemetry.csv", payload),
            tenant_id="tenant-1",
            connection_id="connection-1",
        )
    )

    assert receipt.size_bytes == len(payload)
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()
    assert Path(receipt.path).is_file()
    assert read_spooled_bytes(receipt) == payload


def test_stream_upload_rejects_oversize_and_cleans_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CONNECTOR_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("CONNECTOR_STREAM_CHUNK_BYTES", "65536")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            stream_upload_to_spool(
                _upload("large.csv", b"x" * 2048),
                tenant_id="tenant-1",
                connection_id="connection-1",
            )
        )

    assert exc.value.status_code == 413
    assert not list(tmp_path.rglob("*.part"))
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_checksum_change_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CONNECTOR_MAX_UPLOAD_BYTES", "1048576")
    receipt = asyncio.run(
        stream_upload_to_spool(
            _upload("evidence.csv", b"a,b\n1,2\n"),
            tenant_id="tenant-1",
            connection_id="connection-1",
        )
    )
    Path(receipt.path).write_bytes(b"changed")

    with pytest.raises(RuntimeError):
        read_spooled_bytes(receipt)
