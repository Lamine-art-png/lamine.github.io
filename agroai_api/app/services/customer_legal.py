"""Customer-facing clickwrap policy for the AGRO-AI Enterprise Portal."""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models.legal import CustomerLegalAcceptance
from app.services.security_audit import privacy_hash


TERMS_VERSION = "2026-07-03"
PRIVACY_VERSION = "2026-07-03"
TERMS_EFFECTIVE_DATE = "2026-07-03"
PRIVACY_EFFECTIVE_DATE = "2026-07-03"
TERMS_URL = "https://agroai-pilot.com/terms-of-service"
PRIVACY_URL = "https://agroai-pilot.com/privacy-policy"
ACCEPTANCE_TEXT = (
    "I agree to the AGRO-AI Terms of Service, acknowledge the Privacy Policy, "
    "and confirm that I am authorized to bind my organization."
)


def _reference_digest(document_type: str, version: str, effective_date: str, url: str) -> str:
    canonical = f"{document_type}|{version}|{effective_date}|{url}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


TERMS_REFERENCE_DIGEST = _reference_digest("terms", TERMS_VERSION, TERMS_EFFECTIVE_DATE, TERMS_URL)
PRIVACY_REFERENCE_DIGEST = _reference_digest("privacy", PRIVACY_VERSION, PRIVACY_EFFECTIVE_DATE, PRIVACY_URL)


def current_documents() -> dict:
    return {
        "terms": {
            "version": TERMS_VERSION,
            "effective_date": TERMS_EFFECTIVE_DATE,
            "url": TERMS_URL,
            "reference_digest": TERMS_REFERENCE_DIGEST,
        },
        "privacy": {
            "version": PRIVACY_VERSION,
            "effective_date": PRIVACY_EFFECTIVE_DATE,
            "url": PRIVACY_URL,
            "reference_digest": PRIVACY_REFERENCE_DIGEST,
        },
        "acceptance_copy": ACCEPTANCE_TEXT,
    }


def validate_clickwrap(
    *,
    terms_version: str,
    privacy_version: str,
    accepted_terms: bool,
    acknowledged_privacy: bool,
    authority_confirmed: bool,
) -> None:
    if terms_version != TERMS_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_terms_version",
                "message": "The Terms of Service changed. Review and accept the current version.",
                "current_version": TERMS_VERSION,
                "current_url": TERMS_URL,
            },
        )
    if privacy_version != PRIVACY_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_privacy_version",
                "message": "The Privacy Policy changed. Review the current version before continuing.",
                "current_version": PRIVACY_VERSION,
                "current_url": PRIVACY_URL,
            },
        )
    if not (accepted_terms and acknowledged_privacy and authority_confirmed):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "legal_acceptance_required",
                "message": "Accept the Terms of Service, acknowledge the Privacy Policy, and confirm authority to bind the organization.",
            },
        )


def _request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None)


def record_acceptance(
    db: Session,
    *,
    request: Request,
    organization_id: str,
    user_id: str,
    subject_email: str,
    event_type: str,
    order_snapshot: dict | None = None,
) -> CustomerLegalAcceptance:
    row = CustomerLegalAcceptance(
        organization_id=organization_id,
        user_id=user_id,
        subject_email=subject_email.strip().lower(),
        event_type=event_type,
        terms_version=TERMS_VERSION,
        privacy_version=PRIVACY_VERSION,
        terms_effective_date=TERMS_EFFECTIVE_DATE,
        privacy_effective_date=PRIVACY_EFFECTIVE_DATE,
        terms_url=TERMS_URL,
        privacy_url=PRIVACY_URL,
        terms_reference_digest=TERMS_REFERENCE_DIGEST,
        privacy_reference_digest=PRIVACY_REFERENCE_DIGEST,
        acceptance_text=ACCEPTANCE_TEXT,
        accepted_terms=True,
        acknowledged_privacy=True,
        authority_confirmed=True,
        order_snapshot_json=order_snapshot,
        ip_hash=privacy_hash(_request_ip(request), "customer-legal-ip"),
        user_agent_hash=privacy_hash(request.headers.get("user-agent", "")[:512], "customer-legal-user-agent"),
        request_id=str(getattr(request.state, "request_id", "") or "") or None,
        accepted_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def latest_acceptance(
    db: Session,
    *,
    organization_id: str,
    user_id: str,
    event_types: tuple[str, ...] = ("signup", "invite", "reaccept"),
) -> CustomerLegalAcceptance | None:
    return (
        db.query(CustomerLegalAcceptance)
        .filter(
            CustomerLegalAcceptance.organization_id == organization_id,
            CustomerLegalAcceptance.user_id == user_id,
            CustomerLegalAcceptance.event_type.in_(event_types),
        )
        .order_by(CustomerLegalAcceptance.accepted_at.desc())
        .first()
    )


def acceptance_is_current(row: CustomerLegalAcceptance | None) -> bool:
    return bool(
        row
        and row.terms_version == TERMS_VERSION
        and row.privacy_version == PRIVACY_VERSION
        and row.accepted_terms
        and row.acknowledged_privacy
        and row.authority_confirmed
    )
