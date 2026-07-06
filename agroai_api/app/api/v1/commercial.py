"""Customer-safe AGRO-AI commercial control-plane API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.services.commercial_control import customer_safe_entitlement_payload, feature_state
from app.services.entitlements import require_owner_or_admin
from app.services.quota import quota_snapshot


router = APIRouter(prefix="/commercial", tags=["commercial-control"])


CUSTOMER_CLASSES = {
    "individual_operator",
    "professional_operator",
    "operating_team",
    "network_program",
    "institutional_enterprise",
}


class CommercialProfileUpdate(BaseModel):
    customer_class: str | None = Field(default=None, max_length=80)
    organization_type: str | None = Field(default=None, max_length=80)


def _require_org(ctx: AuthContext):
    if not ctx.organization or not ctx.membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization, ctx.membership


@router.get("/state")
def commercial_state(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    return {
        "organization_id": org.id,
        "role": membership.role,
        "commercial": customer_safe_entitlement_payload(db, org),
        "usage": quota_snapshot(db, org),
    }


@router.get("/usage")
def commercial_usage(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    return quota_snapshot(db, org)


@router.get("/features/{feature_key:path}")
def commercial_feature(feature_key: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    return {"feature": feature_key, "state": feature_state(db, org, feature_key)}


@router.patch("/profile")
def update_commercial_profile(payload: CommercialProfileUpdate, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)
    if payload.customer_class is not None:
        customer_class = payload.customer_class.strip().lower()
        if customer_class not in CUSTOMER_CLASSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_customer_class", "allowed": sorted(CUSTOMER_CLASSES)},
            )
        org.customer_class = customer_class
    if payload.organization_type is not None:
        org.organization_type = payload.organization_type.strip().lower() or None
    db.commit()
    return {"commercial": customer_safe_entitlement_payload(db, org)}
