"""Governed API for AGRO-AI Field State, Decision Memory, and lifecycle transitions."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.intelligence_memory import (
    DecisionLifecycle,
    DecisionLifecycleEvent,
    DecisionSnapshot,
    FieldState,
)
from app.models.saas import Organization, OrganizationMembership, User
from app.services.commercial_control import require_feature
from app.services.decision_lifecycle import (
    LifecycleIdempotencyConflict,
    LifecycleTransitionError,
    transition_decision_lifecycle,
)
from app.services.evidence_reference_validator import EvidenceReferenceError, validate_evidence_references


router = APIRouter(prefix="/intelligence/memory", tags=["intelligence-memory"])
_WRITE_ROLES = {"owner", "admin", "manager", "operator"}
VerificationOutcome = Literal[
    "effective",
    "partially_effective",
    "ineffective",
    "matched",
    "partially_matched",
    "deviated",
    "failed",
    "agronomically_ineffective",
    "inconclusive",
    "no_change",
]


class RejectPayload(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class ExecutionEvidencePayload(BaseModel):
    execution_evidence_ids: list[str] = Field(min_length=1, max_length=50)


class VerificationPendingPayload(BaseModel):
    verification_status: str = Field(default="pending", min_length=2, max_length=80)


class VerificationPayload(BaseModel):
    verification_evidence_ids: list[str] = Field(min_length=1, max_length=50)
    outcome: VerificationOutcome
    verification_status: str = Field(default="complete", min_length=2, max_length=80)


class CancelPayload(BaseModel):
    reason: str = Field(default="Cancelled by an authorized operator.", min_length=2, max_length=2000)


def _organization_and_role(db: Session, tenant_id: str, user: User) -> tuple[Organization, str]:
    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    require_feature(db, org, "intelligence.ask", recommended_plan="professional")
    if org.owner_user_id == user.id:
        return org, "owner"
    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == tenant_id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == "active",
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org, str(membership.role or "viewer").casefold()


def _require_write_role(role: str) -> None:
    if role not in _WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "decision_lifecycle_write_forbidden", "message": "Your organization role is read-only for decision lifecycle changes."},
        )


def _idempotency_key(value: str | None) -> str:
    key = str(value or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": "idempotency_key_required", "message": "Idempotency-Key is required for lifecycle changes."},
        )
    if len(key) > 160:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Idempotency-Key is too long")
    return key


def _lifecycle(db: Session, tenant_id: str, lifecycle_id: str) -> DecisionLifecycle:
    row = db.query(DecisionLifecycle).filter(
        DecisionLifecycle.id == lifecycle_id,
        DecisionLifecycle.organization_id == tenant_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision lifecycle not found")
    return row


def _transition_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LifecycleIdempotencyConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "lifecycle_idempotency_conflict", "message": str(exc)})
    if isinstance(exc, LifecycleTransitionError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "lifecycle_transition_rejected", "message": str(exc)})
    if isinstance(exc, EvidenceReferenceError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "evidence_reference_invalid", "message": str(exc)})
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _field_state_body(row: FieldState) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "field_id": row.field_id,
        "block_id": row.block_id,
        "schema_version": row.schema_version,
        "revision": row.revision,
        "as_of_at": row.as_of_at.isoformat() if row.as_of_at else None,
        "source_cutoff_at": row.source_cutoff_at.isoformat() if row.source_cutoff_at else None,
        "state": row.state_json or {},
        "unknowns": row.unknowns_json or [],
        "conflicts": row.conflicts_json or [],
        "evidence_ids": row.evidence_ids_json or [],
        "state_hash": row.state_hash,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _snapshot_body(row: DecisionSnapshot, lifecycle: DecisionLifecycle | None = None, *, include_graph: bool = False) -> dict[str, Any]:
    body = {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "field_id": row.field_id,
        "block_id": row.block_id,
        "domain": row.domain,
        "task": row.task,
        "question": row.question,
        "field_state_revision_id": row.field_state_revision_id,
        "decision_schema_version": row.decision_schema_version,
        "grounding_schema_version": row.grounding_schema_version,
        "science_ruleset_version": row.science_ruleset_version,
        "evidence_ids": row.evidence_ids_json or [],
        "science_trace": row.science_trace_json or [],
        "decision": row.decision_json or {},
        "grounding_confidence": row.grounding_confidence,
        "snapshot_hash": row.snapshot_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "lifecycle": None if lifecycle is None else {
            "id": lifecycle.id,
            "state": lifecycle.state,
            "version": lifecycle.version,
            "requires_human_approval": lifecycle.requires_human_approval,
            "approved_at": lifecycle.approved_at.isoformat() if lifecycle.approved_at else None,
            "executed_at": lifecycle.executed_at.isoformat() if lifecycle.executed_at else None,
            "verified_at": lifecycle.verified_at.isoformat() if lifecycle.verified_at else None,
            "verification_status": lifecycle.verification_status,
            "outcome": lifecycle.outcome,
            "expires_at": lifecycle.expires_at.isoformat() if lifecycle.expires_at else None,
        },
    }
    if include_graph:
        body["evidence_graph"] = row.evidence_graph_json or {}
    return body


def _lifecycle_body(db: Session, row: DecisionLifecycle) -> dict[str, Any]:
    events = (
        db.query(DecisionLifecycleEvent)
        .filter(DecisionLifecycleEvent.lifecycle_id == row.id, DecisionLifecycleEvent.organization_id == row.organization_id)
        .order_by(DecisionLifecycleEvent.sequence.asc())
        .all()
    )
    return {
        "id": row.id,
        "decision_snapshot_id": row.decision_snapshot_id,
        "workspace_id": row.workspace_id,
        "state": row.state,
        "version": row.version,
        "requires_human_approval": row.requires_human_approval,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
        "rejection_reason": row.rejection_reason,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "verification_status": row.verification_status,
        "outcome": row.outcome,
        "events": [
            {
                "id": event.id,
                "sequence": event.sequence,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "event_type": event.event_type,
                "actor_type": event.actor_type,
                "actor_user_id": event.actor_user_id,
                "payload": event.payload_json or {},
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }


@router.get("/field-state")
def get_field_state(
    workspace_id: str | None = None,
    field_id: str | None = None,
    block_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    query = db.query(FieldState).filter(FieldState.organization_id == tenant_id)
    if workspace_id:
        query = query.filter(FieldState.workspace_id == workspace_id)
    if field_id:
        query = query.filter(FieldState.field_id == field_id)
    if block_id:
        query = query.filter(FieldState.block_id == block_id)
    rows = query.order_by(desc(FieldState.updated_at)).limit(limit).all()
    return {"items": [_field_state_body(row) for row in rows], "count": len(rows)}


@router.get("/decisions")
def list_decisions(
    workspace_id: str | None = None,
    field_id: str | None = None,
    block_id: str | None = None,
    domain: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    query = db.query(DecisionSnapshot).filter(DecisionSnapshot.organization_id == tenant_id)
    if workspace_id:
        query = query.filter(DecisionSnapshot.workspace_id == workspace_id)
    if field_id:
        query = query.filter(DecisionSnapshot.field_id == field_id)
    if block_id:
        query = query.filter(DecisionSnapshot.block_id == block_id)
    if domain:
        query = query.filter(DecisionSnapshot.domain == domain)
    rows = query.order_by(desc(DecisionSnapshot.created_at)).limit(limit).all()
    lifecycle_by_snapshot = {
        row.decision_snapshot_id: row
        for row in db.query(DecisionLifecycle).filter(
            DecisionLifecycle.organization_id == tenant_id,
            DecisionLifecycle.decision_snapshot_id.in_([item.id for item in rows] or [""]),
        ).all()
    }
    return {
        "items": [_snapshot_body(row, lifecycle_by_snapshot.get(row.id), include_graph=False) for row in rows],
        "count": len(rows),
    }


@router.get("/decisions/{snapshot_id}")
def get_decision(
    snapshot_id: str,
    include_evidence_graph: bool = False,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    row = db.query(DecisionSnapshot).filter(
        DecisionSnapshot.id == snapshot_id,
        DecisionSnapshot.organization_id == tenant_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")
    lifecycle = db.query(DecisionLifecycle).filter(
        DecisionLifecycle.decision_snapshot_id == row.id,
        DecisionLifecycle.organization_id == tenant_id,
    ).first()
    return _snapshot_body(row, lifecycle, include_graph=include_evidence_graph)


@router.get("/lifecycles/{lifecycle_id}")
def get_lifecycle(
    lifecycle_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    return _lifecycle_body(db, _lifecycle(db, tenant_id, lifecycle_id))


def _mutate(
    db: Session,
    *,
    tenant_id: str,
    lifecycle_id: str,
    user: User,
    role: str,
    idempotency_key: str | None,
    to_state: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _require_write_role(role)
    row = _lifecycle(db, tenant_id, lifecycle_id)
    try:
        lifecycle, _event, _created = transition_decision_lifecycle(
            db,
            row.id,
            to_state=to_state,
            event_type=event_type,
            actor_type="user",
            actor_user_id=user.id,
            idempotency_key=_idempotency_key(idempotency_key),
            payload=payload,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise _transition_error(exc) from exc
    return _lifecycle_body(db, lifecycle)


@router.post("/lifecycles/{lifecycle_id}/approve")
def approve_decision(
    lifecycle_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    return _mutate(db, tenant_id=tenant_id, lifecycle_id=lifecycle_id, user=user, role=role, idempotency_key=idempotency_key, to_state="approved", event_type="human_approved", payload={"source": "portal_or_api"})


@router.post("/lifecycles/{lifecycle_id}/reject")
def reject_decision(
    lifecycle_id: str,
    payload: RejectPayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    return _mutate(db, tenant_id=tenant_id, lifecycle_id=lifecycle_id, user=user, role=role, idempotency_key=idempotency_key, to_state="rejected", event_type="human_rejected", payload={"reason": payload.reason})


@router.post("/lifecycles/{lifecycle_id}/execution-pending")
def mark_execution_pending(
    lifecycle_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    return _mutate(db, tenant_id=tenant_id, lifecycle_id=lifecycle_id, user=user, role=role, idempotency_key=idempotency_key, to_state="execution_pending", event_type="execution_pending", payload={"source": "portal_or_api"})


@router.post("/lifecycles/{lifecycle_id}/executed")
def mark_executed(
    lifecycle_id: str,
    payload: ExecutionEvidencePayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    _require_write_role(role)
    try:
        refs = validate_evidence_references(
            db,
            tenant_id=tenant_id,
            evidence_ids=payload.execution_evidence_ids,
            allowed_types={"evidence_record", "field_observation"},
        )
    except Exception as exc:
        raise _transition_error(exc) from exc
    return _mutate(
        db,
        tenant_id=tenant_id,
        lifecycle_id=lifecycle_id,
        user=user,
        role=role,
        idempotency_key=idempotency_key,
        to_state="executed",
        event_type="execution_attested",
        payload={
            "execution_evidence_ids": [row.evidence_id for row in refs],
            "evidence_types": {row.evidence_id: row.evidence_type for row in refs},
            "source": "authorized_user_attestation",
        },
    )


@router.post("/lifecycles/{lifecycle_id}/verification-pending")
def mark_verification_pending(
    lifecycle_id: str,
    payload: VerificationPendingPayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    return _mutate(db, tenant_id=tenant_id, lifecycle_id=lifecycle_id, user=user, role=role, idempotency_key=idempotency_key, to_state="verification_pending", event_type="verification_started", payload={"verification_status": payload.verification_status})


@router.post("/lifecycles/{lifecycle_id}/verified")
def mark_verified(
    lifecycle_id: str,
    payload: VerificationPayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    _require_write_role(role)
    try:
        refs = validate_evidence_references(
            db,
            tenant_id=tenant_id,
            evidence_ids=payload.verification_evidence_ids,
            allowed_types={"evidence_record", "field_observation", "execution_verification"},
        )
    except Exception as exc:
        raise _transition_error(exc) from exc
    return _mutate(
        db,
        tenant_id=tenant_id,
        lifecycle_id=lifecycle_id,
        user=user,
        role=role,
        idempotency_key=idempotency_key,
        to_state="verified",
        event_type="verification_completed",
        payload={
            "verification_evidence_ids": [row.evidence_id for row in refs],
            "evidence_types": {row.evidence_id: row.evidence_type for row in refs},
            "outcome": payload.outcome,
            "verification_status": payload.verification_status,
            "source": "authorized_user_verification",
        },
    )


@router.post("/lifecycles/{lifecycle_id}/cancel")
def cancel_decision(
    lifecycle_id: str,
    payload: CancelPayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    return _mutate(db, tenant_id=tenant_id, lifecycle_id=lifecycle_id, user=user, role=role, idempotency_key=idempotency_key, to_state="cancelled", event_type="human_cancelled", payload={"reason": payload.reason})
