"""Governed, tenant-safe APIs for verified outcome learning."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.intelligence_memory_api import _idempotency_key, _organization_and_role, _require_write_role
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import User
from app.services.outcome_learning import (
    OutcomeLearningError,
    build_outcome_learning_summary,
    materialize_missing_verified_outcomes,
)


router = APIRouter(prefix="/intelligence/memory/learning", tags=["intelligence-learning"])


@router.get("/summary")
def learning_summary(
    workspace_id: str | None = None,
    field_id: str | None = None,
    domain: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    return build_outcome_learning_summary(
        db,
        organization_id=tenant_id,
        workspace_id=workspace_id,
        field_id=field_id,
        domain=domain,
        limit=limit,
    )


@router.post("/materialize")
def materialize_learning_evidence(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _org, role = _organization_and_role(db, tenant_id, user)
    _require_write_role(role)
    request_key = _idempotency_key(idempotency_key)
    try:
        result = materialize_missing_verified_outcomes(db, organization_id=tenant_id)
        db.commit()
    except OutcomeLearningError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "outcome_learning_rejected", "message": str(exc)},
        ) from exc
    except Exception:
        db.rollback()
        raise
    return {
        "status": "completed",
        "idempotency_key": request_key,
        **result,
        "automatic_parameter_updates": False,
        "automatic_policy_updates": False,
    }
