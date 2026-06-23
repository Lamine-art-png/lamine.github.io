"""SQLAlchemy models for deterministic agent workflow runs."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, JSON, String, Text

from app.db.base import Base


class AgentWorkflowRun(Base):
    __tablename__ = "agent_workflow_runs"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workbench_session_id = Column(String, nullable=True, index=True)
    workflow_type = Column(String, nullable=False, index=True)
    status = Column(String, default="completed", nullable=False, index=True)
    priority = Column(String, default="normal", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    actor = Column(String, default="system", nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    requires_human_approval = Column(Boolean, default=False, nullable=False, index=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


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
    requires_human_approval = Column(Boolean, default=False, nullable=False, index=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


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
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
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

