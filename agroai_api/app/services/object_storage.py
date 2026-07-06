from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

from app.core.config import settings


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class StoredObject:
    uri: str
    key: str
    size_bytes: int
    sha256: str
    content_type: str | None


def _safe_component(value: str, *, fallback: str) -> str:
    cleaned = _SAFE.sub("_", value or "").strip("._")
    return cleaned[:120] or fallback


def _scope_component(value: str, *, fallback: str) -> str:
    raw = (value or "").strip() or fallback
    readable = _safe_component(raw, fallback=fallback)[:48]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{readable}-{digest}"


def _s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_default_s3_client():
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("S3/R2 connector object storage is configured but boto3 is unavailable") from exc

    endpoint_url = getattr(settings, "CONNECTOR_OBJECT_ENDPOINT_URL", "").strip() or None
    region_name = getattr(settings, "CONNECTOR_OBJECT_REGION", "auto").strip() or "auto"
    r2_access_key = getattr(settings, "CLOUDFLARE_R2_ACCESS_KEY_ID", "").strip()
    r2_secret_key = getattr(settings, "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "").strip()
    if bool(r2_access_key) != bool(r2_secret_key):
        raise RuntimeError("Both Cloudflare R2 access key fields must be configured together")

    client_kwargs: dict[str, Any] = {
        "endpoint_url": endpoint_url,
        "region_name": region_name,
        "config": Config(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 4, "mode": "standard"},
        ),
    }
    if r2_access_key and r2_secret_key:
        client_kwargs["aws_access_key_id"] = r2_access_key
        client_kwargs["aws_secret_access_key"] = r2_secret_key
    return boto3.client("s3", **client_kwargs)


class S3ObjectStore:
    def __init__(self, *, bucket: str, prefix: str = "agroai", client: Any | None = None):
        if not bucket:
            raise RuntimeError("CONNECTOR_OBJECT_BUCKET is required for S3-compatible object storage")
        self.bucket = bucket
        self.prefix = prefix.strip("/") or "agroai"
        self.client = client or _build_default_s3_client()

    def _namespace(self, *, tenant_id: str, connection_id: str) -> str:
        return "/".join([
            self.prefix,
            "tenants",
            _scope_component(tenant_id, fallback="tenant"),
            "connectors",
            _scope_component(connection_id, fallback="connection"),
        ]) + "/"

    def _key(self, *, tenant_id: str, connection_id: str, filename: str) -> str:
        now = datetime.utcnow()
        return "/".join([
            self._namespace(tenant_id=tenant_id, connection_id=connection_id).rstrip("/"),
            "raw",
            now.strftime("%Y"),
            now.strftime("%m"),
            now.strftime("%d"),
            f"{uuid.uuid4().hex}-{_safe_component(filename, fallback='upload')}",
        ])

    def _validated_key(
        self,
        uri: str,
        *,
        tenant_id: str | None = None,
        connection_id: str | None = None,
    ) -> str:
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or parsed.netloc != self.bucket:
            raise ValueError("object URI is outside the configured connector bucket")
        key = parsed.path.lstrip("/")
        prefix = self.prefix.rstrip("/") + "/"
        if not key.startswith(prefix):
            raise ValueError("object URI is outside the configured connector prefix")
        if (tenant_id is None) != (connection_id is None):
            raise ValueError("tenant_id and connection_id must be supplied together")
        if tenant_id is not None and connection_id is not None:
            namespace = self._namespace(tenant_id=tenant_id, connection_id=connection_id)
            if not key.startswith(namespace):
                raise ValueError("object URI is outside the connector tenant namespace")
        return key

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
        expected_sha256 = expected_sha256.strip().lower()
        if not _SHA256.fullmatch(expected_sha256):
            raise RuntimeError("expected connector checksum is invalid")
        if _file_sha256(source) != expected_sha256:
            raise RuntimeError("spooled connector object checksum changed before durable upload")

        tenant_scope = _scope_component(tenant_id, fallback="tenant")
        connection_scope = _scope_component(connection_id, fallback="connection")
        key = self._key(tenant_id=tenant_id, connection_id=connection_id, filename=filename)
        extra: dict[str, Any] = {
            "Metadata": {
                "sha256": expected_sha256,
                "tenant-scope": tenant_scope,
                "connection-scope": connection_scope,
            }
        }
        if content_type:
            extra["ContentType"] = content_type
        with source.open("rb") as handle:
            self.client.upload_fileobj(handle, self.bucket, key, ExtraArgs=extra)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        size = int(head.get("ContentLength") or -1)
        metadata = head.get("Metadata") or {}
        verified = (
            size == expected_size
            and metadata.get("sha256") == expected_sha256
            and metadata.get("tenant-scope") == tenant_scope
            and metadata.get("connection-scope") == connection_scope
        )
        if not verified:
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

    def read_bytes(
        self,
        uri: str,
        *,
        max_bytes: int,
        tenant_id: str | None = None,
        connection_id: str | None = None,
    ) -> bytes:
        key = self._validated_key(uri, tenant_id=tenant_id, connection_id=connection_id)
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        length = int(response.get("ContentLength") or 0)
        if length > max_bytes:
            raise RuntimeError("connector object exceeds worker read limit")
        body: BinaryIO = response["Body"]
        data = body.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise RuntimeError("connector object exceeded worker read limit while streaming")
        metadata = response.get("Metadata") or {}
        expected = str(metadata.get("sha256") or "").strip().lower()
        if not _SHA256.fullmatch(expected):
            raise RuntimeError("connector object checksum metadata is unavailable")
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("connector object checksum mismatch")
        if tenant_id is not None:
            expected_tenant_scope = _scope_component(tenant_id, fallback="tenant")
            if metadata.get("tenant-scope") != expected_tenant_scope:
                raise RuntimeError("connector object tenant metadata mismatch")
        if connection_id is not None:
            expected_connection_scope = _scope_component(connection_id, fallback="connection")
            if metadata.get("connection-scope") != expected_connection_scope:
                raise RuntimeError("connector object connection metadata mismatch")
        return data

    def delete(
        self,
        uri: str,
        *,
        tenant_id: str | None = None,
        connection_id: str | None = None,
    ) -> None:
        key = self._validated_key(uri, tenant_id=tenant_id, connection_id=connection_id)
        self.client.delete_object(Bucket=self.bucket, Key=key)


def object_storage_configured() -> bool:
    backend = getattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled").strip().lower()
    return backend in {"s3", "r2", "s3_compatible"} and bool(
        getattr(settings, "CONNECTOR_OBJECT_BUCKET", "").strip()
    )


def get_object_store(*, client: Any | None = None) -> S3ObjectStore:
    backend = getattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled").strip().lower()
    if backend not in {"s3", "r2", "s3_compatible"}:
        raise RuntimeError("durable connector object storage is not configured")
    return S3ObjectStore(
        bucket=getattr(settings, "CONNECTOR_OBJECT_BUCKET", "").strip(),
        prefix=getattr(settings, "CONNECTOR_OBJECT_PREFIX", "agroai").strip() or "agroai",
        client=client,
    )
