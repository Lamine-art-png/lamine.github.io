from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from html import escape

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import EmailVerificationToken, SaaSRequest, User
from app.services.email_delivery import delivery_status, send_email

logger = logging.getLogger(__name__)


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


def verification_base_url() -> str:
    """Return the public portal URL used in verification links.

    RESEND_APP_URL is intentionally supported so email/link routing can be
    configured independently from the main portal APP_URL used elsewhere.
    """

    return (os.getenv("RESEND_APP_URL") or settings.APP_URL or "https://app.agroai-pilot.com").strip().rstrip("/")


def _verification_email_html(*, verification_url: str) -> str:
    safe_url = escape(verification_url, quote=True)
    return f"""
<!doctype html>
<html>
  <body style="margin:0;background:#f6f3ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#10231b;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f3ea;padding:40px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:18px;border:1px solid #e5e0d6;overflow:hidden;">
            <tr>
              <td style="background:#082f23;padding:28px 32px;color:#ffffff;">
                <div style="font-size:13px;letter-spacing:0.18em;text-transform:uppercase;color:#d9f99d;font-weight:700;">AGRO-AI</div>
                <h1 style="margin:14px 0 0;font-size:28px;line-height:1.2;font-weight:750;">Confirm your email address</h1>
                <p style="margin:12px 0 0;font-size:15px;line-height:1.6;color:#dbe7df;">Activate secure access to your AGRO-AI Enterprise Portal workspace.</p>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 18px;font-size:16px;line-height:1.6;">Thank you for creating an AGRO-AI account. To activate your workspace, confirm your email address.</p>
                <table role="presentation" cellspacing="0" cellpadding="0" style="margin:28px auto;">
                  <tr>
                    <td align="center" style="border-radius:10px;background:#0b3326;">
                      <a href="{safe_url}" style="display:inline-block;padding:14px 28px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;border-radius:10px;">Verify email</a>
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#637267;">If the button does not work, copy and paste this link into your browser:</p>
                <p style="word-break:break-all;margin:0 0 24px;font-size:13px;line-height:1.6;"><a href="{safe_url}" style="color:#0b6b43;">{safe_url}</a></p>
                <p style="margin:0;font-size:13px;line-height:1.6;color:#7a857d;">This verification link expires in 24 hours. If you did not create this account, you can safely ignore this email.</p>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 32px;background:#faf8f1;border-top:1px solid #e5e0d6;color:#7a857d;font-size:12px;line-height:1.6;text-align:center;">
                You received this email because an AGRO-AI Enterprise Portal account was created with this address.<br />
                AGRO-AI · Secure agricultural intelligence workspace
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def send_or_log_verification(db: Session, user: User, token: str) -> dict:
    status = delivery_status()
    verification_url = f"{verification_base_url()}/verify-email?token={token}"
    subject = "Confirm your AGRO-AI email address"
    body = (
        "Confirm your email address to activate your AGRO-AI Enterprise Portal workspace.\n\n"
        f"Open this link: {verification_url}\n\n"
        "This link expires in 24 hours."
    )
    if status["configured"]:
        sent = send_email(
            to_email=user.email,
            subject=subject,
            text_body=body,
            html_body=_verification_email_html(verification_url=verification_url),
        )
        if sent:
            return {"delivery": "sent", "provider_configured": True}
        logger.warning("Email verification provider was configured but send_email returned false for user_id=%s", user.id)
    else:
        logger.warning("Email verification requested but delivery is not configured. Missing=%s", status.get("missing_env"))

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
        message="Email verification requested but delivery provider is not configured or failed.",
        source_page="security",
        notification_status="provider_missing",
        metadata_json={"missing_env": status["missing_env"], "request_type": "email_verification", "provider": status.get("provider")},
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
