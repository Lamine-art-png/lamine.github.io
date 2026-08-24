"""Add durable Field State and generalized Decision Memory.

Revision ID: 030_intelligence_state_memory
Revises: 029_platform_cli_device_auth
Create Date: 2026-08-22

Adds a mutable current Field State projection backed by immutable revisions,
immutable generalized decision snapshots, and a lifecycle head backed by an
append-only transition event log. Existing irrigation DecisionRun and
ExecutionVerification records remain intact and may be linked by opaque IDs.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "030_intelligence_state_memory"
down_revision = "029_platform_cli_device_auth"
branch_labels = None
depends_on = None


_IMMUTABLE_TABLES = (
    "field_state_revisions",
    "decision_snapshots",
    "decision_lifecycle_events",
)
_HEAD_TABLES = (
    "field_states",
    "decision_lifecycles",
)


def _install_postgres_immutability() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_agroai_immutable_memory()
        RETURNS trigger AS $$
        DECLARE
            old_protected jsonb;
            new_protected jsonb;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'AGRO-AI intelligence memory table % is append-only; DELETE is forbidden', TG_TABLE_NAME;
            END IF;

            old_protected := to_jsonb(OLD);
            new_protected := to_jsonb(NEW);

            IF TG_TABLE_NAME = 'field_state_revisions' THEN
                old_protected := old_protected - 'workspace_id' - 'created_by_intelligence_run_id';
                new_protected := new_protected - 'workspace_id' - 'created_by_intelligence_run_id';
                IF new_protected IS DISTINCT FROM old_protected THEN
                    RAISE EXCEPTION 'AGRO-AI Field State revisions are immutable';
                END IF;
                IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id AND NEW.workspace_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Field State workspace linkage may only be cleared by retention policy';
                END IF;
                IF NEW.created_by_intelligence_run_id IS DISTINCT FROM OLD.created_by_intelligence_run_id
                   AND NEW.created_by_intelligence_run_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Field State run linkage may only be cleared by retention policy';
                END IF;
                RETURN NEW;
            ELSIF TG_TABLE_NAME = 'decision_snapshots' THEN
                old_protected := old_protected - 'workspace_id' - 'user_id' - 'intelligence_run_id';
                new_protected := new_protected - 'workspace_id' - 'user_id' - 'intelligence_run_id';
                IF new_protected IS DISTINCT FROM old_protected THEN
                    RAISE EXCEPTION 'AGRO-AI Decision Snapshots are immutable';
                END IF;
                IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id AND NEW.workspace_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Decision Snapshot workspace linkage may only be cleared by retention policy';
                END IF;
                IF NEW.user_id IS DISTINCT FROM OLD.user_id AND NEW.user_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Decision Snapshot user linkage may only be cleared by retention policy';
                END IF;
                IF NEW.intelligence_run_id IS DISTINCT FROM OLD.intelligence_run_id AND NEW.intelligence_run_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Decision Snapshot run linkage may only be cleared by retention policy';
                END IF;
                RETURN NEW;
            ELSIF TG_TABLE_NAME = 'decision_lifecycle_events' THEN
                old_protected := old_protected - 'workspace_id' - 'actor_user_id';
                new_protected := new_protected - 'workspace_id' - 'actor_user_id';
                IF new_protected IS DISTINCT FROM old_protected THEN
                    RAISE EXCEPTION 'AGRO-AI Decision Lifecycle Events are immutable';
                END IF;
                IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id AND NEW.workspace_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Lifecycle Event workspace linkage may only be cleared by retention policy';
                END IF;
                IF NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id AND NEW.actor_user_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Lifecycle Event actor linkage may only be cleared by retention policy';
                END IF;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'Unsupported immutable intelligence memory table %', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_agroai_memory_head_delete()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'AGRO-AI intelligence memory head % anchors durable history and cannot be deleted', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_agroai_immutable_memory();"
        )
    for table in _HEAD_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_agroai_memory_head_delete();"
        )


def upgrade() -> None:
    op.create_table(
        "field_states",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("field_id", sa.String(), nullable=True),
        sa.Column("block_id", sa.String(), nullable=True),
        sa.Column("scope_key", sa.String(length=512), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("as_of_at", sa.DateTime(), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("conflicts_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "scope_key", name="uq_field_state_org_scope"),
        sa.CheckConstraint("revision >= 1", name="ck_field_states_revision_positive"),
    )
    op.create_index("ix_field_states_organization_id", "field_states", ["organization_id"])
    op.create_index("ix_field_states_workspace_id", "field_states", ["workspace_id"])
    op.create_index("ix_field_states_field_id", "field_states", ["field_id"])
    op.create_index("ix_field_states_block_id", "field_states", ["block_id"])
    op.create_index("ix_field_states_as_of_at", "field_states", ["as_of_at"])
    op.create_index("ix_field_states_state_hash", "field_states", ["state_hash"])
    op.create_index("ix_field_state_scope", "field_states", ["organization_id", "workspace_id", "field_id", "block_id"])

    op.create_table(
        "field_state_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("field_state_id", sa.String(), sa.ForeignKey("field_states.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("field_id", sa.String(), nullable=True),
        sa.Column("block_id", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("as_of_at", sa.DateTime(), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("conflicts_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_revision_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by_intelligence_run_id", sa.String(), sa.ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("field_state_id", "revision", name="uq_field_state_revision_number"),
        sa.UniqueConstraint("field_state_id", "state_hash", name="uq_field_state_revision_hash"),
        sa.CheckConstraint("revision >= 1", name="ck_field_state_revisions_revision_positive"),
    )
    op.create_index("ix_field_state_revisions_field_state_id", "field_state_revisions", ["field_state_id"])
    op.create_index("ix_field_state_revisions_organization_id", "field_state_revisions", ["organization_id"])
    op.create_index("ix_field_state_revisions_workspace_id", "field_state_revisions", ["workspace_id"])
    op.create_index("ix_field_state_revisions_field_id", "field_state_revisions", ["field_id"])
    op.create_index("ix_field_state_revisions_block_id", "field_state_revisions", ["block_id"])
    op.create_index("ix_field_state_revisions_as_of_at", "field_state_revisions", ["as_of_at"])
    op.create_index("ix_field_state_revisions_created_by_run", "field_state_revisions", ["created_by_intelligence_run_id"])
    op.create_index("ix_field_state_revision_scope", "field_state_revisions", ["organization_id", "workspace_id", "field_id", "block_id", "revision"])

    op.create_table(
        "decision_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("field_state_revision_id", sa.String(), sa.ForeignKey("field_state_revisions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("intelligence_run_id", sa.String(), sa.ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("legacy_decision_run_id", sa.String(), nullable=True),
        sa.Column("field_id", sa.String(), nullable=True),
        sa.Column("block_id", sa.String(), nullable=True),
        sa.Column("domain", sa.String(length=80), nullable=False),
        sa.Column("task", sa.String(length=120), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("decision_schema_version", sa.String(length=80), nullable=False),
        sa.Column("grounding_schema_version", sa.String(length=80), nullable=False),
        sa.Column("science_ruleset_version", sa.String(length=80), nullable=False),
        sa.Column("evidence_graph_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("science_trace_json", sa.JSON(), nullable=False),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("grounding_confidence", sa.Float(), nullable=False),
        sa.Column("model_provider", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("reasoning_effort", sa.String(), nullable=True),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("action_policy_version", sa.String(length=80), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_decision_snapshot_idempotency"),
        sa.CheckConstraint("grounding_confidence >= 0 AND grounding_confidence <= 1", name="ck_decision_snapshot_confidence"),
        sa.CheckConstraint("domain IN ('water','crop_health','equipment','assurance','reporting','operations')", name="ck_decision_snapshot_domain"),
    )
    op.create_index("ix_decision_snapshots_organization_id", "decision_snapshots", ["organization_id"])
    op.create_index("ix_decision_snapshots_workspace_id", "decision_snapshots", ["workspace_id"])
    op.create_index("ix_decision_snapshots_user_id", "decision_snapshots", ["user_id"])
    op.create_index("ix_decision_snapshots_field_state_revision_id", "decision_snapshots", ["field_state_revision_id"])
    op.create_index("ix_decision_snapshots_intelligence_run_id", "decision_snapshots", ["intelligence_run_id"])
    op.create_index("ix_decision_snapshots_legacy_decision_run_id", "decision_snapshots", ["legacy_decision_run_id"])
    op.create_index("ix_decision_snapshots_field_id", "decision_snapshots", ["field_id"])
    op.create_index("ix_decision_snapshots_block_id", "decision_snapshots", ["block_id"])
    op.create_index("ix_decision_snapshots_domain", "decision_snapshots", ["domain"])
    op.create_index("ix_decision_snapshots_task", "decision_snapshots", ["task"])
    op.create_index("ix_decision_snapshots_snapshot_hash", "decision_snapshots", ["snapshot_hash"])
    op.create_index("ix_decision_snapshots_created_at", "decision_snapshots", ["created_at"])
    op.create_index("ix_decision_snapshot_scope", "decision_snapshots", ["organization_id", "workspace_id", "field_id", "block_id", "created_at"])
    op.create_index("ix_decision_snapshot_domain", "decision_snapshots", ["organization_id", "domain", "created_at"])

    op.create_table(
        "decision_lifecycles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("decision_snapshot_id", sa.String(), sa.ForeignKey("decision_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.String(length=40), nullable=False, server_default="proposed"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approved_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verification_status", sa.String(length=40), nullable=True),
        sa.Column("outcome", sa.String(length=80), nullable=True),
        sa.Column("legacy_execution_verification_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("decision_snapshot_id", name="uq_decision_lifecycle_snapshot"),
        sa.CheckConstraint("version >= 1", name="ck_decision_lifecycles_version_positive"),
        sa.CheckConstraint(
            "state IN ('proposed','awaiting_approval','approved','execution_pending','executed','verification_pending','verified','rejected','failed','expired','cancelled')",
            name="ck_decision_lifecycles_state",
        ),
    )
    op.create_index("ix_decision_lifecycles_snapshot", "decision_lifecycles", ["decision_snapshot_id"])
    op.create_index("ix_decision_lifecycles_organization_id", "decision_lifecycles", ["organization_id"])
    op.create_index("ix_decision_lifecycles_workspace_id", "decision_lifecycles", ["workspace_id"])
    op.create_index("ix_decision_lifecycles_state", "decision_lifecycles", ["state"])
    op.create_index("ix_decision_lifecycles_expires_at", "decision_lifecycles", ["expires_at"])
    op.create_index("ix_decision_lifecycles_verification_status", "decision_lifecycles", ["verification_status"])
    op.create_index("ix_decision_lifecycles_outcome", "decision_lifecycles", ["outcome"])
    op.create_index("ix_decision_lifecycles_legacy_verification", "decision_lifecycles", ["legacy_execution_verification_id"])
    op.create_index("ix_decision_lifecycle_state", "decision_lifecycles", ["organization_id", "state", "updated_at"])

    op.create_table(
        "decision_lifecycle_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("lifecycle_id", sa.String(), sa.ForeignKey("decision_lifecycles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(length=40), nullable=True),
        sa.Column("to_state", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("lifecycle_id", "sequence", name="uq_decision_lifecycle_event_sequence"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_decision_lifecycle_event_idempotency"),
        sa.CheckConstraint("sequence >= 1", name="ck_decision_lifecycle_events_sequence_positive"),
        sa.CheckConstraint("actor_type IN ('user','system','provider')", name="ck_decision_lifecycle_events_actor_type"),
    )
    op.create_index("ix_decision_lifecycle_events_lifecycle_id", "decision_lifecycle_events", ["lifecycle_id"])
    op.create_index("ix_decision_lifecycle_events_organization_id", "decision_lifecycle_events", ["organization_id"])
    op.create_index("ix_decision_lifecycle_events_workspace_id", "decision_lifecycle_events", ["workspace_id"])
    op.create_index("ix_decision_lifecycle_events_event_type", "decision_lifecycle_events", ["event_type"])
    op.create_index("ix_decision_lifecycle_events_created_at", "decision_lifecycle_events", ["created_at"])
    op.create_index("ix_decision_lifecycle_event_time", "decision_lifecycle_events", ["lifecycle_id", "created_at"])

    _install_postgres_immutability()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table};")
        for table in _HEAD_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete ON {table};")
        op.execute("DROP FUNCTION IF EXISTS protect_agroai_immutable_memory();")
        op.execute("DROP FUNCTION IF EXISTS reject_agroai_memory_head_delete();")
    op.drop_table("decision_lifecycle_events")
    op.drop_table("decision_lifecycles")
    op.drop_table("decision_snapshots")
    op.drop_table("field_state_revisions")
    op.drop_table("field_states")
