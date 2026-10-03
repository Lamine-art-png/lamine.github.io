"""AGRO-AI Intelligence Platform v1 primitives.

Additive only. Extends ``platform_commercial_intelligence_runs`` so a run can
be a synchronous request or an asynchronous job (lease, attempts, cancel,
pending payload) and records tool provenance; adds tenant/project-owned
sessions, files, and knowledge (documents + chunks). On PostgreSQL knowledge
chunks carry a generated ``search_vector`` (``simple`` configuration, language
neutral) with a GIN index, so retrieval needs no new infrastructure.

Revision ID: 042_intelligence_platform_v1
Revises: 041_abuse_project_holds
"""
from alembic import op
import sqlalchemy as sa


revision = "042_intelligence_platform_v1"
down_revision = "041_abuse_project_holds"
branch_labels = None
depends_on = None


_RUN_TABLE = "platform_commercial_intelligence_runs"


def upgrade() -> None:
    op.add_column(_RUN_TABLE, sa.Column("execution", sa.String(length=16), nullable=False, server_default="sync"))
    op.add_column(_RUN_TABLE, sa.Column("session_id", sa.String(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(_RUN_TABLE, sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("request_payload_json", sa.JSON(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("tool_calls_json", sa.JSON(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.add_column(_RUN_TABLE, sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.create_index("ix_commercial_intelligence_run_session_id", _RUN_TABLE, ["session_id"])
    op.create_index(
        "ix_commercial_intelligence_run_job_queue",
        _RUN_TABLE,
        ["execution", "status", "next_attempt_at"],
    )

    op.create_table(
        "platform_intelligence_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_api_key_id", sa.String(), nullable=True),
        sa.Column("created_by_user_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("turn_count >= 0", name="ck_intelligence_session_turns_nonnegative"),
    )
    op.create_index("ix_platform_intelligence_sessions_organization_id", "platform_intelligence_sessions", ["organization_id"])
    op.create_index("ix_platform_intelligence_sessions_api_project_id", "platform_intelligence_sessions", ["api_project_id"])
    op.create_index(
        "ix_intelligence_session_owner_time",
        "platform_intelligence_sessions",
        ["organization_id", "api_project_id", "created_at"],
    )
    op.create_index("ix_intelligence_session_expiry", "platform_intelligence_sessions", ["status", "expires_at"])

    op.create_table(
        "platform_intelligence_session_turns",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("platform_intelligence_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_platform_intelligence_session_turns_organization_id",
        "platform_intelligence_session_turns",
        ["organization_id"],
    )
    op.create_index(
        "ix_intelligence_session_turn_order",
        "platform_intelligence_session_turns",
        ["session_id", "created_at"],
    )

    op.create_table(
        "platform_intelligence_files",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_api_key_id", sa.String(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False, server_default="attachment"),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.String(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(length=20), nullable=False, server_default="not_applicable"),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="available"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("size_bytes >= 0", name="ck_intelligence_file_size_nonnegative"),
    )
    op.create_index("ix_platform_intelligence_files_organization_id", "platform_intelligence_files", ["organization_id"])
    op.create_index("ix_platform_intelligence_files_api_project_id", "platform_intelligence_files", ["api_project_id"])
    op.create_index(
        "ix_intelligence_file_owner_time",
        "platform_intelligence_files",
        ["organization_id", "api_project_id", "created_at"],
    )
    op.create_index("ix_intelligence_file_expiry", "platform_intelligence_files", ["status", "expires_at"])

    op.create_table(
        "platform_knowledge_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("collection", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="document"),
        sa.Column("source_label", sa.String(length=200), nullable=True),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("byte_size >= 0", name="ck_knowledge_document_size_nonnegative"),
    )
    op.create_index("ix_platform_knowledge_documents_organization_id", "platform_knowledge_documents", ["organization_id"])
    op.create_index(
        "uq_knowledge_document_external_id",
        "platform_knowledge_documents",
        ["organization_id", "api_project_id", sa.text("coalesce(workspace_id, '')"), "collection", "external_id"],
        unique=True,
    )
    op.create_index("ix_platform_knowledge_documents_api_project_id", "platform_knowledge_documents", ["api_project_id"])
    op.create_index(
        "ix_knowledge_document_owner_collection",
        "platform_knowledge_documents",
        ["organization_id", "api_project_id", "collection", "created_at"],
    )

    op.create_table(
        "platform_knowledge_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("platform_knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("collection", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_chunk_owner_collection",
        "platform_knowledge_chunks",
        ["organization_id", "api_project_id", "collection"],
    )
    op.create_index("ix_knowledge_chunk_document", "platform_knowledge_chunks", ["document_id", "ordinal"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE platform_knowledge_chunks ADD COLUMN search_vector tsvector "
            "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED"
        )
        op.execute(
            "CREATE INDEX ix_knowledge_chunk_search_vector ON platform_knowledge_chunks USING GIN (search_vector)"
        )
        # Money-path parity: an async job is billed through the same ledger,
        # so execution must be one of the two known modes.
        op.execute(
            f"ALTER TABLE {_RUN_TABLE} ADD CONSTRAINT ck_commercial_intelligence_run_execution "
            "CHECK (execution IN ('sync', 'async'))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {_RUN_TABLE} DROP CONSTRAINT IF EXISTS ck_commercial_intelligence_run_execution")
    op.drop_table("platform_knowledge_chunks")
    op.drop_table("platform_knowledge_documents")
    op.drop_table("platform_intelligence_files")
    op.drop_table("platform_intelligence_session_turns")
    op.drop_table("platform_intelligence_sessions")
    op.drop_index("ix_commercial_intelligence_run_job_queue", table_name=_RUN_TABLE)
    op.drop_index("ix_commercial_intelligence_run_session_id", table_name=_RUN_TABLE)
    for column in (
        "latency_ms", "metadata_json", "tool_calls_json", "request_payload_json", "cancel_requested_at",
        "next_attempt_at", "lease_expires_at", "started_at", "attempt_count", "request_id", "session_id", "execution",
    ):
        op.drop_column(_RUN_TABLE, column)
