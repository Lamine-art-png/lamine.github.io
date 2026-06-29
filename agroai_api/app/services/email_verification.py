from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import EmailVerificationToken, SaaSRequest, User
from app.services.email_delivery import delivery_status, send_email


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_verification_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    row = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(row)
    db.flush()
    return token


def send_or_log_verification(db: Session, user: User, token: str) -> dict:
    status = delivery_status()
    verification_url = f"{settings.APP_URL.rstrip('/')}/verify-email?token={token}"
    subject = "Verify your AGRO-AI workspace email"
    body = (
        "Verify your email to activate your AGRO-AI workspace.\n\n"
        f"Open this link: {verification_url}\n\n"
        "This link expires in 24 hours."
    )
    if status["configured"]:
        try:
            sent = send_email(to_email=user.email, subject=subject, text_body=body)
            if sent:
                return {"delivery": "sent", "provider_configured": True}
        except Exception:
            pass
    row = SaaSRequest(
        organization_id=None,
        workspace_id=None,
        user_id=user.id,
        type="support",
        status="received",
        priority="medium",
        name=user.name,
        email=user.email,
        company=None,
        role=None,
        subject="Email verification delivery needs setup",
        message="Email verification requested but delivery provider is not configured.",
        source_page="security",
        notification_status="provider_missing",
        metadata_json={"missing_env": status["missing_env"], "request_type": "email_verification"},
    )
    db.add(row)
    return {"delivery": "received", "provider_configured": False}


def confirm_verification(db: Session, token: str) -> User | None:
    row = (
        db.query(EmailVerificationToken)
        .filter(EmailVerificationToken.token_hash == hash_token(token))
        .order_by(EmailVerificationToken.created_at.desc())
        .first()
    )
    if not row or row.used_at or row.expires_at < datetime.utcnow():
        return None
    user = db.get(User, row.user_id)
    if not user:
        return None
    row.used_at = datetime.utcnow()
    user.email_verified_at = datetime.utcnow()
    user.email_verification_status = "verified"
    db.commit()
    db.refresh(user)
    return user
