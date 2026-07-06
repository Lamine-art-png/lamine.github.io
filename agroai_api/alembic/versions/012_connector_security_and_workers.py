"""Add one-time OAuth state, encrypted credential custody, queue leases, and provenance.

Revision ID: 012_connector_security
Revises: 011_operational_records
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "012_connector_security"
down_revision = "011_operational_records"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {item["name"] for item in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {item["name"] for item in _inspector().get_indexes(table) if item.get("name")}


def _add_column(table: str, column: sa.Column) -> None:
    if _has_table(table) and column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if _has_table(table) and set(columns).issubset(_columns(table)) and name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("oauth_state_nonces"):
        op.create_table(
            "oauth_state_nonces",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("connection_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("nonce_hash", sa.String(length=64), nullable=False),
            sa.Column("redirect_sha256", sa.String(length=64), nullable=False),
            sa.Column("issued_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["connection_id"], ["connector_connections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("nonce_hash", name="uq_oauth_state_nonce_hash"),
        )
    for name, columns in {
        "ix_oauth_state_tenant": ["tenant_id"],
        "ix_oauth_state_connection": ["connection_id"],
        "ix_oauth_state_expires": ["expires_at"],
        "ix_oauth_state_pending_lookup": ["connection_id", "provider", "consumed_at", "expires_at"],
    }.items():
        _create_index(name, "oauth_state_nonces", columns)

    if not _has_table("connector_credentials"):
        op.create_table(
            "connector_credentials",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("connection_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("key_version", sa.String(), nullable=False),
            sa.Column("algorithm", sa.String(), nullable=False),
            sa.Column("nonce_b64", sa.Text(), nullable=False),
            sa.Column("ciphertext_b64", sa.Text(), nullable=False),
            sa.Column("token_expires_at", sa.DateTime(), nullable=True),
            sa.Column("scopes_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["connection_id"], ["connector_connections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("connection_id", name="uq_connector_credential_connection"),
        )
    for name, columns in {
        "ix_connector_credentials_tenant": ["tenant_id"],
        "ix_connector_credentials_provider": ["provider"],
        "ix_connector_credentials_active": ["tenant_id", "provider", "revoked_at"],
    }.items():
        _create_index(name, "connector_credentials", columns)

    _add_column("data_sources", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    _add_column("data_sources", sa.Column("object_size_bytes", sa.BigInteger(), nullable=True))
    _create_index(
        "uq_data_source_content_identity",
        "data_sources",
        ["tenant_id", "connector_connection_id", "content_sha256"],
        unique=True,
    )

    _add_column("ingestion_jobs", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    _add_column("ingestion_jobs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    _add_column("ingestion_jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"))
    _add_column("ingestion_jobs", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    _add_column("ingestion_jobs", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    _add_column("ingestion_jobs", sa.Column("worker_id", sa.String(), nullable=True))
    _add_column("ingestion_jobs", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
    _add_column("ingestion_jobs", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    _create_index("uq_ingestion_job_idempotency", "ingestion_jobs", ["tenant_id", "idempotency_key"], unique=True)
    _create_index("ix_ingestion_job_claim", "ingestion_jobs", ["status", "next_attempt_at", "lease_expires_at"])

    _add_column("evidence_records", sa.Column("source_updated_at", sa.DateTime(), nullable=True))
    _add_column("intelligence_runs", sa.Column("provenance_json", sa.JSON(), nullable=True))
    _add_column("intelligence_runs", sa.Column("freshness_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    for table, name in [
        ("ingestion_jobs", "ix_ingestion_job_claim"),
        ("ingestion_jobs", "uq_ingestion_job_idempotency"),
        ("data_sources", "uq_data_source_content_identity"),
    ]:
        if _has_table(table) and name in _indexes(table):
            op.drop_index(name, table_name=table)

    for table, columns in {
        "intelligence_runs": ["freshness_json", "provenance_json"],
        "evidence_records": ["source_updated_at"],
        "ingestion_jobs": [
            "cancelled_at", "last_heartbeat_at", "worker_id", "lease_expires_at",
            "next_attempt_at", "max_attempts", "attempt_count", "idempotency_key",
        ],
        "data_sources": ["object_size_bytes", "content_sha256"],
    }.items():
        for column in columns:
            if _has_table(table) and column in _columns(table):
                op.drop_column(table, column)

    for table in ["connector_credentials", "oauth_state_nonces"]:
        if _has_table(table):
            op.drop_table(table)
