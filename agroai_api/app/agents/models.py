"""SQLAlchemy models for deterministic and autonomous agent workflow runs."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


class AgentProcedure(Base):
    """Versioned executable operating procedure scoped to an enterprise workspace."""

    __tablename__ = "agent_procedures"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    name = Column(String, nullable=False, index=True)
    domain = Column(String, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String, default="draft", nullable=False, index=True)
    autonomy_level = Column(Integer, default=2, nullable=False, index=True)
    trigger_type = Column(String, default="manual", nullable=False, index=True)
    definition_json = Column(JSON, nullable=False, default=dict)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "workspace_id", "name", "version", name="uq_agent_procedure_version"),
    )


class AgentPolicy(Base):
    """Server-authoritative autonomy policy for a domain/workspace."""

    __tablename__ = "agent_policies"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    rules_json = Column(JSON, nullable=False, default=dict)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AgentWorkflowRun(Base):
    __tablename__ = "agent_workflow_runs"

    id = Column(String, primary_key=True)
    # Legacy API-key workflows still use tenant_id. Enterprise Portal autonomy
    # uses organization/workspace identity. Exactly one identity domain is
    # expected at service boundaries; both remain nullable for migration safety.
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    procedure_id = Column(String, ForeignKey("agent_procedures.id", ondelete="RESTRICT"), nullable=True, index=True)
    procedure_version = Column(Integer, nullable=True)
    workflow_type = Column(String, nullable=False, index=True)
    source_type = Column(String, nullable=True, index=True)
    source_id = Column(String, nullable=True, index=True)
    status = Column(String, default="completed", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False, index=True)
    autonomy_level = Column(Integer, default=1, nullable=False, index=True)
    current_step = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True, index=True)
    policy_snapshot_json = Column(JSON, nullable=False, default=dict)
    human_touch_count = Column(Integer, default=0, nullable=False)
    verified_outcome = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    actor = Column(String, default="system", nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False, index=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_agent_run_org_idempotency"),
    )


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    status = Column(String, default="completed", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    actor = Column(String, default="system", nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class AgentFinding(Base):
    __tablename__ = "agent_findings"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    status = Column(String, default="open", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    actor = Column(String, default="system", nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class AgentRecommendation(Base):
    __tablename__ = "agent_recommendations"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    status = Column(String, default="proposed", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    actor = Column(String, default="system", nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class AgentActionProposal(Base):
    __tablename__ = "agent_action_proposals"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    action_type = Column(String, nullable=True, index=True)
    idempotency_key = Column(String, nullable=True, index=True)
    status = Column(String, default="proposed", nullable=False, index=True)
    execution_status = Column(String, default="not_started", nullable=False, index=True)
    verification_status = Column(String, default="not_required", nullable=False, index=True)
    risk_level = Column(String, default="low", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True, index=True)
    actor = Column(String, default="system", nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    execution_result_json = Column(JSON, nullable=False, default=dict)
    requires_human_approval = Column(Boolean, default=False, nullable=False, index=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_agent_action_run_idempotency"),
    )


class AgentActionEvidenceLink(Base):
    """Verified proof that an executed action produced the claimed real-world outcome."""

    __tablename__ = "agent_action_evidence_links"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    action_id = Column(String, ForeignKey("agent_action_proposals.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_type = Column(String, nullable=False, index=True)
    evidence_id = Column(String, nullable=False, index=True)
    verification_status = Column(String, default="verified", nullable=False, index=True)
    verification_method = Column(String, default="canonical_evidence_validator", nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict)
    verified_by = Column(String, nullable=True)
    verified_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("action_id", "evidence_type", "evidence_id", name="uq_agent_action_evidence"),
    )


class AgentWorkflowOutcome(Base):
    __tablename__ = "agent_workflow_outcomes"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, index=True)
    summary = Column(Text, nullable=True)
    metrics_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    status = Column(String, default="completed", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    actor = Column(String, default="system", nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    status = Column(String, default="sent", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    actor = Column(String, default="agent", nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class AgentRunAuditEvent(Base):
    __tablename__ = "agent_run_audit_events"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    run_id = Column(String, ForeignKey("agent_workflow_runs.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    status = Column(String, default="recorded", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    actor = Column(String, default="system", nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
