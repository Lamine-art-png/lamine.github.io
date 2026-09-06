"""Durable autonomy runtime models for AGRO-AI autonomous operations."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


class AutonomyProcedure(Base):
    __tablename__ = "autonomy_procedures"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    procedure_key = Column(String(120), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    name = Column(String(220), nullable=False)
    domain = Column(String(80), nullable=False, index=True)
    description = Column(Text, nullable=True)
    source = Column(String(40), nullable=False, default="system")
    active = Column(Boolean, nullable=False, default=True, index=True)
    trigger_types_json = Column(JSON, nullable=False, default=list)
    steps_json = Column(JSON, nullable=False, default=list)
    outcome_contract_json = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("organization_id", "procedure_key", "version", name="uq_autonomy_procedure_org_key_version"),
        Index("ix_autonomy_procedure_lookup", "organization_id", "procedure_key", "active", "version"),
    )


class AutonomyPolicy(Base):
    __tablename__ = "autonomy_policies"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    autonomy_level = Column(String(2), nullable=False, default="A4")
    action_class_caps_json = Column(JSON, nullable=False, default=dict)
    risk_caps_json = Column(JSON, nullable=False, default=dict)
    constraints_json = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("organization_id", "workspace_id", name="uq_autonomy_policy_scope"),
        Index("ix_autonomy_policy_scope", "organization_id", "workspace_id", "enabled"),
    )


class AutonomyRun(Base):
    __tablename__ = "autonomy_runs"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    procedure_id = Column(String, ForeignKey("autonomy_procedures.id", ondelete="RESTRICT"), nullable=False, index=True)
    procedure_key = Column(String(120), nullable=False, index=True)
    trigger_type = Column(String(80), nullable=False, index=True)
    trigger_ref = Column(String(255), nullable=True, index=True)
    status = Column(String(40), nullable=False, default="running", index=True)
    requested_autonomy_level = Column(String(2), nullable=False, default="A4")
    effective_autonomy_level = Column(String(2), nullable=False, default="A4")
    current_step_sequence = Column(Integer, nullable=False, default=0)
    eligible_for_autonomy = Column(Boolean, nullable=False, default=True, index=True)
    human_decision_count = Column(Integer, nullable=False, default=0)
    exception_count = Column(Integer, nullable=False, default=0)
    context_json = Column(JSON, nullable=False, default=dict)
    result_json = Column(JSON, nullable=False, default=dict)
    outcome_status = Column(String(80), nullable=True, index=True)
    verification_status = Column(String(80), nullable=True, index=True)
    failure_reason = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_autonomy_run_scope_status", "organization_id", "workspace_id", "status", "updated_at"),
        Index("ix_autonomy_run_trigger", "organization_id", "procedure_key", "trigger_type", "trigger_ref"),
    )


class AutonomyStep(Base):
    __tablename__ = "autonomy_steps"

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("autonomy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    step_key = Column(String(120), nullable=False)
    name = Column(String(220), nullable=False)
    step_type = Column(String(40), nullable=False, index=True)
    action_class = Column(String(60), nullable=False, default="intelligence", index=True)
    action_type = Column(String(120), nullable=True)
    risk_level = Column(String(20), nullable=False, default="low", index=True)
    minimum_autonomy_level = Column(String(2), nullable=False, default="A4")
    effective_autonomy_level = Column(String(2), nullable=True)
    status = Column(String(40), nullable=False, default="pending", index=True)
    approval_required = Column(Boolean, nullable=False, default=False)
    approved_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String(180), nullable=False, unique=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    input_json = Column(JSON, nullable=False, default=dict)
    output_json = Column(JSON, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_autonomy_step_run_sequence"),
        Index("ix_autonomy_step_run_status", "run_id", "status", "sequence"),
    )


class AutonomyEvent(Base):
    __tablename__ = "autonomy_events"

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("autonomy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String, ForeignKey("autonomy_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    actor = Column(String(160), nullable=False, default="system")
    payload_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_autonomy_event_run_time", "run_id", "created_at"),
        Index("ix_autonomy_event_scope_time", "organization_id", "created_at"),
    )
