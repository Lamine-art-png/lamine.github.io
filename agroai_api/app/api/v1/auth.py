
import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthContext,
    get_auth_context,
    get_current_user,
    get_current_user_optional,
    is_platform_admin_user,
    require_approved_organization,
)
from app.core.config import settings
from app.core.rate_limiting import limiter
from app.core.security import create_access_token
from app.db.base import get_db
from app.models.saas import (
    Organization,
    OrganizationMembership,
    OrganizationVerificationProfile,
    User,
    Workspace,
)
from app.services.account_verification import (
    VerificationInput,
    evaluate_organization,
    verification_enforcement_enabled,
)
from app.services.email_verification import confirm_verification, create_verification_token, send_or_log_verification
from app.services.entitlements import serialize_entitlements
from app.services.evaluation_seed import ensure_evaluation_context
from app.services.identity_vault import encrypt_phone
from app.services.password_policy import password_policy_error
from app.services.security_audit import record_security_event

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)

GENERIC_VERIFICATION_MESSAGE = "If an account exists, we sent a verification email."
APPROVED_ORGANIZATION_STATUSES = {"approved", "approved_legacy"}
_PRODUCTION_RATE_LIMITS = str(getattr(settings, "APP_ENV", "development") or "development").strip().lower() in {"production", "prod"}
REGISTER_RATE_LIMIT = "5/minute" if _PRODUCTION_RATE_LIMITS else "1000/minute"
LOGIN_RATE_LIMIT = "10/minute" if _PRODUCTION_RATE_LIMITS else "1000/minute"
VERIFICATION_REQUEST_RATE_LIMIT = "3/minute" if _PRODUCTION_RATE_LIMITS else "1000/minute"
VERIFICATION_CONFIRM_RATE_LIMIT = "10/minute" if _PRODUCTION_RATE_LIMITS else "1000/minute"


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    name: str | None = None
    organization_name: str = Field(min_length=2, max_length=180)
    workspace_name: str = Field(default="Evaluation workspace", min_length=2, max_length=180)
    crop: str | None = None
    region: str | None = None
    organization_type: str | None = None
    professional_role: str | None = None
    phone_number: str | None = None
    website_url: str | None = None
    professional_profile_url: str | None = None
    country: str | None = None
    operating_region: str | None = None
    acres_or_sites: str | None = None
    primary_crops: str | None = None
    intended_use: str | None = None
    planned_data_sources: str | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email required")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email required")
        return value


class EmailVerificationRequest(BaseModel):
    email: str | None = None

    @field_validator("email")
    @classmethod
    def valid_optional_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email required")
        return value


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=12)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "organization"


def _unique_slug(db: Session, name: str) -> str:
    base = _slugify(name)
    slug = base
    suffix = 2
    while db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _first_workspace(db: Session, org_id: str) -> Workspace | None:
    return (
        db.query(Workspace)
        .filter(Workspace.organization_id == org_id)
        .order_by(Workspace.created_at.asc())
        .first()
    )


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    )
    ip_address = forwarded_ip or (request.client.host if request.client else None) or "unknown"
    return ip_address, request.headers.get("user-agent")


def _organization_verification_payload(org: Organization) -> dict:
    profile = getattr(org, "verification_profile", None)
    return {
        "verification_id": getattr(profile, "id", None),
        "status": org.verification_status,
        "score": org.verification_score,
        "engine_version": org.verification_engine_version,
        "verified_at": org.verified_at.isoformat() if org.verified_at else None,
        "email_domain_type": getattr(profile, "domain_classification", None),
        "phone_last4": getattr(profile, "phone_last4", None),
    }


def _organization_payload(org: Organization, role: str) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "plan": org.plan,
        "subscription_status": org.subscription_status,
        "role": role,
        "verification": _organization_verification_payload(org),
    }


def _session_response(user: User, org: Organization, membership: OrganizationMembership) -> dict:
    require_approved_organization(org)
    token = create_access_token({"sub": user.id, "tenant_id": org.id, "org_id": org.id, "role": membership.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "is_active": user.is_active,
            "account_status": user.account_status,
        },
        "current_organization": _organization_payload(org, membership.role),
        "organization_verification": _organization_verification_payload(org),
        "entitlements": serialize_entitlements(org),
        "platform_admin": is_platform_admin_user(user),
    }


def _verification_payload(user: User) -> dict:
    return {
        "email": user.email,
        "status": user.email_verification_status,
        "verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
    }


def _best_effort_send_verification(db: Session, user: User) -> dict:
    """Create/send a verification token without letting delivery issues break auth UX."""

    try:
        token = create_verification_token(db, user)
        delivery = send_or_log_verification(db, user, token)
        db.commit()
        return delivery
    except Exception:
        db.rollback()
        logger.exception("Email verification delivery failed for user_id=%s", getattr(user, "id", None))
        return {"delivery": "received", "provider_configured": False}


def _registration_evidence_complete(payload: RegisterRequest) -> bool:
    return all(
        str(value or "").strip()
        for value in (
            payload.name,
            payload.organization_type,
            payload.professional_role,
            payload.phone_number,
            payload.country,
            payload.operating_region or payload.region,
            payload.acres_or_sites,
            payload.primary_crops or payload.crop,
            payload.intended_use,
            payload.planned_data_sources,
        )
    ) and bool(str(payload.website_url or payload.professional_profile_url or "").strip())


def _verification_input(payload: RegisterRequest) -> VerificationInput:
    return VerificationInput(
        email=payload.email,
        name=payload.name,
        organization_name=payload.organization_name,
        organization_type=payload.organization_type,
        professional_role=payload.professional_role,
        phone_number=payload.phone_number,
        website_url=payload.website_url,
        professional_profile_url=payload.professional_profile_url,
        country=payload.country,
        operating_region=payload.operating_region or payload.region,
        acres_or_sites=payload.acres_or_sites,
        primary_crops=payload.primary_crops or payload.crop,
        intended_use=payload.intended_use,
        planned_data_sources=payload.planned_data_sources,
    )


def _promote_verified_organization(user: User, org: Organization) -> None:
    if user.email_verification_status == "verified" and user.email_verified_at:
        if org.verification_status == "preapproved_pending_email":
            org.verification_status = "approved"
            org.verified_at = datetime.utcnow()
        if org.verification_status in APPROVED_ORGANIZATION_STATUSES:
            user.account_status = "active"


def _register_failure(
    db: Session,
    request: Request,
    *,
    email: str,
    reason_codes: list[str] | tuple[str, ...],
    score: int | None = None,
) -> None:
    ip_address, user_agent = _request_metadata(request)
    record_security_event(
        db,
        event_type="registration_verification",
        outcome="rejected",
        subject=email,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"reason_codes": list(reason_codes), "score": score},
    )
    db.commit()


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_RATE_LIMIT)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with that email already exists")

    policy_error = password_policy_error(payload.password, email=email)
    if policy_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "password_policy_failed", "message": policy_error},
        )

    enforce_verification = verification_enforcement_enabled()
    evidence_complete = _registration_evidence_complete(payload)
    decision = evaluate_organization(_verification_input(payload)) if (enforce_verification or evidence_complete) else None

    if enforce_verification and not evidence_complete:
        reason_codes = ["complete_organization_verification_required"]
        _register_failure(db, request, email=email, reason_codes=reason_codes)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "organization_verification_rejected",
                "message": "Live portal access is reserved for verifiable agricultural organizations and professionals.",
                "reason_codes": reason_codes,
            },
        )

    if decision is not None and not decision.approved:
        _register_failure(db, request, email=email, reason_codes=decision.reason_codes, score=decision.score)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "organization_verification_rejected",
                "message": "We could not verify a genuine agricultural operation from the information supplied.",
                "reason_codes": list(decision.reason_codes),
            },
        )

    strict_registration = decision is not None and decision.approved
    verification_status = decision.status if strict_registration else "approved_legacy"
    user = User(
        email=email,
        name=payload.name,
        password_hash=pwd_context.hash(payload.password),
        email_verification_status="unverified",
        account_status="pending_email" if strict_registration else "active",
    )
    db.add(user)
    db.flush()

    now = datetime.utcnow()
    org = Organization(
        name=payload.organization_name,
        slug=_unique_slug(db, payload.organization_name),
        owner_user_id=user.id,
        plan="free",
        subscription_status="inactive",
        organization_type=payload.organization_type,
        verification_status=verification_status,
        verification_score=decision.score if decision else None,
        verification_reason_codes_json=list(decision.reason_codes) if decision else [],
        verification_engine_version=decision.engine_version if decision else "legacy-pre-2026-07-20",
        verification_submitted_at=now,
        verified_at=now if verification_status == "approved_legacy" else None,
    )
    db.add(org)
    db.flush()

    if strict_registration and decision is not None:
        profile = OrganizationVerificationProfile(
            organization_id=org.id,
            professional_role=str(payload.professional_role or "").strip(),
            organization_type=str(payload.organization_type or "").strip(),
            website_url=str(payload.website_url or "").strip() or None,
            professional_profile_url=str(payload.professional_profile_url or "").strip() or None,
            country=str(payload.country or "").strip(),
            operating_region=str(payload.operating_region or payload.region or "").strip(),
            acres_or_sites=str(payload.acres_or_sites or "").strip(),
            primary_crops=str(payload.primary_crops or payload.crop or "").strip(),
            intended_use=str(payload.intended_use or "").strip(),
            planned_data_sources=str(payload.planned_data_sources or "").strip(),
            email_domain=decision.email_domain,
            domain_classification=decision.domain_classification,
            phone_algorithm="pending",
            phone_key_version="pending",
            phone_nonce_b64="pending",
            phone_ciphertext_b64="pending",
            phone_last4="0000",
            decision=decision.status,
            score=decision.score,
            reason_codes_json=list(decision.reason_codes),
            engine_version=decision.engine_version,
            evidence_digest=decision.evidence_digest,
            submitted_at=now,
            decided_at=now,
        )
        db.add(profile)
        db.flush()
        protected_phone = encrypt_phone(
            str(payload.phone_number or ""),
            organization_id=org.id,
            profile_id=profile.id,
        )
        profile.phone_algorithm = protected_phone["algorithm"]
        profile.phone_key_version = protected_phone["key_version"]
        profile.phone_nonce_b64 = protected_phone["nonce_b64"]
        profile.phone_ciphertext_b64 = protected_phone["ciphertext_b64"]
        profile.phone_last4 = protected_phone["last4"]

    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(
        organization_id=org.id,
        name=payload.workspace_name,
        crop=payload.primary_crops or payload.crop,
        region=payload.operating_region or payload.region,
        mode="evaluation",
    )
    db.add_all([membership, workspace])
    db.flush()
    ensure_evaluation_context(db, org, workspace)
    ip_address, user_agent = _request_metadata(request)
    record_security_event(
        db,
        event_type="registration_verification",
        outcome="preapproved_pending_email" if strict_registration else "approved_legacy",
        organization_id=org.id,
        user_id=user.id,
        subject=email,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={
            "score": decision.score if decision else None,
            "engine_version": decision.engine_version if decision else "legacy-pre-2026-07-20",
            "domain_classification": decision.domain_classification if decision else "legacy",
        },
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration could not be completed")

    db.refresh(user)
    db.refresh(org)
    db.refresh(membership)
    delivery = _best_effort_send_verification(db, user)
    db.refresh(user)
    db.refresh(org)
    return {
        "status": "verification_required",
        "message": "Your organization passed automated screening. Verify your email to activate the workspace."
        if strict_registration
        else "Verify your email to activate your AGRO-AI workspace.",
        "verification": _verification_payload(user),
        "organization_verification": _organization_verification_payload(org),
        "delivery": "verification_email_sent" if delivery.get("provider_configured") else "verification_request_received",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "is_active": user.is_active,
            "account_status": user.account_status,
        },
        "current_organization": _organization_payload(org, membership.role),
        "entitlements": serialize_entitlements(org),
    }


def _lockout_active(user: User, now: datetime) -> bool:
    return bool(user.locked_until and user.locked_until > now)


def _register_failed_login(db: Session, user: User, now: datetime) -> bool:
    window_minutes = max(1, int(getattr(settings, "AUTH_FAILURE_WINDOW_MINUTES", 15)))
    lockout_minutes = max(1, int(getattr(settings, "AUTH_LOCKOUT_MINUTES", 15)))
    max_attempts = max(3, int(getattr(settings, "AUTH_MAX_FAILED_ATTEMPTS", 5)))
    window_start = user.failed_login_window_started_at
    if not window_start or window_start < now - timedelta(minutes=window_minutes):
        user.failed_login_attempts = 1
        user.failed_login_window_started_at = now
    else:
        user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
    locked = user.failed_login_attempts >= max_attempts
    if locked:
        user.locked_until = now + timedelta(minutes=lockout_minutes)
        user.failed_login_attempts = 0
        user.failed_login_window_started_at = None
    db.flush()
    return locked


def _reset_failed_login(user: User) -> None:
    user.failed_login_attempts = 0
    user.failed_login_window_started_at = None
    user.locked_until = None


@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    now = datetime.utcnow()
    email = payload.email.lower()
    user = db.query(User).filter(User.email == email).first()
    ip_address, user_agent = _request_metadata(request)

    if user and _lockout_active(user, now):
        record_security_event(
            db,
            event_type="login",
            outcome="locked",
            organization_id=user.memberships[0].organization_id if user.memberships else None,
            user_id=user.id,
            subject=email,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "account_temporarily_locked",
                "message": "Sign-in is temporarily locked after repeated failed attempts. Try again later or recover the account.",
            },
        )

    password_valid = bool(user and user.password_hash and pwd_context.verify(payload.password, user.password_hash))
    if not password_valid:
        locked = _register_failed_login(db, user, now) if user else False
        record_security_event(
            db,
            event_type="login",
            outcome="locked" if locked else "invalid_credentials",
            organization_id=user.memberships[0].organization_id if user and user.memberships else None,
            user_id=user.id if user else None,
            subject=email,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if user.email_verification_status != "verified" or not user.email_verified_at:
        record_security_event(
            db,
            event_type="login",
            outcome="email_verification_required",
            organization_id=user.memberships[0].organization_id if user.memberships else None,
            user_id=user.id,
            subject=email,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_verification_required",
                "message": "Verify your email to activate your AGRO-AI workspace.",
            },
        )

    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.created_at.asc())
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no organization membership")

    _promote_verified_organization(user, membership.organization)
    if user.account_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "account_access_restricted", "message": "This account is not approved for portal access."},
        )
    require_approved_organization(membership.organization)

    _reset_failed_login(user)
    user.last_login_at = now
    ensure_evaluation_context(db, membership.organization, _first_workspace(db, membership.organization_id))
    record_security_event(
        db,
        event_type="login",
        outcome="success",
        organization_id=membership.organization_id,
        user_id=user.id,
        subject=email,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return _session_response(user, membership.organization, membership)


@router.post("/logout")
def logout(_: User = Depends(get_current_user)) -> dict:
    return {"ok": True}


@router.post("/email-verification/request")
@limiter.limit(VERIFICATION_REQUEST_RATE_LIMIT)
def request_email_verification(
    request: Request,
    payload: EmailVerificationRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    try:
        target = user
        if not target and payload.email:
            target = db.query(User).filter(User.email == payload.email.lower()).first()
        if target and (target.email_verification_status != "verified" or not target.email_verified_at):
            _best_effort_send_verification(db, target)
    except (SQLAlchemyError, Exception):
        db.rollback()
        logger.exception("Email verification resend failed")
    return {"message": GENERIC_VERIFICATION_MESSAGE}


@router.post("/email-verification/confirm")
@limiter.limit(VERIFICATION_CONFIRM_RATE_LIMIT)
def email_verification_confirm(
    payload: EmailVerificationConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Verify the single-use email token and establish an approved session."""
    user = confirm_verification(db, payload.token)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification link is invalid or expired")

    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.created_at.asc())
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no organization membership")

    _promote_verified_organization(user, membership.organization)
    require_approved_organization(membership.organization)
    ensure_evaluation_context(db, membership.organization, _first_workspace(db, membership.organization_id))
    user.last_login_at = datetime.utcnow()
    ip_address, user_agent = _request_metadata(request)
    record_security_event(
        db,
        event_type="email_verification",
        outcome="success",
        organization_id=membership.organization_id,
        user_id=user.id,
        subject=user.email,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    response = _session_response(user, membership.organization, membership)
    response.update(
        {
            "status": "verified",
            "message": "Your email and organization access have been verified. You are signed in.",
            "verification": _verification_payload(user),
        }
    )
    return response


@router.get("/me")
def me(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    if ctx.organization:
        ensure_evaluation_context(db, ctx.organization, _first_workspace(db, ctx.organization.id))
        db.commit()

    orgs = [_organization_payload(membership.organization, membership.role) for membership in ctx.user.memberships]
    current = orgs[0] if orgs else None
    return {
        "user": {
            "id": ctx.user.id,
            "email": ctx.user.email,
            "name": ctx.user.name,
            "is_active": ctx.user.is_active,
            "account_status": ctx.user.account_status,
        },
        "organizations": orgs,
        "current_organization": current,
        "role": current["role"] if current else None,
        "plan": current["plan"] if current else None,
        "subscription_status": current["subscription_status"] if current else None,
        "entitlements": serialize_entitlements(ctx.organization) if ctx.organization else None,
        "verification": _verification_payload(ctx.user),
        "organization_verification": _organization_verification_payload(ctx.organization) if ctx.organization else None,
        "platform_admin": is_platform_admin_user(ctx.user),
    }
