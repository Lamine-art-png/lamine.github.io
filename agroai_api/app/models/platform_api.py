from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


def new_platform_id() -> str:
    return str(uuid.uuid4())


class ApiProject(Base):
    __tablename__ = "api_projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", "environment", name="uq_api_project_org_slug_env"),
        Index("ix_api_project_org_env_status", "organization_id", "environment", "status"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    environment = Column(String, nullable=False, index=True)  # test | live
    status = Column(String, default="disabled", nullable=False, index=True)
    default_rate_limit_policy = Column(JSON, nullable=False, default=dict)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ApiServiceAccount(Base):
    __tablename__ = "api_service_accounts"
    __table_args__ = (
        UniqueConstraint("api_project_id", "name", name="uq_api_service_account_project_name"),
        Index("ix_api_service_account_org_project_status", "organization_id", "api_project_id", "status"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="active", nullable=False, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    resource_restrictions_json = Column(JSON, nullable=False, default=dict)
    provider_restrictions_json = Column(JSON, nullable=False, default=dict)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    disabled_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    disabled_at = Column(DateTime, nullable=True)


class PlatformApiKey(Base):
    __tablename__ = "platform_api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_platform_api_key_hash"),
        Index("ix_platform_api_key_fingerprint", "fingerprint"),
        Index("ix_platform_api_key_lookup", "key_prefix", "status"),
        Index("ix_platform_api_key_org_project_status", "organization_id", "api_project_id", "status"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    service_account_id = Column(String, ForeignKey("api_service_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String, nullable=False)
    environment = Column(String, nullable=False, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    status = Column(String, default="active", nullable=False, index=True)
    key_hash = Column(String(64), nullable=False)
    key_prefix = Column(String(24), nullable=False)
    fingerprint = Column(String(32), nullable=False)
    cidr_allowlist_json = Column(JSON, nullable=False, default=list)
    provider_restrictions_json = Column(JSON, nullable=False, default=dict)
    resource_restrictions_json = Column(JSON, nullable=False, default=dict)
    expires_at = Column(DateTime, nullable=True, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    rotate_after_key_id = Column(String, nullable=True, index=True)
    overlap_expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    last_used_request_id = Column(String, nullable=True)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformApiUsageEvent(Base):
    __tablename__ = "platform_api_usage_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "api_project_id", "idempotency_key", name="uq_platform_usage_idempotency"),
        Index("ix_platform_usage_org_project_time", "organization_id", "api_project_id", "created_at"),
        Index("ix_platform_usage_key_time", "api_key_id", "created_at"),
        Index("ix_platform_usage_metric_time", "metric", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    service_account_id = Column(String, ForeignKey("api_service_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    api_key_id = Column(String, ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    environment = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    metric = Column(String, nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    cost_units = Column(Integer, default=1, nullable=False)
    operation = Column(String, nullable=False, index=True)
    route = Column(String, nullable=True)
    method = Column(String, nullable=True)
    request_id = Column(String, nullable=True, index=True)
    idempotency_key = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class PlatformIdempotencyRecord(Base):
    __tablename__ = "platform_idempotency_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "api_project_id", "operation", "idempotency_key", name="uq_platform_idempotency_scope"),
        Index("ix_platform_idempotency_expires", "expires_at"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    operation = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String, default="in_progress", nullable=False, index=True)
    response_status = Column(Integer, nullable=True)
    response_json = Column(JSON, nullable=True)
    operation_id = Column(String, nullable=True, index=True)
    first_request_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class ProviderExternalIdentityMap(Base):
    __tablename__ = "provider_external_identity_maps"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "connection_id",
            "external_object_type",
            "external_object_id",
            name="uq_provider_external_identity",
        ),
        Index("ix_provider_identity_internal", "organization_id", "internal_object_type", "internal_object_id"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    provider = Column(String, nullable=False, index=True)
    connection_id = Column(String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    external_object_type = Column(String, nullable=False)
    external_object_id = Column(String, nullable=False)
    internal_object_type = Column(String, nullable=False, index=True)
    internal_object_id = Column(String, nullable=False, index=True)
    provider_version = Column(String, nullable=True)
    etag = Column(String, nullable=True)
    tombstoned = Column(Boolean, default=False, nullable=False, index=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_synchronized_at = Column(DateTime, nullable=True)


class ProviderCapabilityRecord(Base):
    __tablename__ = "provider_capability_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "connection_id", "capability", name="uq_provider_capability_connection"),
        Index("ix_provider_capability_status", "provider", "status"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    connection_id = Column(String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=True, index=True)
    capability = Column(String, nullable=False)
    status = Column(String, default="awaiting_partner_contract", nullable=False, index=True)
    source = Column(String, default="adapter_contract", nullable=False)
    diagnostics_json = Column(JSON, nullable=False, default=dict)
    last_validated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformWebhookEndpoint(Base):
    __tablename__ = "platform_webhook_endpoints"
    __table_args__ = (
        Index("ix_platform_webhook_endpoint_project_status", "organization_id", "api_project_id", "status"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    subscribed_event_types = Column(JSON, nullable=False, default=list)
    status = Column(String, default="active", nullable=False, index=True)
    signing_secret_hash = Column(String(64), nullable=False)
    signing_secret_prefix = Column(String(24), nullable=False)
    signing_secret_version = Column(String, default="v1", nullable=False)
    signing_secret_key_version = Column(String, nullable=True)
    signing_secret_nonce_b64 = Column(Text, nullable=True)
    signing_secret_ciphertext_b64 = Column(Text, nullable=True)
    previous_secret_hash = Column(String(64), nullable=True)
    previous_secret_key_version = Column(String, nullable=True)
    previous_secret_nonce_b64 = Column(Text, nullable=True)
    previous_secret_ciphertext_b64 = Column(Text, nullable=True)
    previous_secret_expires_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    disabled_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class PlatformWebhookEvent(Base):
    __tablename__ = "platform_webhook_events"
    __table_args__ = (
        Index("ix_platform_webhook_event_project_time", "organization_id", "api_project_id", "created_at"),
        Index("ix_platform_webhook_event_type_time", "event_type", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    version = Column(String, default="2026-07-10", nullable=False)
    payload_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class PlatformWebhookDeliveryAttempt(Base):
    __tablename__ = "platform_webhook_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("event_id", "endpoint_id", "attempt_number", name="uq_platform_webhook_attempt"),
        Index("ix_platform_webhook_delivery_next_retry", "status", "next_retry_at"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    event_id = Column(String, ForeignKey("platform_webhook_events.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint_id = Column(String, ForeignKey("platform_webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    request_id = Column(String, nullable=True, index=True)
    status = Column(String, default="pending", nullable=False, index=True)
    response_status = Column(Integer, nullable=True)
    response_excerpt = Column(Text, nullable=True)
    error_classification = Column(String, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformWebhookOutbox(Base):
    __tablename__ = "platform_webhook_outbox"
    __table_args__ = (
        UniqueConstraint("event_id", "endpoint_id", name="uq_platform_webhook_outbox_event_endpoint"),
        Index("ix_platform_webhook_outbox_ready", "status", "next_attempt_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String, ForeignKey("platform_webhook_events.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint_id = Column(String, ForeignKey("platform_webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, default="pending", nullable=False, index=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    next_attempt_at = Column(DateTime, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformWebhookAuditEvent(Base):
    __tablename__ = "platform_webhook_audit_events"
    __table_args__ = (
        Index("ix_platform_webhook_audit_org_endpoint_time", "organization_id", "endpoint_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint_id = Column(String, ForeignKey("platform_webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    actor_type = Column(String, nullable=False)
    actor_id = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    details_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ActionSafetyConfiguration(Base):
    __tablename__ = "action_safety_configurations"
    __table_args__ = (
        UniqueConstraint("organization_id", "api_project_id", "connection_id", "resource_id", "command_type", name="uq_action_safety_scope"),
    )

    id = Column(String, primary_key=True, default=new_platform_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    connection_id = Column(String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=True, index=True)
    resource_id = Column(String, nullable=True, index=True)
    command_type = Column(String, default="*", nullable=False, index=True)
    disabled = Column(Boolean, default=True, nullable=False)
    reason = Column(Text, nullable=True)
    updated_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
