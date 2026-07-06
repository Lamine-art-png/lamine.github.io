from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from html import escape

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import AccountRecoveryToken, User
from app.services.email_delivery import send_email

logger = logging.getLogger(__name__)
credential_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TTL_MINUTES = 30
COOLDOWN_SECONDS = 60
GENERIC_MESSAGE = "If an account exists, we sent recovery instructions."


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def portal_base_url() -> str:
    return (settings.RESEND_APP_URL or settings.APP_URL or "https://app.agroai-pilot.com").strip().rstrip("/")


def issue_token(db: Session, user: User) -> str | None:
    now = datetime.utcnow()
    latest = (
        db.query(AccountRecoveryToken)
        .filter(AccountRecoveryToken.user_id == user.id)
        .order_by(AccountRecoveryToken.created_at.desc())
        .first()
    )
    if latest and latest.created_at > now - timedelta(seconds=COOLDOWN_SECONDS):
        return None

    db.query(AccountRecoveryToken).filter(
        AccountRecoveryToken.user_id == user.id,
        AccountRecoveryToken.used_at.is_(None),
    ).update({AccountRecoveryToken.used_at: now}, synchronize_session=False)

    token = secrets.token_urlsafe(32)
    db.add(
        AccountRecoveryToken(
            user_id=user.id,
            token_hash=digest_token(token),
            expires_at=now + timedelta(minutes=TTL_MINUTES),
        )
    )
    db.flush()
    return token


def _message_html(url: str) -> str:
    safe_url = escape(url, quote=True)
    return f"""
<!doctype html>
<html><body style="margin:0;background:#f6f3ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#10231b;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f3ea;padding:40px 16px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:18px;border:1px solid #e5e0d6;overflow:hidden;">
<tr><td style="background:#082f23;padding:28px 32px;color:#ffffff;"><div style="font-size:13px;letter-spacing:0.18em;text-transform:uppercase;color:#d9f99d;font-weight:700;">AGRO-AI</div><h1 style="margin:14px 0 0;font-size:28px;line-height:1.2;font-weight:750;">Recover account access</h1><p style="margin:12px 0 0;font-size:15px;line-height:1.6;color:#dbe7df;">Secure recovery for your AGRO-AI Enterprise Portal workspace.</p></td></tr>
<tr><td style="padding:32px;"><p style="margin:0 0 18px;font-size:16px;line-height:1.6;">A recovery request was received for your account. Use the secure one-time link below to choose a new sign-in credential.</p><table role="presentation" cellspacing="0" cellpadding="0" style="margin:28px auto;"><tr><td align="center" style="border-radius:10px;background:#0b3326;"><a href="{safe_url}" style="display:inline-block;padding:14px 28px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;border-radius:10px;">Recover account</a></td></tr></table><p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#637267;">If the button does not work, copy and paste this link into your browser:</p><p style="word-break:break-all;margin:0 0 24px;font-size:13px;line-height:1.6;"><a href="{safe_url}" style="color:#0b6b43;">{safe_url}</a></p><p style="margin:0;font-size:13px;line-height:1.6;color:#7a857d;">This link expires in {TTL_MINUTES} minutes and can be used only once. If you did not request recovery, ignore this email.</p></td></tr>
</table></td></tr></table></body></html>
"""


def deliver(email: str, token: str) -> dict:
    url = f"{portal_base_url()}/reset-password?token={token}"
    result = send_email(
        to_email=email,
        subject="Recover your AGRO-AI account",
        text_body=(
            "A secure account recovery request was received.\n\n"
            f"Open this one-time link: {url}\n\n"
            f"This link expires in {TTL_MINUTES} minutes."
        ),
        html_body=_message_html(url),
    )
    if not result.get("ok"):
        logger.warning("Recovery email was not accepted provider=%s reason=%s", result.get("provider"), result.get("reason"))
    return result


def consume_token(db: Session, token: str, replacement_credential: str) -> User | None:
    now = datetime.utcnow()
    query = db.query(AccountRecoveryToken).filter(AccountRecoveryToken.token_hash == digest_token(token))
    if db.get_bind().dialect.name != "sqlite":
        query = query.with_for_update()
    row = query.first()
    if not row or row.used_at is not None or row.expires_at < now:
        return None

    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        return None

    row.used_at = now
    user.password_hash = credential_context.hash(replacement_credential)
    user.credentials_changed_at = now
    db.query(AccountRecoveryToken).filter(
        AccountRecoveryToken.user_id == user.id,
        AccountRecoveryToken.id != row.id,
        AccountRecoveryToken.used_at.is_(None),
    ).update({AccountRecoveryToken.used_at: now}, synchronize_session=False)
    db.commit()
    db.refresh(user)
    return user
