"""Add Platform API private beta foundation tables.

Revision ID: 018_platform_api_private_beta
Revises: 017_outreach_machine
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "018_platform_api_private_beta"
down_revision = "017_outreach_machine"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("api_projects"):
        op.create_table(
            "api_projects",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("environment", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="disabled"),
            sa.Column("default_rate_limit_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "slug", "environment", name="uq_api_project_org_slug_env"),
        )
    _create_index("ix_api_project_org_env_status", "api_projects", ["organization_id", "environment", "status"])
    _create_index("ix_api_projects_organization_id", "api_projects", ["organization_id"])
    _create_index("ix_api_projects_workspace_id", "api_projects", ["workspace_id"])

    if not _has_table("api_service_accounts"):
        op.create_table(
            "api_service_accounts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("resource_restrictions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("provider_restrictions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("disabled_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("disabled_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("api_project_id", "name", name="uq_api_service_account_project_name"),
        )
    _create_index("ix_api_service_account_org_project_status", "api_service_accounts", ["organization_id", "api_project_id", "status"])
    _create_index("ix_api_service_accounts_api_project_id", "api_service_accounts", ["api_project_id"])

    if not _has_table("platform_api_keys"):
        op.create_table(
            "platform_api_keys",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("service_account_id", sa.String(), sa.ForeignKey("api_service_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("environment", sa.String(), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("key_hash", sa.String(length=64), nullable=False),
            sa.Column("key_prefix", sa.String(length=24), nullable=False),
            sa.Column("fingerprint", sa.String(length=32), nullable=False),
            sa.Column("cidr_allowlist_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("provider_restrictions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("resource_restrictions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("rotate_after_key_id", sa.String(), nullable=True),
            sa.Column("overlap_expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_request_id", sa.String(), nullable=True),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("key_hash", name="uq_platform_api_key_hash"),
        )
    _create_index("ix_platform_api_key_lookup", "platform_api_keys", ["key_prefix", "status"])
    _create_index("ix_platform_api_key_fingerprint", "platform_api_keys", ["fingerprint"])
    _create_index("ix_platform_api_key_org_project_status", "platform_api_keys", ["organization_id", "api_project_id", "status"])

    if not _has_table("platform_api_usage_events"):
        op.create_table(
            "platform_api_usage_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("service_account_id", sa.String(), sa.ForeignKey("api_service_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("api_key_id", sa.String(), sa.ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
            sa.Column("environment", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("metric", sa.String(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("cost_units", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("route", sa.String(), nullable=True),
            sa.Column("method", sa.String(), nullable=True),
            sa.Column("request_id", sa.String(), nullable=True),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "api_project_id", "idempotency_key", name="uq_platform_usage_idempotency"),
        )
    _create_index("ix_platform_usage_org_project_time", "platform_api_usage_events", ["organization_id", "api_project_id", "created_at"])
    _create_index("ix_platform_usage_key_time", "platform_api_usage_events", ["api_key_id", "created_at"])
    _create_index("ix_platform_usage_metric_time", "platform_api_usage_events", ["metric", "created_at"])

    if not _has_table("platform_idempotency_records"):
        op.create_table(
            "platform_idempotency_records",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="in_progress"),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_json", sa.JSON(), nullable=True),
            sa.Column("operation_id", sa.String(), nullable=True),
            sa.Column("first_request_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "api_project_id", "operation", "idempotency_key", name="uq_platform_idempotency_scope"),
        )
    _create_index("ix_platform_idempotency_expires", "platform_idempotency_records", ["expires_at"])

    if not _has_table("provider_external_identity_maps"):
        op.create_table(
            "provider_external_identity_maps",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("external_object_type", sa.String(), nullable=False),
            sa.Column("external_object_id", sa.String(), nullable=False),
            sa.Column("internal_object_type", sa.String(), nullable=False),
            sa.Column("internal_object_id", sa.String(), nullable=False),
            sa.Column("provider_version", sa.String(), nullable=True),
            sa.Column("etag", sa.String(), nullable=True),
            sa.Column("tombstoned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_synchronized_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("organization_id", "provider", "connection_id", "external_object_type", "external_object_id", name="uq_provider_external_identity"),
        )
    _create_index("ix_provider_identity_internal", "provider_external_identity_maps", ["organization_id", "internal_object_type", "internal_object_id"])

    if not _has_table("provider_capability_records"):
        op.create_table(
            "provider_capability_records",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=True),
            sa.Column("capability", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="awaiting_partner_contract"),
            sa.Column("source", sa.String(), nullable=False, server_default="adapter_contract"),
            sa.Column("diagnostics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("last_validated_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "provider", "connection_id", "capability", name="uq_provider_capability_connection"),
        )
    _create_index("ix_provider_capability_status", "provider_capability_records", ["provider", "status"])

    if not _has_table("platform_webhook_endpoints"):
        op.create_table(
            "platform_webhook_endpoints",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("subscribed_event_types", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("signing_secret_hash", sa.String(length=64), nullable=False),
            sa.Column("signing_secret_prefix", sa.String(length=24), nullable=False),
            sa.Column("signing_secret_version", sa.String(), nullable=False, server_default="v1"),
            sa.Column("previous_secret_hash", sa.String(length=64), nullable=True),
            sa.Column("previous_secret_expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("disabled_at", sa.DateTime(), nullable=True),
        )
    _create_index("ix_platform_webhook_endpoint_project_status", "platform_webhook_endpoints", ["organization_id", "api_project_id", "status"])

    if not _has_table("platform_webhook_events"):
        op.create_table(
            "platform_webhook_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False, server_default="2026-07-10"),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index("ix_platform_webhook_event_project_time", "platform_webhook_events", ["organization_id", "api_project_id", "created_at"])
    _create_index("ix_platform_webhook_event_type_time", "platform_webhook_events", ["event_type", "created_at"])

    if not _has_table("platform_webhook_delivery_attempts"):
        op.create_table(
            "platform_webhook_delivery_attempts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("event_id", sa.String(), sa.ForeignKey("platform_webhook_events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("endpoint_id", sa.String(), sa.ForeignKey("platform_webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("request_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_excerpt", sa.Text(), nullable=True),
            sa.Column("error_classification", sa.String(), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("event_id", "endpoint_id", "attempt_number", name="uq_platform_webhook_attempt"),
        )
    _create_index("ix_platform_webhook_delivery_next_retry", "platform_webhook_delivery_attempts", ["status", "next_retry_at"])

    if not _has_table("action_safety_configurations"):
        op.create_table(
            "action_safety_configurations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=True),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=True),
            sa.Column("resource_id", sa.String(), nullable=True),
            sa.Column("command_type", sa.String(), nullable=False, server_default="*"),
            sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("updated_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "api_project_id", "connection_id", "resource_id", "command_type", name="uq_action_safety_scope"),
        )


def downgrade() -> None:
    for table in [
        "action_safety_configurations",
        "platform_webhook_delivery_attempts",
        "platform_webhook_events",
        "platform_webhook_endpoints",
        "provider_capability_records",
        "provider_external_identity_maps",
        "platform_idempotency_records",
        "platform_api_usage_events",
        "platform_api_keys",
        "api_service_accounts",
        "api_projects",
    ]:
        if _has_table(table):
            op.drop_table(table)
