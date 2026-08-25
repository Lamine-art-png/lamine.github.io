"""Tenant-safe immutable decision history explanations."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.intelligence_memory_api import _organization_and_role
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.intelligence_memory import DecisionSnapshot
from app.models.saas import User
from app.services.decision_history import compare_decision_snapshots, previous_decision_snapshot


router = APIRouter(prefix="/intelligence/memory", tags=["intelligence-history"])


@router.get("/decisions/{snapshot_id}/changes")
def decision_changes(
    snapshot_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    current = (
        db.query(DecisionSnapshot)
        .filter(
            DecisionSnapshot.id == snapshot_id,
            DecisionSnapshot.organization_id == tenant_id,
        )
        .first()
    )
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")
    previous = previous_decision_snapshot(db, current)
    return compare_decision_snapshots(current, previous)
