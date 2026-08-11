from __future__ import annotations

import hashlib
import json
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

    # ------------------------------------------------------------------ #
    # Pending-registration staging
    #
    # A durable upload whose database registration may still fail leaves a
    # small marker object under ``<prefix>/pending-registration/``. The marker
    # lives in the object store itself, so it survives total database
    # unavailability. Successful registration promotes the object by deleting
    # the marker; a periodic reconciler removes stale unpromoted objects.
    # ------------------------------------------------------------------ #

    def _pending_prefix(self) -> str:
        return f"{self.prefix}/pending-registration/"

    def _pending_marker_key(self, object_key: str) -> str:
        return self._pending_prefix() + hashlib.sha256(object_key.encode("utf-8")).hexdigest() + ".json"

    def stage_pending_registration(self, object_key: str) -> str:
        """Durably record that ``object_key`` awaits database registration."""
        marker_key = self._pending_marker_key(object_key)
        body = json.dumps({
            "key": object_key,
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
        }).encode("utf-8")
        self.client.put_object(Bucket=self.bucket, Key=marker_key, Body=body,
                               ContentType="application/json")
        return marker_key

    def promote(self, uri: str, *, tenant_id: str | None = None, connection_id: str | None = None) -> None:
        """Clear the pending-registration marker after a durable DB commit.

        Idempotent; a missing marker is a no-op. Failure is safe: the
        reconciler sees the live database reference and only clears the marker.
        """
        key = self._validated_key(uri, tenant_id=tenant_id, connection_id=connection_id)
        self.client.delete_object(Bucket=self.bucket, Key=self._pending_marker_key(key))

    def list_pending_registrations(self, *, limit: int = 1000) -> list[dict]:
        """Enumerate pending-registration markers with their object keys."""
        entries: list[dict] = []
        token: str | None = None
        prefix = self._pending_prefix()
        while len(entries) < limit:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix,
                                      "MaxKeys": min(limit - len(entries), 1000)}
            if token:
                kwargs["ContinuationToken"] = token
            response = self.client.list_objects_v2(**kwargs)
            for item in response.get("Contents") or []:
                marker_key = item.get("Key")
                if not marker_key:
                    continue
                try:
                    body = self.client.get_object(Bucket=self.bucket, Key=marker_key)["Body"].read(64 * 1024)
                    payload = json.loads(body.decode("utf-8"))
                    object_key = str(payload.get("key") or "")
                    uploaded_raw = str(payload.get("uploaded_at") or "").rstrip("Z")
                    uploaded_at = datetime.fromisoformat(uploaded_raw) if uploaded_raw else None
                except Exception:  # noqa: BLE001 - malformed marker: surface for cleanup
                    object_key, uploaded_at = "", None
                if not object_key.startswith(self.prefix.rstrip("/") + "/"):
                    object_key = ""  # never act outside the configured prefix
                entries.append({
                    "marker_key": marker_key,
                    "key": object_key or None,
                    "uri": _s3_uri(self.bucket, object_key) if object_key else None,
                    "uploaded_at": uploaded_at,
                })
            token = response.get("NextContinuationToken")
            if not token:
                break
        return entries

    def clear_pending_marker(self, marker_key: str) -> None:
        if not marker_key.startswith(self._pending_prefix()):
            raise ValueError("marker key is outside the pending-registration prefix")
        self.client.delete_object(Bucket=self.bucket, Key=marker_key)

    def delete_unregistered_object(self, object_key: str) -> None:
        """Delete a staged object by key (reconciler only; prefix-validated)."""
        if not object_key.startswith(self.prefix.rstrip("/") + "/"):
            raise ValueError("object key is outside the configured prefix")
        self.client.delete_object(Bucket=self.bucket, Key=object_key)

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
        pending_registration: bool = False,
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
        if pending_registration:
            # Marker precedes the object: a crash at any later point leaves a
            # store-resident record the reconciler can act on without the DB.
            self.stage_pending_registration(key)
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

    def create_presigned_upload(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        filename: str,
        content_type: str,
        expected_sha256: str,
        expires_seconds: int = 900,
    ) -> tuple[str, str, dict[str, str]]:
        """Create a scoped direct-upload URL without exposing storage credentials."""

        expected_sha256 = expected_sha256.strip().lower()
        if not _SHA256.fullmatch(expected_sha256):
            raise ValueError("expected upload checksum is invalid")
        key = self._key(tenant_id=tenant_id, connection_id=connection_id, filename=filename)
        metadata = {
            "sha256": expected_sha256,
            "tenant-scope": _scope_component(tenant_id, fallback="tenant"),
            "connection-scope": _scope_component(connection_id, fallback="connection"),
        }
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "Metadata": metadata,
            },
            ExpiresIn=max(60, min(int(expires_seconds), 3600)),
            HttpMethod="PUT",
        )
        return url, _s3_uri(self.bucket, key), {f"x-amz-meta-{name}": value for name, value in metadata.items()}

    def inspect(
        self,
        uri: str,
        *,
        tenant_id: str,
        connection_id: str,
        max_bytes: int,
        expected_sha256: str | None = None,
    ) -> StoredObject:
        """Verify scoped object metadata without returning customer content."""

        key = self._validated_key(uri, tenant_id=tenant_id, connection_id=connection_id)
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        size = int(response.get("ContentLength") or -1)
        if size < 0 or size > max_bytes:
            raise RuntimeError("object size is outside the permitted range")
        metadata = response.get("Metadata") or {}
        sha256 = str(metadata.get("sha256") or "").strip().lower()
        if not _SHA256.fullmatch(sha256):
            raise RuntimeError("object checksum metadata is unavailable")
        if expected_sha256 is not None and sha256 != expected_sha256.strip().lower():
            raise RuntimeError("object checksum metadata does not match the request")
        if metadata.get("tenant-scope") != _scope_component(tenant_id, fallback="tenant"):
            raise RuntimeError("object tenant metadata mismatch")
        if metadata.get("connection-scope") != _scope_component(connection_id, fallback="connection"):
            raise RuntimeError("object purpose metadata mismatch")
        return StoredObject(
            uri=uri,
            key=key,
            size_bytes=size,
            sha256=sha256,
            content_type=response.get("ContentType"),
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

    def stat(self, uri: str, *, tenant_id: str | None = None, connection_id: str | None = None) -> tuple[int, str | None]:
        """Return (size_bytes, content_type) for an authorized object."""
        key = self._validated_key(uri, tenant_id=tenant_id, connection_id=connection_id)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        return int(head.get("ContentLength") or 0), head.get("ContentType")

    def stream_object(
        self,
        uri: str,
        *,
        tenant_id: str | None = None,
        connection_id: str | None = None,
        byte_range: tuple[int, int] | None = None,
        chunk_size: int = 256 * 1024,
    ):
        """Stream an authorized object without buffering it fully in memory.

        Supports HTTP range requests. Tenant/connection namespace is validated
        against the key before any bytes are read; integrity of the stored object
        was verified at upload time.
        """
        key = self._validated_key(uri, tenant_id=tenant_id, connection_id=connection_id)
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if byte_range is not None:
            kwargs["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
        response = self.client.get_object(**kwargs)
        body = response["Body"]

        def _iterator():
            # The finally block guarantees the S3/R2 body (and its pooled HTTP
            # connection) is released on normal completion, on error, and on
            # client cancellation (GeneratorExit via StreamingResponse close).
            try:
                while True:
                    chunk = body.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    body.close()
                except Exception:  # noqa: BLE001 - releasing is best-effort
                    pass

        return _iterator()


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
