"""Harden Platform API isolation, idempotency, and webhook delivery.

Revision ID: 020_platform_api_hardening
Revises: 019_platform_api_private_beta
Create Date: 2026-07-18
"""
from __future__ import annotations

from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = "020_platform_api_hardening"
down_revision = "019_platform_api_private_beta"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add_column("platform_webhook_endpoints", sa.Column("signing_secret_key_version", sa.String(), nullable=True))
    _add_column("platform_webhook_endpoints", sa.Column("signing_secret_nonce_b64", sa.Text(), nullable=True))
    _add_column("platform_webhook_endpoints", sa.Column("signing_secret_ciphertext_b64", sa.Text(), nullable=True))
    _add_column("platform_webhook_endpoints", sa.Column("previous_secret_key_version", sa.String(), nullable=True))
    _add_column("platform_webhook_endpoints", sa.Column("previous_secret_nonce_b64", sa.Text(), nullable=True))
    _add_column("platform_webhook_endpoints", sa.Column("previous_secret_ciphertext_b64", sa.Text(), nullable=True))
    _add_column("platform_webhook_endpoints", sa.Column("revoked_at", sa.DateTime(), nullable=True))

    if "platform_webhook_outbox" not in _inspector().get_table_names():
        op.create_table(
            "platform_webhook_outbox",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_id", sa.String(), sa.ForeignKey("platform_webhook_events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("endpoint_id", sa.String(), sa.ForeignKey("platform_webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("event_id", "endpoint_id", name="uq_platform_webhook_outbox_event_endpoint"),
        )
        op.create_index(
            "ix_platform_webhook_outbox_ready",
            "platform_webhook_outbox",
            ["status", "next_attempt_at", "created_at"],
        )
        op.create_index("ix_platform_webhook_outbox_organization_id", "platform_webhook_outbox", ["organization_id"])
        op.create_index("ix_platform_webhook_outbox_api_project_id", "platform_webhook_outbox", ["api_project_id"])
        op.create_index("ix_platform_webhook_outbox_event_id", "platform_webhook_outbox", ["event_id"])
        op.create_index("ix_platform_webhook_outbox_endpoint_id", "platform_webhook_outbox", ["endpoint_id"])

    if "platform_webhook_audit_events" not in _inspector().get_table_names():
        op.create_table(
            "platform_webhook_audit_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("endpoint_id", sa.String(), sa.ForeignKey("platform_webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("actor_type", sa.String(), nullable=False),
            sa.Column("actor_id", sa.String(), nullable=True),
            sa.Column("request_id", sa.String(), nullable=True),
            sa.Column("details_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_platform_webhook_audit_org_endpoint_time",
            "platform_webhook_audit_events",
            ["organization_id", "endpoint_id", "created_at"],
        )
        op.create_index("ix_platform_webhook_audit_events_api_project_id", "platform_webhook_audit_events", ["api_project_id"])
        op.create_index("ix_platform_webhook_audit_events_action", "platform_webhook_audit_events", ["action"])

    # Hash-only beta endpoints cannot safely sign deliveries. Preserve them for
    # customer inspection but fail closed until the customer creates a new
    # endpoint with one-time plaintext plus encrypted custody.
    connection = op.get_bind()
    endpoints = sa.table(
        "platform_webhook_endpoints",
        sa.column("id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("api_project_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("signing_secret_ciphertext_b64", sa.Text()),
        sa.column("disabled_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    audit = sa.table(
        "platform_webhook_audit_events",
        sa.column("id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("api_project_id", sa.String()),
        sa.column("endpoint_id", sa.String()),
        sa.column("action", sa.String()),
        sa.column("actor_type", sa.String()),
        sa.column("actor_id", sa.String()),
        sa.column("request_id", sa.String()),
        sa.column("details_json", sa.JSON()),
        sa.column("created_at", sa.DateTime()),
    )
    legacy_rows = connection.execute(
        sa.select(endpoints.c.id, endpoints.c.organization_id, endpoints.c.api_project_id).where(
            endpoints.c.status == "active",
            endpoints.c.signing_secret_ciphertext_b64.is_(None),
        )
    ).mappings().all()
    now = datetime.utcnow()
    for row in legacy_rows:
        connection.execute(
            audit.insert().values(
                id=str(uuid.uuid4()),
                organization_id=row["organization_id"],
                api_project_id=row["api_project_id"],
                endpoint_id=row["id"],
                action="disabled",
                actor_type="migration",
                actor_id=revision,
                request_id=None,
                details_json={"reason": "legacy_hash_only_secret_custody"},
                created_at=now,
            )
        )
    if legacy_rows:
        connection.execute(
            endpoints.update()
            .where(
                endpoints.c.status == "active",
                endpoints.c.signing_secret_ciphertext_b64.is_(None),
            )
            .values(status="disabled", disabled_at=now, updated_at=now)
        )


def downgrade() -> None:
    for table in ("platform_webhook_audit_events", "platform_webhook_outbox"):
        if table in _inspector().get_table_names():
            op.drop_table(table)
    for column in (
        "revoked_at",
        "previous_secret_ciphertext_b64",
        "previous_secret_nonce_b64",
        "previous_secret_key_version",
        "signing_secret_ciphertext_b64",
        "signing_secret_nonce_b64",
        "signing_secret_key_version",
    ):
        if column in _columns("platform_webhook_endpoints"):
            op.drop_column("platform_webhook_endpoints", column)
