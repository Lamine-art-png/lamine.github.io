from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode, urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import EmailVerificationToken, SaaSRequest, User
from app.services.email_delivery import delivery_status, send_email

logger = logging.getLogger(__name__)
_PRODUCT_SURFACES = {"enterprise_portal", "platform_api"}
_TRUSTED_VERIFICATION_ORIGIN = "https://app.agroai-pilot.com"
_LOCAL_VERIFICATION_HOSTS = {"localhost", "127.0.0.1", "::1"}
_LOCAL_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}


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
    """Return a fail-closed first-party origin for single-use verification links.

    Production verification tokens must never be sent to a configurable third-party
    origin. Local loopback origins remain available only in explicit development or
    test environments.
    """

    candidate = str(settings.RESEND_APP_URL or settings.APP_URL or _TRUSTED_VERIFICATION_ORIGIN).strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        logger.error("Rejected malformed verification app origin")
        return _TRUSTED_VERIFICATION_ORIGIN

    if (
        parsed.scheme.lower() == "https"
        and hostname == "app.agroai-pilot.com"
        and port in {None, 443}
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    ):
        return _TRUSTED_VERIFICATION_ORIGIN

    environment = str(getattr(settings, "APP_ENV", "development") or "development").strip().lower()
    if (
        environment in _LOCAL_ENVIRONMENTS
        and parsed.scheme.lower() in {"http", "https"}
        and hostname in _LOCAL_VERIFICATION_HOSTS
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    ):
        return f"{parsed.scheme.lower()}://{parsed.netloc}"

    logger.error(
        "Rejected untrusted verification app origin host=%s environment=%s",
        hostname or "missing",
        environment,
    )
    return _TRUSTED_VERIFICATION_ORIGIN


def normalize_product_surface(value: str | None) -> str:
    normalized = str(value or "enterprise_portal").strip().lower()
    return normalized if normalized in _PRODUCT_SURFACES else "enterprise_portal"


def verification_url(token: str, *, product_surface: str = "enterprise_portal") -> str:
    surface = normalize_product_surface(product_surface)
    query = urlencode({"token": token, "product": surface})
    return f"{verification_base_url()}/verify-email?{query}"


def _product_copy(product_surface: str) -> dict[str, str]:
    if normalize_product_surface(product_surface) == "platform_api":
        return {
            "product": "AGRO-AI Platform API",
            "headline": "Confirm your developer account",
            "intro": "Confirm your email to activate the verified AGRO-AI organization account used for the Platform API private beta.",
            "body": "After verification, return to the Platform API application. API enrollment, test projects, keys, live access, billing, providers, and physical actions remain separately controlled.",
            "footer": "Verified account · reviewed API enrollment · controlled activation",
            "subject": "Confirm your AGRO-AI Platform API account",
        }
    return {
        "product": "AGRO-AI Enterprise Portal",
        "headline": "Confirm your email address",
        "intro": "Activate secure access to your AGRO-AI Enterprise Portal workspace.",
        "body": "Thank you for creating an AGRO-AI account. To activate your workspace, confirm your email address.",
        "footer": "AGRO-AI · Secure agricultural intelligence workspace",
        "subject": "Confirm your AGRO-AI email address",
    }


def _verification_email_html(*, url: str, product_surface: str) -> str:
    safe_url = escape(url, quote=True)
    copy = {key: escape(value) for key, value in _product_copy(product_surface).items()}
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
                <h1 style="margin:14px 0 0;font-size:28px;line-height:1.2;font-weight:750;">{copy['headline']}</h1>
                <p style="margin:12px 0 0;font-size:15px;line-height:1.6;color:#dbe7df;">{copy['intro']}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 18px;font-size:16px;line-height:1.6;">{copy['body']}</p>
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
                You received this email because a {copy['product']} account flow was started with this address.<br />
                {copy['footer']}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _log_delivery_gap(
    db: Session,
    user: User,
    status: dict,
    result: dict | None = None,
    *,
    product_surface: str = "enterprise_portal",
) -> None:
    result = result or {}
    row = SaaSRequest(
        organization_id=None,
        workspace_id=None,
        user_id=user.id,
        type="support",
        status="received",
        priority="high",
        name=user.name,
        email=user.email,
        company=None,
        role=None,
        subject="Email verification delivery needs attention",
        message="Email verification was requested but the email provider did not accept the message.",
        source_page="security",
        notification_status="provider_missing" if not status.get("configured") else "provider_failed",
        metadata_json={
            "missing_env": status.get("missing_env", []),
            "request_type": "email_verification",
            "product_surface": normalize_product_surface(product_surface),
            "provider": status.get("provider"),
            "from_email_domain": status.get("from_email_domain"),
            "verification_base_url": status.get("verification_base_url"),
            "result_reason": result.get("reason"),
            "result_status_code": result.get("status_code"),
            "provider_response": result.get("provider_response"),
        },
    )
    db.add(row)


def send_or_log_verification(
    db: Session,
    user: User,
    token: str,
    *,
    product_surface: str = "enterprise_portal",
) -> dict:
    surface = normalize_product_surface(product_surface)
    status = delivery_status()
    url = verification_url(token, product_surface=surface)
    copy = _product_copy(surface)
    body = (
        f"{copy['intro']}\n\n"
        f"Open this link: {url}\n\n"
        f"{copy['body']}\n\n"
        "This link expires in 24 hours."
    )
    if not status["configured"]:
        logger.warning("Email verification requested but delivery is not configured. Missing=%s", status.get("missing_env"))
        _log_delivery_gap(db, user, status, {"reason": "email_provider_not_configured"}, product_surface=surface)
        return {
            "delivery": "not_configured",
            "provider_configured": False,
            "provider": status.get("provider"),
            "reason": "email_provider_not_configured",
            "missing_env": status.get("missing_env", []),
            "product_surface": surface,
        }

    result = send_email(
        to_email=user.email,
        subject=copy["subject"],
        text_body=body,
        html_body=_verification_email_html(url=url, product_surface=surface),
    )
    if result.get("ok"):
        return {
            "delivery": "sent",
            "provider_configured": True,
            "provider": result.get("provider"),
            "status_code": result.get("status_code"),
            "reason": "accepted",
            "product_surface": surface,
        }

    logger.warning("Email verification provider failed for user_id=%s result=%s", user.id, result)
    _log_delivery_gap(db, user, status, result, product_surface=surface)
    return {
        "delivery": "failed",
        "provider_configured": True,
        "provider": result.get("provider") or status.get("provider"),
        "status_code": result.get("status_code"),
        "reason": result.get("reason") or "provider_failed",
        "product_surface": surface,
    }


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
