"""Invitation link endpoints: preview, accept with an existing account, accept
with a new account. The organization and role always come from the invitation
row identified by the single-use link token, never from the client."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.auth import (
    REGISTER_RATE_LIMIT,
    SELF_SERVICE_PRIVACY_URL,
    SELF_SERVICE_PRIVACY_VERSION,
    SELF_SERVICE_TERMS_URL,
    SELF_SERVICE_TERMS_VERSION,
    _SELF_SERVICE_ACCEPTED_VERSION_PAIRS,
    _request_metadata,
    _session_response,
    pwd_context,
)
from app.core.rate_limiting import limiter
from app.db.base import get_db
from app.models.saas import Organization, SelfServiceLegalAcceptance, User, UserPreference
from app.services import team_invitations
from app.services.password_policy import password_policy_error
from app.services.security_audit import privacy_hash, record_security_event

router = APIRouter(tags=["team-invitations"])

INVITEE_ACCEPTANCE_TEXT = "I agree to the AGRO-AI Terms of Service and acknowledge the Privacy Policy."
INVITATION_LINK_RATE_LIMIT = "20/minute"


class InvitationTokenRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class InvitationNewAccountRequest(InvitationTokenRequest):
    name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=256)
    terms_accepted: bool = False
    terms_version: str | None = Field(default=None, max_length=40)
    privacy_version: str | None = Field(default=None, max_length=40)
    locale: str | None = Field(default=None, max_length=24)


@router.post("/team/invitations/preview")
@limiter.limit(INVITATION_LINK_RATE_LIMIT)
def preview_invitation(payload: InvitationTokenRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    row = team_invitations.redeemable_invitation(db, payload.token)
    org = db.get(Organization, row.organization_id)
    return {
        "organization_name": org.name if org else None,
        "role": row.role,
        "email": row.email,
        "account_exists": db.query(User).filter(User.email == row.email).first() is not None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "locale": row.locale,
    }


@router.post("/team/invitations/accept")
@limiter.limit(INVITATION_LINK_RATE_LIMIT)
def accept_invitation(payload: InvitationTokenRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = team_invitations.redeemable_invitation(db, payload.token, lock=True)
    membership = team_invitations.accept_invitation_for_user(db, row=row, user=user)
    org = db.get(Organization, row.organization_id)
    ip_address, user_agent = _request_metadata(request)
    record_security_event(
        db, event_type="team.invitation.accepted", outcome="accepted", organization_id=org.id, user_id=user.id,
        subject=user.email, ip_address=ip_address, user_agent=user_agent,
        metadata={"invitation_id": row.id, "role": membership.role, "account": "existing"},
    )
    db.commit()
    db.refresh(membership)
    return {"status": "accepted", **_session_response(user, org, membership)}


@router.post("/team/invitations/accept-new-account", status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_RATE_LIMIT)
def accept_invitation_new_account(payload: InvitationNewAccountRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    if payload.terms_accepted is not True or (payload.terms_version, payload.privacy_version) not in _SELF_SERVICE_ACCEPTED_VERSION_PAIRS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "legal_acceptance_required", "message": "You must accept the current AGRO-AI Terms of Service and acknowledge the Privacy Policy to create an account."},
        )
    row = team_invitations.redeemable_invitation(db, payload.token, lock=True)
    if db.query(User).filter(User.email == row.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "account_exists", "message": "An AGRO-AI account already exists for this email. Sign in to accept the invitation."},
        )
    policy_error = password_policy_error(payload.password, email=row.email)
    if policy_error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "password_policy_failed", "message": policy_error})

    now = datetime.utcnow()
    # Possession of the single-use link delivered to this mailbox proves the
    # address, so the account is created verified.
    user = User(
        email=row.email,
        name=payload.name.strip(),
        password_hash=pwd_context.hash(payload.password),
        email_verification_status="verified",
        email_verified_at=now,
        account_status="active",
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "account_exists", "message": "An AGRO-AI account already exists for this email. Sign in to accept the invitation."})
    locale = payload.locale or row.locale
    db.add(UserPreference(user_id=user.id, locale=locale))
    membership = team_invitations.accept_invitation_for_user(db, row=row, user=user)
    ip_address, user_agent = _request_metadata(request)
    db.add(SelfServiceLegalAcceptance(
        organization_id=row.organization_id,
        user_id=user.id,
        terms_version=SELF_SERVICE_TERMS_VERSION,
        privacy_version=SELF_SERVICE_PRIVACY_VERSION,
        terms_url=SELF_SERVICE_TERMS_URL,
        privacy_url=SELF_SERVICE_PRIVACY_URL,
        locale=locale or "en",
        acceptance_text=INVITEE_ACCEPTANCE_TEXT,
        authority_confirmed=False,
        ip_hash=privacy_hash(ip_address, "ip"),
        user_agent_hash=privacy_hash(user_agent, "user-agent"),
        accepted_at=now,
    ))
    record_security_event(
        db, event_type="legal.clickwrap.accepted", outcome="accepted", organization_id=row.organization_id, user_id=user.id,
        subject=user.email, ip_address=ip_address, user_agent=user_agent,
        metadata={"terms_version": SELF_SERVICE_TERMS_VERSION, "privacy_version": SELF_SERVICE_PRIVACY_VERSION, "locale": locale, "authority_confirmed": False, "invitation_id": row.id},
    )
    record_security_event(
        db, event_type="team.invitation.accepted", outcome="accepted", organization_id=row.organization_id, user_id=user.id,
        subject=user.email, ip_address=ip_address, user_agent=user_agent,
        metadata={"invitation_id": row.id, "role": membership.role, "account": "new"},
    )
    db.commit()
    db.refresh(membership)
    org = db.get(Organization, row.organization_id)
    return {"status": "accepted", **_session_response(user, org, membership)}
