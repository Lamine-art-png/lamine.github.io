"""Enterprise Portal customer legal-document and reacceptance API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.services.customer_legal import (
    acceptance_is_current,
    current_documents,
    latest_acceptance,
    record_acceptance,
    validate_clickwrap,
)


router = APIRouter(prefix="/legal", tags=["legal"])


class AcceptanceRequest(BaseModel):
    event_type: Literal["invite", "reaccept"] = "reaccept"
    terms_version: str = Field(min_length=1, max_length=80)
    privacy_version: str = Field(min_length=1, max_length=80)
    accepted_terms: bool
    acknowledged_privacy: bool
    authority_confirmed: bool


@router.get("/documents/current")
def get_current_documents() -> dict:
    return current_documents()


@router.get("/status")
def legal_status(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    assert ctx.organization is not None
    row = latest_acceptance(db, organization_id=ctx.organization.id, user_id=ctx.user.id)
    return {
        "current": acceptance_is_current(row),
        "latest_acceptance_id": row.id if row else None,
        "terms_version": row.terms_version if row else None,
        "privacy_version": row.privacy_version if row else None,
        "accepted_at": row.accepted_at.isoformat() if row else None,
        "documents": current_documents(),
    }


@router.post("/acceptances", status_code=status.HTTP_201_CREATED)
def accept_current_documents(
    payload: AcceptanceRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    assert ctx.organization is not None
    validate_clickwrap(
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
        accepted_terms=payload.accepted_terms,
        acknowledged_privacy=payload.acknowledged_privacy,
        authority_confirmed=payload.authority_confirmed,
    )
    row = record_acceptance(
        db,
        request=request,
        organization_id=ctx.organization.id,
        user_id=ctx.user.id,
        subject_email=ctx.user.email,
        event_type=payload.event_type,
    )
    db.commit()
    return {
        "status": "accepted",
        "acceptance_id": row.id,
        "terms_version": row.terms_version,
        "privacy_version": row.privacy_version,
        "accepted_at": row.accepted_at.isoformat(),
    }
