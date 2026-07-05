from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from app.core.config import settings


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StoredObject:
    uri: str
    key: str
    size_bytes: int
    sha256: str
    content_type: str | None


def _safe_component(value: str, *, fallback: str) -> str:
    cleaned = _SAFE.sub("_", value or "").strip("._")
    return (cleaned[:120] or fallback)


def _s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


class S3ObjectStore:
    def __init__(self, *, bucket: str, prefix: str = "agroai", client: Any | None = None):
        if not bucket:
            raise RuntimeError("CONNECTOR_OBJECT_BUCKET is required for S3 object storage")
        self.bucket = bucket
        self.prefix = prefix.strip("/") or "agroai"
        self.client = client or boto3.client(
            "s3",
            endpoint_url=os.getenv("CONNECTOR_OBJECT_ENDPOINT_URL", "").strip() or None,
            region_name=os.getenv("CONNECTOR_OBJECT_REGION", "us-east-1").strip() or "us-east-1",
            config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"}),
        )

    def _key(self, *, tenant_id: str, connection_id: str, filename: str) -> str:
        now = datetime.utcnow()
        return "/".join(
            [
                self.prefix,
                "tenants",
                _safe_component(tenant_id, fallback="tenant"),
                "connectors",
                _safe_component(connection_id, fallback="connection"),
                "raw",
                now.strftime("%Y"),
                now.strftime("%m"),
                now.strftime("%d"),
                f"{uuid.uuid4().hex}-{_safe_component(filename, fallback='upload')}",
            ]
        )

    def put_path(
        self,
        path: str | Path,
        *,
        tenant_id: str,
        connection_id: str,
        filename: str,
        content_type: str | None,
        expected_sha256: str,
        expected_size: int,
    ) -> StoredObject:
        source = Path(path)
        if not source.is_file():
            raise RuntimeError("spooled connector object is unavailable")
        if source.stat().st_size != expected_size:
            raise RuntimeError("spooled connector object size changed before durable upload")
        key = self._key(tenant_id=tenant_id, connection_id=connection_id, filename=filename)
        extra: dict[str, Any] = {
            "Metadata": {
                "sha256": expected_sha256,
                "connection-id": _safe_component(connection_id, fallback="connection"),
            }
        }
        if content_type:
            extra["ContentType"] = content_type
        with source.open("rb") as handle:
            self.client.upload_fileobj(handle, self.bucket, key, ExtraArgs=extra)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        size = int(head.get("ContentLength") or -1)
        metadata = head.get("Metadata") or {}
        if size != expected_size or metadata.get("sha256") != expected_sha256:
            try:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            finally:
                raise RuntimeError("durable connector object verification failed")
        return StoredObject(
            uri=_s3_uri(self.bucket, key),
            key=key,
            size_bytes=size,
            sha256=expected_sha256,
            content_type=content_type,
        )

    def read_bytes(self, uri: str, *, max_bytes: int) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or parsed.netloc != self.bucket:
            raise ValueError("object URI is outside the configured connector bucket")
        key = parsed.path.lstrip("/")
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        length = int(response.get("ContentLength") or 0)
        if length > max_bytes:
            raise RuntimeError("connector object exceeds worker read limit")
        body: BinaryIO = response["Body"]
        data = body.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise RuntimeError("connector object exceeded worker read limit while streaming")
        metadata = response.get("Metadata") or {}
        expected = metadata.get("sha256")
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("connector object checksum mismatch")
        return data

    def delete(self, uri: str) -> None:
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or parsed.netloc != self.bucket:
            raise ValueError("object URI is outside the configured connector bucket")
        self.client.delete_object(Bucket=self.bucket, Key=parsed.path.lstrip("/"))


def object_storage_configured() -> bool:
    backend = getattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled").strip().lower()
    return backend in {"s3", "r2", "s3_compatible"} and bool(os.getenv("CONNECTOR_OBJECT_BUCKET", "").strip())


def get_object_store(*, client: Any | None = None) -> S3ObjectStore:
    backend = getattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled").strip().lower()
    if backend not in {"s3", "r2", "s3_compatible"}:
        raise RuntimeError("durable connector object storage is not configured")
    return S3ObjectStore(
        bucket=os.getenv("CONNECTOR_OBJECT_BUCKET", "").strip(),
        prefix=os.getenv("CONNECTOR_OBJECT_PREFIX", "agroai").strip() or "agroai",
        client=client,
    )
