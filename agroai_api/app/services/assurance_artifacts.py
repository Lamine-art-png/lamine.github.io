"""Secure storage and delivery helpers for modern Assurance proof packages.

Production packages use the existing GeneratedArtifact catalog and configured
R2/S3-compatible object store. Development and tests may keep bytes encoded in
GeneratedArtifact.body_text so callers still exercise authenticated server-side
download instead of receiving large inline API payloads.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.models.operational_records import GeneratedArtifact
from app.services.object_storage import get_object_store, object_storage_configured


logger = logging.getLogger(__name__)
PRODUCTION_ENVS = {"production", "staging"}
MAX_ASSURANCE_PACKAGE_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class StagedAssuranceArtifact:
    artifact: GeneratedArtifact
    object_uri: str | None
    object_connection_id: str | None

    def promote(self) -> None:
        if not self.object_uri or not self.object_connection_id:
            return
        try:
            get_object_store().promote(
                self.object_uri,
                tenant_id=self.artifact.tenant_id,
                connection_id=self.object_connection_id,
            )
        except Exception:  # noqa: BLE001 - pending marker makes retry/cleanup safe
            logger.exception("Assurance artifact promotion marker cleanup failed")


def _production_environment() -> bool:
    return str(getattr(settings, "APP_ENV", "development") or "").strip().lower() in PRODUCTION_ENVS


def stage_assurance_artifact(
    *,
    artifact_id: str,
    organization_id: str,
    workspace_id: str,
    title: str,
    filename: str,
    pdf_bytes: bytes,
    metadata: dict[str, Any],
) -> StagedAssuranceArtifact:
    """Stage immutable PDF bytes and return the catalog row to persist.

    Object-store registration uses its existing pending-registration marker.
    The caller must commit the GeneratedArtifact reference and then call
    ``promote``. A failed database commit therefore leaves a recoverable object
    marker rather than an untracked durable object.
    """

    if not pdf_bytes or len(pdf_bytes) > MAX_ASSURANCE_PACKAGE_BYTES:
        raise RuntimeError("Assurance package size is outside the permitted range")
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    object_uri: str | None = None
    connection_id: str | None = None
    body_text: str | None = None
    storage_backend: str

    if object_storage_configured():
        connection_id = f"assurance-package-{artifact_id}"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="agroai-assurance-", suffix=".pdf", delete=False) as handle:
                handle.write(pdf_bytes)
                temp_path = Path(handle.name)
            stored = get_object_store().put_path(
                temp_path,
                tenant_id=organization_id,
                connection_id=connection_id,
                filename=filename,
                content_type="application/pdf",
                expected_sha256=checksum,
                expected_size=len(pdf_bytes),
                pending_registration=True,
            )
            object_uri = stored.uri
            storage_backend = "object_storage"
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    else:
        if _production_environment():
            raise RuntimeError("Durable object storage is required for production Assurance packages")
        body_text = base64.b64encode(pdf_bytes).decode("ascii")
        storage_backend = "generated_artifact_database_fallback"

    artifact = GeneratedArtifact(
        id=artifact_id,
        tenant_id=organization_id,
        workspace_id=workspace_id,
        artifact_type="assurance_proof_package",
        title=title,
        filename=filename,
        content_type="application/pdf",
        storage_path=object_uri,
        body_text=body_text,
        metadata_json={
            **metadata,
            "checksum_sha256": checksum,
            "size_bytes": len(pdf_bytes),
            "storage_backend": storage_backend,
            "storage_encoding": "base64" if body_text is not None else None,
            "object_connection_id": connection_id,
        },
    )
    return StagedAssuranceArtifact(artifact, object_uri, connection_id)


def assurance_artifact_content(
    artifact: GeneratedArtifact,
    *,
    organization_id: str,
    workspace_id: str,
) -> tuple[bytes | Iterable[bytes], int, str]:
    """Return authorized content, size, and filename for HTTP delivery."""

    if (
        artifact.tenant_id != organization_id
        or artifact.workspace_id != workspace_id
        or artifact.artifact_type != "assurance_proof_package"
    ):
        raise KeyError("Assurance artifact not found")
    metadata = artifact.metadata_json or {}
    expected_checksum = str(metadata.get("checksum_sha256") or "")
    size_bytes = int(metadata.get("size_bytes") or 0)
    if artifact.storage_path:
        connection_id = str(metadata.get("object_connection_id") or "")
        if not connection_id:
            raise RuntimeError("Assurance artifact storage metadata is incomplete")
        iterator = get_object_store().stream_object(
            artifact.storage_path,
            tenant_id=organization_id,
            connection_id=connection_id,
        )
        return iterator, size_bytes, artifact.filename
    if not artifact.body_text or metadata.get("storage_encoding") != "base64":
        raise KeyError("Assurance artifact content not found")
    content = base64.b64decode(artifact.body_text, validate=True)
    if len(content) != size_bytes or hashlib.sha256(content).hexdigest() != expected_checksum:
        raise RuntimeError("Assurance artifact integrity check failed")
    return content, size_bytes, artifact.filename
