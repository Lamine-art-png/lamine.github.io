"""Versioned Platform API legal acceptance policy.

Legal documents are maintained independently from Portal terms. Enforcement is
organization-scoped for machine credentials and user-scoped for control-plane
actions so service accounts never depend on a browser session at request time.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.platform_product import PlatformTermsAcceptance, PlatformTermsDocument


def required_documents(db: Session, *, now: datetime | None = None) -> list[PlatformTermsDocument]:
    moment = now or datetime.utcnow()
    rows = (
        db.query(PlatformTermsDocument)
        .filter(
            PlatformTermsDocument.status == "approved_effective",
            PlatformTermsDocument.effective_at.is_not(None),
            PlatformTermsDocument.effective_at <= moment,
        )
        .order_by(PlatformTermsDocument.document_type.asc(), PlatformTermsDocument.effective_at.desc())
        .all()
    )
    latest_by_type: dict[str, PlatformTermsDocument] = {}
    for row in rows:
        latest_by_type.setdefault(row.document_type, row)
    return list(latest_by_type.values())


def _enforcement_error(code: str, message: str, *, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "type": "authorization_error", "message": message},
    )


def require_user_acceptance(db: Session, *, organization_id: str, user_id: str) -> None:
    documents = required_documents(db)
    if not documents:
        raise _enforcement_error(
            "platform_terms_catalog_not_ready",
            "Platform API legal documents are not approved and effective.",
            status_code=503,
        )
    for document in documents:
        accepted = (
            db.query(PlatformTermsAcceptance)
            .filter(
                PlatformTermsAcceptance.organization_id == organization_id,
                PlatformTermsAcceptance.user_id == user_id,
                PlatformTermsAcceptance.document_id == document.id,
                PlatformTermsAcceptance.document_type == document.document_type,
                PlatformTermsAcceptance.document_version == document.version,
            )
            .first()
        )
        if accepted is None:
            raise _enforcement_error(
                "platform_terms_acceptance_required",
                f"Acceptance is required for {document.document_type} version {document.version}.",
                status_code=403,
            )


def require_organization_acceptance(db: Session, *, organization_id: str) -> None:
    documents = required_documents(db)
    if not documents:
        raise _enforcement_error(
            "platform_terms_catalog_not_ready",
            "Platform API legal documents are not approved and effective.",
            status_code=503,
        )
    for document in documents:
        accepted = (
            db.query(PlatformTermsAcceptance)
            .filter(
                PlatformTermsAcceptance.organization_id == organization_id,
                PlatformTermsAcceptance.document_id == document.id,
                PlatformTermsAcceptance.document_type == document.document_type,
                PlatformTermsAcceptance.document_version == document.version,
            )
            .first()
        )
        if accepted is None:
            raise _enforcement_error(
                "platform_terms_acceptance_required",
                f"Organization acceptance is required for {document.document_type} version {document.version}.",
                status_code=403,
            )
