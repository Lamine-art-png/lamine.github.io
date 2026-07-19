from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.rate_limiting import limiter
from app.db.base import get_db
from app.models.saas import AccountAccessAppeal, OrganizationMembership, User
from app.services.account_access_email import send_appeal_link, send_appeal_receipt
from app.services.security_audit import record_security_event

router = APIRouter(prefix="/access-appeals", tags=["access-appeals"])
logger = logging.getLogger(__name__)
RESTRICTED_ACCOUNT_STATUSES = {"suspended_pending_appeal", "verification_required", "suspended"}
OPEN_APPEAL_STATUSES = {"link_sent", "pending", "additional_information_required"}
GENERIC_RESPONSE = "If the account is eligible for an appeal, a secure link has been sent."


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None), request.headers.get("user-agent")


def _organization_for_user(db: Session, user: User):
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.created_at.asc())
        .first()
    )
    return membership.organization if membership else None


def _appeal_from_token(db: Session, token: str, *, allow_used: bool = False) -> AccountAccessAppeal:
    appeal = db.query(AccountAccessAppeal).filter(AccountAccessAppeal.token_hash == _hash_token(token)).first()
    if not appeal or appeal.token_expires_at < datetime.utcnow() or (appeal.token_used_at and not allow_used):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "appeal_link_invalid",
                "message": "This appeal link is invalid or expired. Request a new secure link.",
            },
        )
    return appeal


class AppealLinkRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email required")
        return value


class AppealSubmission(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    professional_role: str = Field(min_length=2, max_length=180)
    organization_name: str = Field(min_length=2, max_length=180)
    website_url: str | None = Field(default=None, max_length=500)
    professional_profile_url: str | None = Field(default=None, max_length=500)
    agricultural_use_case: str = Field(min_length=40, max_length=4000)
    acres_or_sites: str = Field(min_length=2, max_length=300)
    planned_data_sources: str = Field(min_length=10, max_length=2000)
    explanation: str = Field(min_length=20, max_length=3000)
    supporting_evidence_url: str | None = Field(default=None, max_length=500)

    @field_validator("website_url", "professional_profile_url", "supporting_evidence_url")
    @classmethod
    def clean_optional_url(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        if not cleaned.startswith(("https://", "http://")):
            raise ValueError("URL must start with https:// or http://")
        return cleaned


@router.post("/request")
@limiter.limit("3/minute")
def request_appeal_link(payload: AppealLinkRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or user.account_status not in RESTRICTED_ACCOUNT_STATUSES:
        return {"message": GENERIC_RESPONSE}

    organization = _organization_for_user(db, user)
    appeal = (
        db.query(AccountAccessAppeal)
        .filter(AccountAccessAppeal.user_id == user.id, AccountAccessAppeal.status.in_(OPEN_APPEAL_STATUSES))
        .order_by(AccountAccessAppeal.created_at.desc())
        .first()
    )
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    if appeal is None:
        appeal = AccountAccessAppeal(
            user_id=user.id,
            organization_id=organization.id if organization else None,
            token_hash=_hash_token(token),
            token_expires_at=now + timedelta(hours=48),
            status="link_sent",
            created_at=now,
            updated_at=now,
        )
        db.add(appeal)
    else:
        appeal.token_hash = _hash_token(token)
        appeal.token_expires_at = now + timedelta(hours=48)
        appeal.token_used_at = None
        if appeal.status not in {"pending", "additional_information_required"}:
            appeal.status = "link_sent"
        appeal.updated_at = now
    db.flush()

    ip_address, user_agent = _request_metadata(request)
    record_security_event(
        db,
        event_type="access_appeal_link",
        outcome="requested",
        organization_id=organization.id if organization else None,
        user_id=user.id,
        subject=user.email,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"appeal_id": appeal.id},
    )
    result = send_appeal_link(user, appeal, token)
    if result.get("ok"):
        user.access_restriction_notified_at = now
    db.commit()
    return {"message": GENERIC_RESPONSE}


@router.get("/form/{token}")
@limiter.limit("20/minute")
def appeal_form(token: str, request: Request, db: Session = Depends(get_db)) -> dict:
    appeal = _appeal_from_token(db, token)
    user = db.get(User, appeal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return {
        "appeal_id": appeal.id,
        "status": appeal.status,
        "masked_email": _mask_email(user.email),
        "account_name": user.name,
        "expires_at": appeal.token_expires_at.isoformat(),
        "form": {
            "full_name": appeal.full_name or user.name or "",
            "professional_role": appeal.professional_role or "",
            "organization_name": appeal.organization_name or (appeal.organization.name if appeal.organization else ""),
            "website_url": appeal.website_url or "",
            "professional_profile_url": appeal.professional_profile_url or "",
            "agricultural_use_case": appeal.agricultural_use_case or "",
            "acres_or_sites": appeal.acres_or_sites or "",
            "planned_data_sources": appeal.planned_data_sources or "",
            "explanation": appeal.explanation or "",
            "supporting_evidence_url": appeal.supporting_evidence_url or "",
        },
    }


@router.post("/submit/{token}")
@limiter.limit("5/minute")
def submit_appeal(
    token: str,
    payload: AppealSubmission,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    appeal = _appeal_from_token(db, token)
    user = db.get(User, appeal.user_id)
    if not user or user.account_status not in RESTRICTED_ACCOUNT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "appeal_not_available",
                "message": "This account is not currently eligible for an access appeal.",
            },
        )

    now = datetime.utcnow()
    for field in (
        "full_name",
        "professional_role",
        "organization_name",
        "website_url",
        "professional_profile_url",
        "agricultural_use_case",
        "acres_or_sites",
        "planned_data_sources",
        "explanation",
        "supporting_evidence_url",
    ):
        setattr(appeal, field, getattr(payload, field))
    appeal.status = "pending"
    appeal.submitted_at = now
    appeal.token_used_at = now
    appeal.updated_at = now

    organization = appeal.organization or _organization_for_user(db, user)
    ip_address, user_agent = _request_metadata(request)
    record_security_event(
        db,
        event_type="access_appeal",
        outcome="submitted",
        organization_id=organization.id if organization else None,
        user_id=user.id,
        subject=user.email,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"appeal_id": appeal.id},
    )
    db.commit()
    try:
        send_appeal_receipt(user)
    except Exception:
        logger.exception("Access appeal receipt delivery failed appeal_id=%s", appeal.id)
    return {
        "status": "pending",
        "message": "Your access appeal has been submitted. The account remains restricted while it is reviewed.",
    }
