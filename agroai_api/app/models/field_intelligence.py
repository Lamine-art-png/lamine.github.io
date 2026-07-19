"""Field Intelligence domain models.

Voice-first / offline field capture that converts a raw observation into
durable, tenant-scoped operational data. This is a dedicated domain and does
not inflate ``operational_records`` or the field operating loop.

Design notes
------------
* String UUID primary keys, ``tenant_id`` -> organizations, ``workspace_id`` ->
  workspaces, mirroring :mod:`app.models.operational_records`.
* Binary media never lives in Postgres. Only authorized object references are
  stored on :class:`FieldObservationAsset`.
* Idempotency is a first-class column so an offline client can safely replay a
  capture. A canonical payload fingerprint distinguishes a benign replay from a
  conflicting reuse of the same key.
* Foreign keys are declared with deliberate delete behavior. There is no
  circular FK: a capture points at an observation by id only; the observation
  owns the unique FK back to its capture (one observation per capture).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


# Capture lifecycle mirrors the offline client state machine so the server and
# the browser agree on a single vocabulary.
CAPTURE_STATES = (
    "draft",
    "queued",
    "received",
    "processing",
    "completed",
    "failed",
    "conflict",
)

OBSERVATION_STATES = ("staged", "processing", "completed", "failed", "needs_review", "deleted")
ASSET_STATES = ("stored", "pending_deletion", "deleted")


class FieldCaptureSession(Base):
    """A single field capture as it moves from the client into durable storage.

    One session yields at most one :class:`FieldObservation`. The session owns
    the idempotency contract: the same ``idempotency_key`` must never create two
    observations, and reusing it with a different canonical payload is a
    conflict rather than a silent overwrite.
    """

    __tablename__ = "field_capture_sessions"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Stable client-generated identity + idempotency key survive offline replay.
    client_capture_id = Column(String, nullable=False, index=True)
    idempotency_key = Column(String(120), nullable=False, index=True)
    # Canonical fingerprint of the accepted payload; a replay with the same key
    # but a different fingerprint is rejected as an idempotency conflict.
    payload_fingerprint = Column(String(64), nullable=True)

    capture_source = Column(String, default="typed", nullable=False)  # voice | typed
    status = Column(String, default="received", nullable=False, index=True)

    note_text = Column(Text, nullable=True)
    transcript_preview = Column(Text, nullable=True)  # optional browser preview only

    field_id = Column(String, nullable=True, index=True)
    field_name = Column(String, nullable=True)
    block_id = Column(String, nullable=True)
    block_name = Column(String, nullable=True)
    crop = Column(String, nullable=True)
    event_type = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    assignee = Column(String, nullable=True)

    occurred_at = Column(DateTime, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_accuracy_m = Column(Float, nullable=True)

    asset_manifest_json = Column(JSON, default=list, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    last_error = Column(Text, nullable=True)

    # Pointer only (no FK) so there is no circular constraint with observations.
    observation_id = Column(String, nullable=True, index=True)

    client_created_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # Idempotent replay: one accepted capture per (tenant, idempotency_key).
        Index("uq_field_capture_idempotency", "tenant_id", "idempotency_key", unique=True),
        Index("uq_field_capture_client_id", "tenant_id", "client_capture_id", unique=True),
        Index("ix_field_capture_status", "tenant_id", "status", "created_at"),
    )


class FieldObservation(Base):
    """The durable, structured operational record derived from a capture."""

    __tablename__ = "field_observations"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Unique FK enforces exactly one observation per capture session.
    capture_session_id = Column(
        String,
        ForeignKey("field_capture_sessions.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )

    field_id = Column(String, nullable=True, index=True)
    field_name = Column(String, nullable=True)
    block_id = Column(String, nullable=True, index=True)
    block_name = Column(String, nullable=True)
    crop = Column(String, nullable=True)
    event_type = Column(String, nullable=True, index=True)
    severity = Column(String, nullable=True, index=True)
    status = Column(String, default="staged", nullable=False, index=True)
    processing_error = Column(Text, nullable=True)

    occurred_at = Column(DateTime, nullable=True, index=True)
    observed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_accuracy_m = Column(Float, nullable=True)

    # Original transcript and any human-corrected transcript are kept separate.
    transcript = Column(Text, nullable=True)
    corrected_transcript = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)

    structured_json = Column(JSON, default=dict, nullable=False)
    extraction_schema_version = Column(String, nullable=True)
    confidence = Column(Float, default=0.0, nullable=False)
    uncertain_fields_json = Column(JSON, default=list, nullable=False)
    recommended_action = Column(Text, nullable=True)

    correlation_json = Column(JSON, default=dict, nullable=False)
    provenance_json = Column(JSON, default=dict, nullable=False)
    model_provider = Column(String, nullable=True)
    model_name = Column(String, nullable=True)

    task_ids_json = Column(JSON, default=list, nullable=False)
    evidence_ids_json = Column(JSON, default=list, nullable=False)
    audit_json = Column(JSON, default=list, nullable=False)

    search_text = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_field_obs_tenant_ws_time", "tenant_id", "workspace_id", "occurred_at"),
        Index("ix_field_obs_field_time", "tenant_id", "field_id", "occurred_at"),
        Index("ix_field_obs_status", "tenant_id", "status", "created_at"),
        Index("ix_field_obs_event_severity", "tenant_id", "event_type", "severity"),
    )


class FieldObservationAsset(Base):
    """Authorized object reference for a captured media asset.

    The binary lives in R2-compatible object storage; only the reference,
    checksum and validated content type live here. ``status`` transitions
    stored -> pending_deletion -> deleted as durable object deletion is
    scheduled and confirmed.
    """

    __tablename__ = "field_observation_assets"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    capture_session_id = Column(
        String, ForeignKey("field_capture_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    observation_id = Column(
        String, ForeignKey("field_observations.id", ondelete="CASCADE"), nullable=True, index=True
    )

    client_asset_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)  # audio | photo | video | file
    content_type = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    storage_backend = Column(String, default="s3", nullable=False)
    object_ref = Column(String, nullable=True)  # never a public URL
    content_sha256 = Column(String(64), nullable=True, index=True)
    size_bytes = Column(BigInteger, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    status = Column(String, default="stored", nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    object_deleted_at = Column(DateTime, nullable=True)
    delete_attempts = Column(Integer, default=0, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        # Safe-retry dedupe: same client asset in the same capture is stored once.
        UniqueConstraint("tenant_id", "capture_session_id", "client_asset_id", name="uq_field_asset_identity"),
        Index("ix_field_asset_checksum", "tenant_id", "content_sha256"),
        Index("ix_field_asset_observation", "tenant_id", "observation_id"),
        Index("ix_field_asset_status", "tenant_id", "status"),
    )


class FieldObservationProcessingRun(Base):
    """One provenance-bearing processing stage (transcription/extraction/correlation)."""

    __tablename__ = "field_observation_processing_runs"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    observation_id = Column(
        String, ForeignKey("field_observations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capture_session_id = Column(String, nullable=True, index=True)

    stage = Column(String, nullable=False, index=True)  # transcription | extraction | correlation | pipeline
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    language = Column(String, nullable=True)
    status = Column(String, default="completed", nullable=False, index=True)
    latency_ms = Column(Integer, nullable=True)
    attempt_count = Column(Integer, default=1, nullable=False)
    error = Column(Text, nullable=True)
    input_json = Column(JSON, default=dict, nullable=False)
    output_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_field_processing_obs_stage", "observation_id", "stage"),
        Index("ix_field_processing_status", "tenant_id", "status", "created_at"),
    )


class FieldStorageReservation(Base):
    """Durable, TTL-bounded reservation of tenant media-storage quota.

    A reservation is committed *before* a new physical object is created so
    concurrent uploads cannot overshoot the plan quota, and is atomically
    replaced by the registered asset row in the same transaction. A crashed
    upload leaks nothing: the reservation expires and is purged.
    """

    __tablename__ = "field_storage_reservations"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    capture_session_id = Column(String, nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_field_storage_res_tenant", "tenant_id", "expires_at"),
    )


class FieldObservationAuditEvent(Base):
    """Append-only audit trail for field intelligence.

    This table is the authoritative, insert-only record of what happened to a
    capture/observation/asset. ``FieldObservation.audit_json`` is only a
    presentation cache; rows here are never mutated or deleted.
    """

    __tablename__ = "field_observation_audit_events"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, nullable=True, index=True)
    observation_id = Column(String, nullable=True, index=True)
    capture_session_id = Column(String, nullable=True, index=True)
    asset_id = Column(String, nullable=True)
    action = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=True)
    actor_type = Column(String, default="user", nullable=False)  # user | system
    details_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_field_audit_tenant_time", "tenant_id", "created_at"),
        Index("ix_field_audit_observation", "observation_id", "created_at"),
    )
