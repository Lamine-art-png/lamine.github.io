"""Add operational record and preference tables.

Revision ID: 011_operational_records
Revises: 010_account_recovery
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "011_operational_records"
down_revision = "010_account_recovery"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _column_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _create_index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if not _has_table(table):
        return
    if not set(columns).issubset(_column_names(table)):
        return
    existing = {idx["name"] for idx in _inspector().get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("user_preferences"):
        op.create_table(
            "user_preferences",
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("locale", sa.String(), nullable=True),
            sa.Column("timezone", sa.String(), nullable=True),
            sa.Column("notifications_json", sa.Text(), nullable=True),
            sa.Column("ui_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id"),
        )

    if not _has_table("connector_connections"):
        op.create_table(
            "connector_connections",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("required_plan", sa.String(), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("credentials_ref", sa.String(), nullable=True),
            sa.Column("last_test_at", sa.DateTime(), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_connector_connections_id": ["id"],
        "ix_connector_connections_tenant_id": ["tenant_id"],
        "ix_connector_connections_workspace_id": ["workspace_id"],
        "ix_connector_connections_provider": ["provider"],
        "ix_connector_connections_status": ["status"],
        "ix_connector_connections_mode": ["mode"],
        "ix_connector_connections_created_at": ["created_at"],
        "ix_connector_tenant_provider": ["tenant_id", "provider"],
    }.items():
        _create_index(name, "connector_connections", columns)

    if not _has_table("data_sources"):
        op.create_table(
            "data_sources",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("connector_connection_id", sa.String(), nullable=True),
            sa.Column("source_type", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("filename", sa.String(), nullable=True),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("storage_path", sa.String(), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["connector_connection_id"], ["connector_connections.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_data_sources_id": ["id"],
        "ix_data_sources_tenant_id": ["tenant_id"],
        "ix_data_sources_workspace_id": ["workspace_id"],
        "ix_data_sources_connector_connection_id": ["connector_connection_id"],
        "ix_data_sources_source_type": ["source_type"],
        "ix_data_sources_provider": ["provider"],
        "ix_data_sources_status": ["status"],
        "ix_data_sources_created_at": ["created_at"],
    }.items():
        _create_index(name, "data_sources", columns)

    if not _has_table("ingestion_jobs"):
        op.create_table(
            "ingestion_jobs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("connector_connection_id", sa.String(), nullable=True),
            sa.Column("data_source_id", sa.String(), nullable=True),
            sa.Column("job_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("input_json", sa.JSON(), nullable=False),
            sa.Column("output_json", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["connector_connection_id"], ["connector_connections.id"]),
            sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_ingestion_jobs_id": ["id"],
        "ix_ingestion_jobs_tenant_id": ["tenant_id"],
        "ix_ingestion_jobs_workspace_id": ["workspace_id"],
        "ix_ingestion_jobs_connector_connection_id": ["connector_connection_id"],
        "ix_ingestion_jobs_data_source_id": ["data_source_id"],
        "ix_ingestion_jobs_job_type": ["job_type"],
        "ix_ingestion_jobs_status": ["status"],
        "ix_ingestion_jobs_created_at": ["created_at"],
    }.items():
        _create_index(name, "ingestion_jobs", columns)

    if not _has_table("evidence_records"):
        op.create_table(
            "evidence_records",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("data_source_id", sa.String(), nullable=True),
            sa.Column("connector_connection_id", sa.String(), nullable=True),
            sa.Column("evidence_type", sa.String(), nullable=False),
            sa.Column("field_id", sa.String(), nullable=True),
            sa.Column("block_id", sa.String(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("units", sa.String(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("quality_status", sa.String(), nullable=False),
            sa.Column("citation_label", sa.String(), nullable=False),
            sa.Column("source_excerpt", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
            sa.ForeignKeyConstraint(["connector_connection_id"], ["connector_connections.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_evidence_records_id": ["id"],
        "ix_evidence_records_tenant_id": ["tenant_id"],
        "ix_evidence_records_workspace_id": ["workspace_id"],
        "ix_evidence_records_data_source_id": ["data_source_id"],
        "ix_evidence_records_connector_connection_id": ["connector_connection_id"],
        "ix_evidence_records_evidence_type": ["evidence_type"],
        "ix_evidence_records_field_id": ["field_id"],
        "ix_evidence_records_block_id": ["block_id"],
        "ix_evidence_records_occurred_at": ["occurred_at"],
        "ix_evidence_records_quality_status": ["quality_status"],
        "ix_evidence_records_created_at": ["created_at"],
        "ix_evidence_tenant_type_time": ["tenant_id", "evidence_type", "occurred_at"],
    }.items():
        _create_index(name, "evidence_records", columns)

    if not _has_table("intelligence_runs"):
        op.create_table(
            "intelligence_runs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("run_type", sa.String(), nullable=False),
            sa.Column("question", sa.Text(), nullable=True),
            sa.Column("input_context_json", sa.JSON(), nullable=False),
            sa.Column("output_json", sa.JSON(), nullable=False),
            sa.Column("citations_json", sa.JSON(), nullable=False),
            sa.Column("model_provider", sa.String(), nullable=True),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_intelligence_runs_id": ["id"],
        "ix_intelligence_runs_tenant_id": ["tenant_id"],
        "ix_intelligence_runs_workspace_id": ["workspace_id"],
        "ix_intelligence_runs_user_id": ["user_id"],
        "ix_intelligence_runs_run_type": ["run_type"],
        "ix_intelligence_runs_status": ["status"],
        "ix_intelligence_runs_created_at": ["created_at"],
    }.items():
        _create_index(name, "intelligence_runs", columns)

    if not _has_table("generated_artifacts"):
        op.create_table(
            "generated_artifacts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("intelligence_run_id", sa.String(), nullable=True),
            sa.Column("artifact_type", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("content_type", sa.String(), nullable=False),
            sa.Column("storage_path", sa.String(), nullable=True),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["intelligence_run_id"], ["intelligence_runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_generated_artifacts_id": ["id"],
        "ix_generated_artifacts_tenant_id": ["tenant_id"],
        "ix_generated_artifacts_workspace_id": ["workspace_id"],
        "ix_generated_artifacts_intelligence_run_id": ["intelligence_run_id"],
        "ix_generated_artifacts_artifact_type": ["artifact_type"],
        "ix_generated_artifacts_created_at": ["created_at"],
    }.items():
        _create_index(name, "generated_artifacts", columns)

    if not _has_table("chat_conversations"):
        op.create_table(
            "chat_conversations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("pinned", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("message_count", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("last_message_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_chat_conversations_id": ["id"],
        "ix_chat_conversations_tenant_id": ["tenant_id"],
        "ix_chat_conversations_workspace_id": ["workspace_id"],
        "ix_chat_conversations_user_id": ["user_id"],
        "ix_chat_conversations_pinned": ["pinned"],
        "ix_chat_conversations_status": ["status"],
        "ix_chat_conversations_created_at": ["created_at"],
        "ix_chat_conversations_updated_at": ["updated_at"],
        "ix_chat_conversations_last_message_at": ["last_message_at"],
        "ix_chat_conversation_tenant_workspace": ["tenant_id", "workspace_id", "last_message_at"],
        "ix_chat_conversation_user": ["tenant_id", "user_id", "last_message_at"],
    }.items():
        _create_index(name, "chat_conversations", columns)

    if not _has_table("chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_chat_messages_id": ["id"],
        "ix_chat_messages_conversation_id": ["conversation_id"],
        "ix_chat_messages_tenant_id": ["tenant_id"],
        "ix_chat_messages_workspace_id": ["workspace_id"],
        "ix_chat_messages_user_id": ["user_id"],
        "ix_chat_messages_role": ["role"],
        "ix_chat_messages_created_at": ["created_at"],
        "ix_chat_messages_conversation_created": ["conversation_id", "created_at"],
    }.items():
        _create_index(name, "chat_messages", columns)


def downgrade() -> None:
    for table in [
        "chat_messages",
        "chat_conversations",
        "generated_artifacts",
        "intelligence_runs",
        "evidence_records",
        "ingestion_jobs",
        "data_sources",
        "connector_connections",
        "user_preferences",
    ]:
        if _has_table(table):
            op.drop_table(table)
