"""Tenant- and scope-safe evidence browser for governed lifecycle transitions."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.intelligence_memory_api import _organization_and_role
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.field_intelligence import FieldObservation
from app.models.intelligence_memory import DecisionLifecycle, DecisionSnapshot
from app.models.operational_records import EvidenceRecord
from app.models.saas import User


router = APIRouter(prefix="/intelligence/memory", tags=["intelligence-evidence"])
EvidencePurpose = Literal["execution", "verification"]
_PROOF_QUALITY = ["verified", "accepted", "validated", "complete", "good", "ok", "usable", "live"]


def _scope_snapshot(db: Session, tenant_id: str, lifecycle_id: str) -> tuple[DecisionLifecycle, DecisionSnapshot]:
    lifecycle = (
        db.query(DecisionLifecycle)
        .filter(
            DecisionLifecycle.id == lifecycle_id,
            DecisionLifecycle.organization_id == tenant_id,
        )
        .first()
    )
    if lifecycle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision lifecycle not found")
    snapshot = (
        db.query(DecisionSnapshot)
        .filter(
            DecisionSnapshot.id == lifecycle.decision_snapshot_id,
            DecisionSnapshot.organization_id == tenant_id,
        )
        .first()
    )
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Decision snapshot is unavailable")
    return lifecycle, snapshot


def _record_scope(query, model, snapshot: DecisionSnapshot):
    if snapshot.workspace_id:
        query = query.filter(model.workspace_id == snapshot.workspace_id)
    if snapshot.field_id:
        query = query.filter(model.field_id == snapshot.field_id)
    if snapshot.block_id and hasattr(model, "block_id"):
        query = query.filter(model.block_id == snapshot.block_id)
    return query


@router.get("/lifecycles/{lifecycle_id}/eligible-evidence")
def eligible_lifecycle_evidence(
    lifecycle_id: str,
    purpose: EvidencePurpose = "execution",
    limit: int = Query(50, ge=1, le=100),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    lifecycle, snapshot = _scope_snapshot(db, tenant_id, lifecycle_id)

    records_query = db.query(EvidenceRecord).filter(
        EvidenceRecord.tenant_id == tenant_id,
        EvidenceRecord.quality_status.in_(_PROOF_QUALITY),
    )
    records_query = _record_scope(records_query, EvidenceRecord, snapshot)
    records = records_query.order_by(desc(EvidenceRecord.occurred_at), desc(EvidenceRecord.created_at)).limit(limit).all()

    observations_query = db.query(FieldObservation).filter(
        FieldObservation.tenant_id == tenant_id,
        FieldObservation.status == "completed",
    )
    observations_query = _record_scope(observations_query, FieldObservation, snapshot)
    observations = observations_query.order_by(desc(FieldObservation.occurred_at), desc(FieldObservation.created_at)).limit(limit).all()

    items: list[dict[str, Any]] = []
    for row in records:
        items.append(
            {
                "id": row.id,
                "type": "evidence_record",
                "title": row.title,
                "summary": row.summary,
                "quality_status": row.quality_status,
                "confidence": row.confidence,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                "field_id": row.field_id,
                "block_id": row.block_id,
                "citation_label": row.citation_label,
            }
        )
    for row in observations:
        items.append(
            {
                "id": row.id,
                "type": "field_observation",
                "title": row.summary or row.event_type or "Field observation",
                "summary": row.corrected_transcript or row.transcript or row.summary or "",
                "quality_status": row.status,
                "confidence": row.confidence,
                "occurred_at": (row.occurred_at or row.observed_at).isoformat() if (row.occurred_at or row.observed_at) else None,
                "field_id": row.field_id,
                "block_id": row.block_id,
                "citation_label": "Field Intelligence observation",
            }
        )

    items.sort(key=lambda item: str(item.get("occurred_at") or ""), reverse=True)
    return {
        "purpose": purpose,
        "lifecycle_id": lifecycle.id,
        "decision_snapshot_id": snapshot.id,
        "scope": {
            "workspace_id": snapshot.workspace_id,
            "field_id": snapshot.field_id,
            "block_id": snapshot.block_id,
        },
        "items": items[:limit],
        "count": min(len(items), limit),
        "accepted_types": ["evidence_record", "field_observation"],
        "requires_explicit_selection": True,
    }
