"""Extend the existing agent workflow layer into the autonomous operations runtime.

Revision ID: 032_autonomous_operations_runtime
Revises: 031_merge_assurance_intelligence
Create Date: 2026-09-05

The migration is additive apart from relaxing legacy tenant ownership on the two
agent tables that now also support current Organization/Workspace identity.
Legacy API-key workflows remain supported.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "032_autonomous_operations_runtime"
down_revision = "031_merge_assurance_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_procedures",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("autonomy_level", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("trigger_type", sa.String(), nullable=False, server_default="manual"),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "workspace_id", "name", "version", name="uq_agent_procedure_version"),
    )
    for column in ("organization_id", "workspace_id", "name", "domain", "status", "autonomy_level", "trigger_type", "created_at"):
        op.create_index(f"ix_agent_procedures_{column}", "agent_procedures", [column])

    op.create_table(
        "agent_policies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("organization_id", "workspace_id", "domain", "enabled", "created_at"):
        op.create_index(f"ix_agent_policies_{column}", "agent_policies", [column])

    # Enterprise Portal identity and durable lifecycle fields on the canonical run.
    with op.batch_alter_table("agent_workflow_runs") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("organization_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("workspace_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("procedure_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("procedure_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_type", sa.String(), nullable=True))
        batch.add_column(sa.Column("source_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("autonomy_level", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("current_step", sa.String(), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(), nullable=True))
        batch.add_column(sa.Column("policy_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("human_touch_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("verified_outcome", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_agent_runs_org", "organizations", ["organization_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_agent_runs_workspace", "workspaces", ["workspace_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_agent_runs_procedure", "agent_procedures", ["procedure_id"], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("uq_agent_run_org_idempotency", ["organization_id", "idempotency_key"])
    for column in ("organization_id", "workspace_id", "procedure_id", "source_type", "source_id", "autonomy_level", "idempotency_key", "verified_outcome", "completed_at"):
        op.create_index(f"ix_agent_workflow_runs_{column}", "agent_workflow_runs", [column])

    with op.batch_alter_table("agent_action_proposals") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("organization_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("workspace_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("action_type", sa.String(), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(), nullable=True))
        batch.add_column(sa.Column("execution_status", sa.String(), nullable=False, server_default="not_started"))
        batch.add_column(sa.Column("verification_status", sa.String(), nullable=False, server_default="not_required"))
        batch.add_column(sa.Column("risk_level", sa.String(), nullable=False, server_default="low"))
        batch.add_column(sa.Column("executed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("execution_result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.create_foreign_key("fk_agent_actions_org", "organizations", ["organization_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_agent_actions_workspace", "workspaces", ["workspace_id"], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("uq_agent_action_run_idempotency", ["run_id", "idempotency_key"])
    for column in ("organization_id", "workspace_id", "action_type", "idempotency_key", "execution_status", "verification_status", "risk_level", "executed_at"):
        op.create_index(f"ix_agent_action_proposals_{column}", "agent_action_proposals", [column])

    with op.batch_alter_table("agent_run_audit_events") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("organization_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("workspace_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_agent_audit_org", "organizations", ["organization_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_agent_audit_workspace", "workspaces", ["workspace_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_agent_run_audit_events_organization_id", "agent_run_audit_events", ["organization_id"])
    op.create_index("ix_agent_run_audit_events_workspace_id", "agent_run_audit_events", ["workspace_id"])

    op.create_table(
        "agent_action_evidence_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.String(), sa.ForeignKey("agent_action_proposals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("verification_status", sa.String(), nullable=False, server_default="verified"),
        sa.Column("verification_method", sa.String(), nullable=False, server_default="canonical_evidence_validator"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("verified_by", sa.String(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("action_id", "evidence_type", "evidence_id", name="uq_agent_action_evidence"),
    )
    for column in ("organization_id", "workspace_id", "run_id", "action_id", "evidence_type", "evidence_id", "verification_status", "verified_at"):
        op.create_index(f"ix_agent_action_evidence_links_{column}", "agent_action_evidence_links", [column])

    op.create_table(
        "agent_workflow_outcomes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("organization_id", "workspace_id", "run_id", "status", "created_at"):
        op.create_index(f"ix_agent_workflow_outcomes_{column}", "agent_workflow_outcomes", [column])


def downgrade() -> None:
    op.drop_table("agent_workflow_outcomes")
    op.drop_table("agent_action_evidence_links")

    with op.batch_alter_table("agent_run_audit_events") as batch:
        batch.drop_constraint("fk_agent_audit_workspace", type_="foreignkey")
        batch.drop_constraint("fk_agent_audit_org", type_="foreignkey")
        batch.drop_column("workspace_id")
        batch.drop_column("organization_id")
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=False)

    with op.batch_alter_table("agent_action_proposals") as batch:
        batch.drop_constraint("uq_agent_action_run_idempotency", type_="unique")
        batch.drop_constraint("fk_agent_actions_workspace", type_="foreignkey")
        batch.drop_constraint("fk_agent_actions_org", type_="foreignkey")
        for name in ("execution_result_json", "executed_at", "risk_level", "verification_status", "execution_status", "idempotency_key", "action_type", "workspace_id", "organization_id"):
            batch.drop_column(name)
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=False)

    with op.batch_alter_table("agent_workflow_runs") as batch:
        batch.drop_constraint("uq_agent_run_org_idempotency", type_="unique")
        batch.drop_constraint("fk_agent_runs_procedure", type_="foreignkey")
        batch.drop_constraint("fk_agent_runs_workspace", type_="foreignkey")
        batch.drop_constraint("fk_agent_runs_org", type_="foreignkey")
        for name in ("completed_at", "verified_outcome", "human_touch_count", "policy_snapshot_json", "idempotency_key", "current_step", "autonomy_level", "source_id", "source_type", "procedure_version", "procedure_id", "workspace_id", "organization_id"):
            batch.drop_column(name)
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=False)

    op.drop_table("agent_policies")
    op.drop_table("agent_procedures")
