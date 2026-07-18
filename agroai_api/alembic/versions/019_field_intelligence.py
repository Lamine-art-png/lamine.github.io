"""Add Field Intelligence capture, observation, asset and processing tables.

Revision ID: 019_field_intelligence
Revises: 018_outreach_engagement
Create Date: 2026-07-18

Foreign keys and delete behavior are deliberate:
* tenant_id -> organizations, workspace_id -> workspaces use RESTRICT so field
  data cannot be silently orphaned by deleting an org/workspace.
* user_id -> users uses SET NULL (attribution is lost, records survive).
* observation.capture_session_id is a UNIQUE FK -> exactly one observation per
  capture session. There is no circular FK: the capture stores an observation
  id pointer only.
* assets and processing runs CASCADE from their capture/observation owner.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "019_field_intelligence"
down_revision = "018_outreach_engagement"
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
    if not _has_table("field_capture_sessions"):
        op.create_table(
            "field_capture_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("client_capture_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=120), nullable=False),
            sa.Column("payload_fingerprint", sa.String(length=64), nullable=True),
            sa.Column("capture_source", sa.String(), nullable=False, server_default="typed"),
            sa.Column("status", sa.String(), nullable=False, server_default="received"),
            sa.Column("note_text", sa.Text(), nullable=True),
            sa.Column("transcript_preview", sa.Text(), nullable=True),
            sa.Column("field_id", sa.String(), nullable=True),
            sa.Column("field_name", sa.String(), nullable=True),
            sa.Column("block_id", sa.String(), nullable=True),
            sa.Column("block_name", sa.String(), nullable=True),
            sa.Column("crop", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=True),
            sa.Column("severity", sa.String(), nullable=True),
            sa.Column("assignee", sa.String(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("location_accuracy_m", sa.Float(), nullable=True),
            sa.Column("asset_manifest_json", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("observation_id", sa.String(), nullable=True),
            sa.Column("client_created_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"], name="fk_field_capture_tenant", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_field_capture_workspace", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_field_capture_user", ondelete="SET NULL"),
        )
    _create_index("ix_field_capture_sessions_id", "field_capture_sessions", ["id"])
    _create_index("ix_field_capture_sessions_tenant_id", "field_capture_sessions", ["tenant_id"])
    _create_index("uq_field_capture_idempotency", "field_capture_sessions", ["tenant_id", "idempotency_key"], unique=True)
    _create_index("uq_field_capture_client_id", "field_capture_sessions", ["tenant_id", "client_capture_id"], unique=True)
    _create_index("ix_field_capture_status", "field_capture_sessions", ["tenant_id", "status", "created_at"])

    if not _has_table("field_observations"):
        op.create_table(
            "field_observations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("capture_session_id", sa.String(), nullable=True),
            sa.Column("field_id", sa.String(), nullable=True),
            sa.Column("field_name", sa.String(), nullable=True),
            sa.Column("block_id", sa.String(), nullable=True),
            sa.Column("block_name", sa.String(), nullable=True),
            sa.Column("crop", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=True),
            sa.Column("severity", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="staged"),
            sa.Column("processing_error", sa.Text(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=True),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("location_accuracy_m", sa.Float(), nullable=True),
            sa.Column("transcript", sa.Text(), nullable=True),
            sa.Column("corrected_transcript", sa.Text(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("structured_json", sa.JSON(), nullable=False),
            sa.Column("extraction_schema_version", sa.String(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("uncertain_fields_json", sa.JSON(), nullable=False),
            sa.Column("recommended_action", sa.Text(), nullable=True),
            sa.Column("correlation_json", sa.JSON(), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.Column("model_provider", sa.String(), nullable=True),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("task_ids_json", sa.JSON(), nullable=False),
            sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
            sa.Column("audit_json", sa.JSON(), nullable=False),
            sa.Column("search_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"], name="fk_field_obs_tenant", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_field_obs_workspace", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_field_obs_user", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["capture_session_id"], ["field_capture_sessions.id"], name="fk_field_obs_capture", ondelete="CASCADE"),
            sa.UniqueConstraint("capture_session_id", name="uq_field_obs_capture_session"),
        )
    _create_index("ix_field_observations_id", "field_observations", ["id"])
    _create_index("ix_field_observations_tenant_id", "field_observations", ["tenant_id"])
    _create_index("ix_field_observations_workspace_id", "field_observations", ["workspace_id"])
    _create_index("ix_field_obs_tenant_ws_time", "field_observations", ["tenant_id", "workspace_id", "occurred_at"])
    _create_index("ix_field_obs_field_time", "field_observations", ["tenant_id", "field_id", "occurred_at"])
    _create_index("ix_field_obs_status", "field_observations", ["tenant_id", "status", "created_at"])
    _create_index("ix_field_obs_event_severity", "field_observations", ["tenant_id", "event_type", "severity"])

    if not _has_table("field_observation_assets"):
        op.create_table(
            "field_observation_assets",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("capture_session_id", sa.String(), nullable=True),
            sa.Column("observation_id", sa.String(), nullable=True),
            sa.Column("client_asset_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("filename", sa.String(), nullable=True),
            sa.Column("storage_backend", sa.String(), nullable=False, server_default="s3"),
            sa.Column("object_ref", sa.String(), nullable=True),
            sa.Column("content_sha256", sa.String(length=64), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="stored"),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("object_deleted_at", sa.DateTime(), nullable=True),
            sa.Column("delete_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"], name="fk_field_asset_tenant", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_field_asset_workspace", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["capture_session_id"], ["field_capture_sessions.id"], name="fk_field_asset_capture", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["observation_id"], ["field_observations.id"], name="fk_field_asset_observation", ondelete="CASCADE"),
            sa.UniqueConstraint("tenant_id", "capture_session_id", "client_asset_id", name="uq_field_asset_identity"),
        )
    _create_index("ix_field_observation_assets_id", "field_observation_assets", ["id"])
    _create_index("ix_field_observation_assets_tenant_id", "field_observation_assets", ["tenant_id"])
    _create_index("ix_field_asset_checksum", "field_observation_assets", ["tenant_id", "content_sha256"])
    _create_index("ix_field_asset_observation", "field_observation_assets", ["tenant_id", "observation_id"])
    _create_index("ix_field_asset_status", "field_observation_assets", ["tenant_id", "status"])

    if not _has_table("field_observation_processing_runs"):
        op.create_table(
            "field_observation_processing_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("observation_id", sa.String(), nullable=True),
            sa.Column("capture_session_id", sa.String(), nullable=True),
            sa.Column("stage", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("language", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="completed"),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("input_json", sa.JSON(), nullable=False),
            sa.Column("output_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"], name="fk_field_run_tenant", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_field_run_workspace", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["observation_id"], ["field_observations.id"], name="fk_field_run_observation", ondelete="CASCADE"),
        )
    _create_index("ix_field_observation_processing_runs_id", "field_observation_processing_runs", ["id"])
    _create_index("ix_field_observation_processing_runs_tenant_id", "field_observation_processing_runs", ["tenant_id"])
    _create_index("ix_field_processing_obs_stage", "field_observation_processing_runs", ["observation_id", "stage"])
    _create_index("ix_field_processing_status", "field_observation_processing_runs", ["tenant_id", "status", "created_at"])


def downgrade() -> None:
    for table in (
        "field_observation_processing_runs",
        "field_observation_assets",
        "field_observations",
        "field_capture_sessions",
    ):
        if _has_table(table):
            op.drop_table(table)
