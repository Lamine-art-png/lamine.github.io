"""Durable state and decision memory for AGRO-AI intelligence.

Only FieldState and DecisionLifecycle are mutable current heads. Historical
FieldStateRevision, DecisionSnapshot, and DecisionLifecycleEvent rows are
append-only. ORM mutation guards reinforce the database foreign-key policy.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, event

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


class ImmutableIntelligenceMemoryError(RuntimeError):
    pass


class FieldState(Base):
    __tablename__ = "field_states"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    field_id = Column(String, nullable=True, index=True)
    block_id = Column(String, nullable=True, index=True)
    scope_key = Column(String(512), nullable=False)
    schema_version = Column(String(80), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    as_of_at = Column(DateTime, nullable=False, index=True)
    source_cutoff_at = Column(DateTime, nullable=True)
    state_json = Column(JSON, nullable=False, default=dict)
    unknowns_json = Column(JSON, nullable=False, default=list)
    conflicts_json = Column(JSON, nullable=False, default=list)
    evidence_ids_json = Column(JSON, nullable=False, default=list)
    state_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "scope_key", name="uq_field_state_org_scope"),
        Index("ix_field_state_scope", "organization_id", "workspace_id", "field_id", "block_id"),
    )


class FieldStateRevision(Base):
    __tablename__ = "field_state_revisions"

    id = Column(String, primary_key=True, default=new_id, index=True)
    field_state_id = Column(String, ForeignKey("field_states.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    field_id = Column(String, nullable=True, index=True)
    block_id = Column(String, nullable=True, index=True)
    revision = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    as_of_at = Column(DateTime, nullable=False, index=True)
    source_cutoff_at = Column(DateTime, nullable=True)
    state_json = Column(JSON, nullable=False, default=dict)
    unknowns_json = Column(JSON, nullable=False, default=list)
    conflicts_json = Column(JSON, nullable=False, default=list)
    evidence_ids_json = Column(JSON, nullable=False, default=list)
    state_hash = Column(String(64), nullable=False)
    previous_revision_hash = Column(String(64), nullable=True)
    created_by_intelligence_run_id = Column(String, ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("field_state_id", "revision", name="uq_field_state_revision_number"),
        UniqueConstraint("field_state_id", "state_hash", name="uq_field_state_revision_hash"),
        Index("ix_field_state_revision_scope", "organization_id", "workspace_id", "field_id", "block_id", "revision"),
    )


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"

    id = Column(String, primary_key=True, default=new_id, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    field_state_revision_id = Column(String, ForeignKey("field_state_revisions.id", ondelete="SET NULL"), nullable=True, index=True)
    intelligence_run_id = Column(String, ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    legacy_decision_run_id = Column(String, nullable=True, index=True)
    field_id = Column(String, nullable=True, index=True)
    block_id = Column(String, nullable=True, index=True)
    domain = Column(String(80), nullable=False, index=True)
    task = Column(String(120), nullable=False, index=True)
    question = Column(Text, nullable=True)
    decision_schema_version = Column(String(80), nullable=False)
    grounding_schema_version = Column(String(80), nullable=False)
    science_ruleset_version = Column(String(80), nullable=False)
    evidence_graph_json = Column(JSON, nullable=False)
    evidence_ids_json = Column(JSON, nullable=False, default=list)
    science_trace_json = Column(JSON, nullable=False, default=list)
    decision_json = Column(JSON, nullable=False)
    grounding_confidence = Column(Float, nullable=False)
    model_provider = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    reasoning_effort = Column(String, nullable=True)
    policy_version = Column(String(80), nullable=False)
    action_policy_version = Column(String(80), nullable=False)
    snapshot_hash = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_decision_snapshot_idempotency"),
        Index("ix_decision_snapshot_scope", "organization_id", "workspace_id", "field_id", "block_id", "created_at"),
        Index("ix_decision_snapshot_domain", "organization_id", "domain", "created_at"),
    )


class DecisionLifecycle(Base):
    __tablename__ = "decision_lifecycles"

    id = Column(String, primary_key=True, default=new_id, index=True)
    decision_snapshot_id = Column(String, ForeignKey("decision_snapshots.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    state = Column(String(40), nullable=False, default="proposed", index=True)
    version = Column(Integer, nullable=False, default=1)
    requires_human_approval = Column(Boolean, nullable=False, default=True)
    approved_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    executed_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verification_status = Column(String(40), nullable=True, index=True)
    outcome = Column(String(80), nullable=True, index=True)
    legacy_execution_verification_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_decision_lifecycle_state", "organization_id", "state", "updated_at"),)


class DecisionLifecycleEvent(Base):
    __tablename__ = "decision_lifecycle_events"

    id = Column(String, primary_key=True, default=new_id, index=True)
    lifecycle_id = Column(String, ForeignKey("decision_lifecycles.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence = Column(Integer, nullable=False)
    from_state = Column(String(40), nullable=True)
    to_state = Column(String(40), nullable=False)
    event_type = Column(String(80), nullable=False, index=True)
    actor_type = Column(String(40), nullable=False)
    actor_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    payload_json = Column(JSON, nullable=False, default=dict)
    idempotency_key = Column(String(160), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("lifecycle_id", "sequence", name="uq_decision_lifecycle_event_sequence"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_decision_lifecycle_event_idempotency"),
        Index("ix_decision_lifecycle_event_time", "lifecycle_id", "created_at"),
    )


def _reject_immutable_mutation(_mapper, _connection, target) -> None:
    raise ImmutableIntelligenceMemoryError(f"{target.__class__.__name__} is append-only and cannot be mutated")


def _reject_historical_head_delete(_mapper, _connection, target) -> None:
    raise ImmutableIntelligenceMemoryError(f"{target.__class__.__name__} cannot be deleted because it anchors durable history")


for _immutable_cls in (FieldStateRevision, DecisionSnapshot, DecisionLifecycleEvent):
    event.listen(_immutable_cls, "before_update", _reject_immutable_mutation)
    event.listen(_immutable_cls, "before_delete", _reject_immutable_mutation)

event.listen(FieldState, "before_delete", _reject_historical_head_delete)
event.listen(DecisionLifecycle, "before_delete", _reject_historical_head_delete)
