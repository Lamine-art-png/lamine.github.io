"""Add durable autonomous operations runtime.

Revision ID: 032_autonomous_operations
Revises: 031_merge_assurance_intelligence
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "032_autonomous_operations"
down_revision = "031_merge_assurance_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomy_procedures",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("procedure_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("domain", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="system"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trigger_types_json", sa.JSON(), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("outcome_contract_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "procedure_key", "version", name="uq_autonomy_procedure_org_key_version"),
    )
    for name in ("organization_id", "procedure_key", "domain", "active"):
        op.create_index(f"ix_autonomy_procedures_{name}", "autonomy_procedures", [name])
    op.create_index("ix_autonomy_procedure_lookup", "autonomy_procedures", ["organization_id", "procedure_key", "active", "version"])

    op.create_table(
        "autonomy_policies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("autonomy_level", sa.String(length=2), nullable=False, server_default="A4"),
        sa.Column("action_class_caps_json", sa.JSON(), nullable=False),
        sa.Column("risk_caps_json", sa.JSON(), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "workspace_id", name="uq_autonomy_policy_scope"),
    )
    for name in ("organization_id", "workspace_id", "enabled"):
        op.create_index(f"ix_autonomy_policies_{name}", "autonomy_policies", [name])
    op.create_index("ix_autonomy_policy_scope", "autonomy_policies", ["organization_id", "workspace_id", "enabled"])

    op.create_table(
        "autonomy_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("procedure_id", sa.String(), sa.ForeignKey("autonomy_procedures.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("procedure_key", sa.String(length=120), nullable=False),
        sa.Column("trigger_type", sa.String(length=80), nullable=False),
        sa.Column("trigger_ref", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="running"),
        sa.Column("requested_autonomy_level", sa.String(length=2), nullable=False, server_default="A4"),
        sa.Column("effective_autonomy_level", sa.String(length=2), nullable=False, server_default="A4"),
        sa.Column("current_step_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible_for_autonomy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_decision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exception_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("outcome_status", sa.String(length=80), nullable=True),
        sa.Column("verification_status", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for name in ("organization_id", "workspace_id", "procedure_id", "procedure_key", "trigger_type", "trigger_ref", "status", "eligible_for_autonomy", "outcome_status", "verification_status", "completed_at"):
        op.create_index(f"ix_autonomy_runs_{name}", "autonomy_runs", [name])
    op.create_index("ix_autonomy_run_scope_status", "autonomy_runs", ["organization_id", "workspace_id", "status", "updated_at"])
    op.create_index("ix_autonomy_run_trigger", "autonomy_runs", ["organization_id", "procedure_key", "trigger_type", "trigger_ref"])

    op.create_table(
        "autonomy_steps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("autonomy_runs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("step_type", sa.String(length=40), nullable=False),
        sa.Column("action_class", sa.String(length=60), nullable=False, server_default="intelligence"),
        sa.Column("action_type", sa.String(length=120), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="low"),
        sa.Column("minimum_autonomy_level", sa.String(length=2), nullable=False, server_default="A4"),
        sa.Column("effective_autonomy_level", sa.String(length=2), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False, unique=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "sequence", name="uq_autonomy_step_run_sequence"),
    )
    for name in ("run_id", "organization_id", "step_type", "action_class", "risk_level", "status"):
        op.create_index(f"ix_autonomy_steps_{name}", "autonomy_steps", [name])
    op.create_index("ix_autonomy_step_run_status", "autonomy_steps", ["run_id", "status", "sequence"])

    op.create_table(
        "autonomy_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("autonomy_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(), sa.ForeignKey("autonomy_steps.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=160), nullable=False, server_default="system"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for name in ("run_id", "step_id", "organization_id", "event_type", "created_at"):
        op.create_index(f"ix_autonomy_events_{name}", "autonomy_events", [name])
    op.create_index("ix_autonomy_event_run_time", "autonomy_events", ["run_id", "created_at"])
    op.create_index("ix_autonomy_event_scope_time", "autonomy_events", ["organization_id", "created_at"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION protect_autonomy_events_append_only()
            RETURNS trigger AS $
            BEGIN
                RAISE EXCEPTION 'AGRO-AI autonomy event history is append-only';
            END;
            $ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_autonomy_events_append_only
            BEFORE UPDATE OR DELETE ON autonomy_events
            FOR EACH ROW EXECUTE FUNCTION protect_autonomy_events_append_only();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_autonomy_events_append_only ON autonomy_events")
        op.execute("DROP FUNCTION IF EXISTS protect_autonomy_events_append_only()")
    op.drop_table("autonomy_events")
    op.drop_table("autonomy_steps")
    op.drop_table("autonomy_runs")
    op.drop_table("autonomy_policies")
    op.drop_table("autonomy_procedures")
