"""Team invitation lifecycle: issue, deliver, resend, revoke, expire, redeem.

Security model
- A 256-bit random token is emailed; only its SHA-256 is stored.
- Exactly one link is valid per invitation: resend rotates the token.
- The hash is cleared on acceptance, revocation, expiry or failed delivery,
  so a used/revoked/expired link can never be replayed.
- The organization and role come only from the invitation row, never from the
  redeeming client.
- An invitation is reported as sent only when the email provider accepted it.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.saas import Organization, OrganizationMembership, SaaSRequest, TeamInvitation, User
from app.services.email_delivery import delivery_status, send_email
from app.services.email_verification import verification_base_url
from app.services.language_registry import canonical_ui_locale
from app.services.transactional_i18n import localize_transactional_strings

logger = logging.getLogger("agroai.team_invitations")

INVITATION_TTL_DAYS = 7
MAX_DELIVERY_ATTEMPTS = 5
RESEND_MIN_INTERVAL = timedelta(seconds=60)
# Ownership is never granted by invitation. Admins may invite below admin.
ASSIGNABLE_ROLES = {
    "owner": {"admin", "manager", "operator", "viewer"},
    "admin": {"manager", "operator", "viewer"},
}
_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")

# Customer-facing result messages (templates; the portal localizes them).
INVITATION_SENT_MESSAGE = "Invitation email sent to {email}."
INVITATION_RESENT_MESSAGE = "Invitation email resent to {email}."
INVITATION_NOT_DELIVERED_MESSAGE = "The invitation for {email} was saved, but the email could not be delivered. Try resending it; AGRO-AI support has been notified."

ENGLISH_COPY = {
    "subject": "{inviter} invited you to {organization} on AGRO-AI",
    "headline": "You're invited to join {organization}",
    "intro": "Work with your team in the AGRO-AI Enterprise Portal.",
    "body": "{inviter} invited you to join {organization} on AGRO-AI with the {role} role. Accept the invitation to sign in or create your account and start working with the team.",
    "button": "Accept invitation",
    "fallback_instruction": "If the button does not work, copy and paste this link into your browser:",
    "expiry": "This invitation expires in {days} days and can be used only once. If you were not expecting it, you can ignore this email.",
    "footer": "AGRO-AI · Secure agricultural intelligence workspace",
}
ENGLISH_ROLES = {"admin": "Admin", "manager": "Manager", "operator": "Operator", "viewer": "Viewer"}


def _error(code: int, key: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=code, detail={"code": key, "message": message, **extra})


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_invitation_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 240 or not _EMAIL_RE.match(email):
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_email", "Enter a valid email address.")
    return email


def _locale(value: str | None) -> str:
    try:
        canonical = canonical_ui_locale(value or "en")
    except ValueError:
        canonical = "en"
    return "en" if canonical == "auto" else canonical


def invitation_url(token: str, locale: str | None) -> str:
    return f"{verification_base_url()}/accept-invite?{urlencode({'token': token, 'lang': _locale(locale)})}"


def effective_status(row: TeamInvitation, now: datetime | None = None) -> str:
    moment = now or datetime.utcnow()
    if row.status == "pending" and row.expires_at and row.expires_at <= moment:
        return "expired"
    return row.status


def serialize_invitation(row: TeamInvitation) -> dict:
    return {
        "id": row.id,
        "email": row.email,
        "role": row.role,
        "status": effective_status(row),
        "delivery_status": row.delivery_status,
        "delivery_attempts": row.delivery_attempts or 0,
        "last_sent_at": row.last_sent_at.isoformat() if row.last_sent_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _email_copy(org: Organization, inviter: User, role: str, locale: str) -> tuple[dict, dict]:
    """Return (plain, html_escaped) localized copy with values substituted."""
    source = {**{f"copy.{k}": v for k, v in ENGLISH_COPY.items()}, "role": ENGLISH_ROLES.get(role, role)}
    localized = localize_transactional_strings(locale, source) if locale != "en" else source
    values = {
        "inviter": (inviter.name or inviter.email or "A teammate").strip(),
        "organization": (org.name or "your organization").strip(),
        "role": localized.get("role", ENGLISH_ROLES.get(role, role)),
        "days": str(INVITATION_TTL_DAYS),
    }
    plain = {key.removeprefix("copy."): value.format(**values) for key, value in localized.items() if key.startswith("copy.")}
    escaped_values = {key: escape(value) for key, value in values.items()}
    html_copy = {key.removeprefix("copy."): escape(value).format(**escaped_values) for key, value in localized.items() if key.startswith("copy.")}
    return plain, html_copy


def _email_html(copy: dict, url: str, locale: str) -> str:
    safe_url = escape(url, quote=True)
    return f"""<!doctype html>
<html lang="{escape(locale, quote=True)}"><body style="margin:0;background:#f6f3ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#10231b;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f3ea;padding:40px 16px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:18px;border:1px solid #e5e0d6;overflow:hidden;">
<tr><td style="background:#082f23;padding:28px 32px;color:#ffffff;"><div style="font-size:13px;letter-spacing:0.18em;text-transform:uppercase;color:#d9f99d;font-weight:700;">AGRO-AI</div><h1 style="margin:14px 0 0;font-size:26px;line-height:1.25;font-weight:750;">{copy['headline']}</h1><p style="margin:12px 0 0;font-size:15px;line-height:1.6;color:#dbe7df;">{copy['intro']}</p></td></tr>
<tr><td style="padding:32px;"><p style="margin:0 0 18px;font-size:16px;line-height:1.6;">{copy['body']}</p>
<table role="presentation" cellspacing="0" cellpadding="0" style="margin:28px auto;"><tr><td align="center" style="border-radius:10px;background:#0b3326;"><a href="{safe_url}" style="display:inline-block;padding:14px 28px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;border-radius:10px;">{copy['button']}</a></td></tr></table>
<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#637267;">{copy['fallback_instruction']}</p>
<p style="word-break:break-all;margin:0 0 24px;font-size:13px;line-height:1.6;"><a href="{safe_url}" style="color:#0b6b43;">{safe_url}</a></p>
<p style="margin:0;font-size:13px;line-height:1.6;color:#7a857d;">{copy['expiry']}</p></td></tr>
<tr><td style="padding:22px 32px;background:#faf8f1;border-top:1px solid #e5e0d6;color:#7a857d;font-size:12px;line-height:1.6;text-align:center;">{copy['footer']}</td></tr>
</table></td></tr></table></body></html>"""


def _record_delivery_gap(db: Session, row: TeamInvitation, org: Organization, inviter: User, result: dict) -> None:
    """Durable operational record so a failed invitation email is never silent."""
    db.add(SaaSRequest(
        organization_id=org.id,
        workspace_id=None,
        user_id=inviter.id,
        type="support",
        status="received",
        priority="high",
        name=inviter.name,
        email=inviter.email,
        subject="Team invitation email was not delivered",
        message="A team invitation was created but the email provider did not accept the message.",
        source_page="team",
        notification_status="provider_missing" if result.get("reason") == "email_provider_not_configured" else "provider_failed",
        metadata_json={
            "request_type": "team_invitation_delivery",
            "invitation_id": row.id,
            "provider": result.get("provider"),
            "result_reason": str(result.get("reason") or "")[:240],
            "result_status_code": result.get("status_code"),
        },
    ))


def _deliver(db: Session, row: TeamInvitation, org: Organization, inviter: User) -> dict:
    """Issue a fresh single-use token and send it. Commits state before and after."""
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    row.token_hash = hash_invitation_token(token)
    row.expires_at = now + timedelta(days=INVITATION_TTL_DAYS)
    row.delivery_status = "sending"
    row.delivery_attempts = (row.delivery_attempts or 0) + 1
    db.commit()  # the token is only valid once durably stored

    locale = _locale(row.locale)
    plain, html_copy = _email_copy(org, inviter, row.role, locale)
    url = invitation_url(token, locale)
    text_body = f"{plain['body']}\n\n{plain['fallback_instruction']} {url}\n\n{plain['expiry']}"
    logger.info("team_invitation.provider_call invitation_id=%s org_id=%s attempt=%s locale=%s", row.id, org.id, row.delivery_attempts, locale)
    try:
        result = send_email(to_email=row.email, subject=plain["subject"], text_body=text_body, html_body=_email_html(html_copy, url, locale))
    except Exception as exc:  # pragma: no cover - defensive; send_email already contains provider errors
        result = {"ok": False, "provider": delivery_status().get("provider"), "reason": exc.__class__.__name__}

    if result.get("ok"):
        row.delivery_status = "sent"
        row.delivery_error = None
        row.last_sent_at = datetime.utcnow()
        row.status = "pending"
        logger.info("team_invitation.provider_accepted invitation_id=%s provider=%s", row.id, result.get("provider"))
    else:
        reason = str(result.get("reason") or "provider_failed")[:240]
        row.delivery_status = "not_configured" if reason == "email_provider_not_configured" else "failed"
        row.delivery_error = reason
        row.status = "delivery_failed"
        row.token_hash = None  # the link never reached the recipient; nothing may redeem it
        _record_delivery_gap(db, row, org, inviter, result)
        logger.error("team_invitation.provider_rejected invitation_id=%s provider=%s reason=%s", row.id, result.get("provider"), reason)
    db.commit()
    db.refresh(row)
    return result


def _seat_limit(db: Session, org: Organization) -> int | None:
    from app.services.commercial_control import get_limit
    return get_limit(db, org, "quota.seat")


def _active_member_count(db: Session, org: Organization) -> int:
    return db.query(OrganizationMembership).filter(
        OrganizationMembership.organization_id == org.id,
        OrganizationMembership.status == "active",
    ).count()


def create_invitation(db: Session, *, org: Organization, inviter: User, inviter_role: str, email: str, role: str, locale: str | None) -> tuple[TeamInvitation, dict]:
    email = normalize_invitation_email(email)
    if role not in ASSIGNABLE_ROLES.get(inviter_role, set()):
        raise _error(status.HTTP_403_FORBIDDEN, "role_not_assignable", "You cannot assign that role.", assignable_roles=sorted(ASSIGNABLE_ROLES.get(inviter_role, set())))
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user and db.query(OrganizationMembership).filter(
        OrganizationMembership.organization_id == org.id, OrganizationMembership.user_id == existing_user.id
    ).first():
        raise _error(status.HTTP_409_CONFLICT, "already_member", "This person is already a member of the organization.")

    now = datetime.utcnow()
    open_rows = db.query(TeamInvitation).filter(
        TeamInvitation.organization_id == org.id,
        TeamInvitation.email == email,
        TeamInvitation.status.in_(["pending", "delivery_failed"]),
    ).all()
    for open_row in open_rows:
        if effective_status(open_row, now) == "expired":
            open_row.status, open_row.token_hash = "expired", None
        else:
            raise _error(status.HTTP_409_CONFLICT, "invitation_pending", "An invitation for this email is already open. Resend or revoke it instead.", invitation_id=open_row.id)

    limit = _seat_limit(db, org)
    if limit is not None:
        pending = db.query(TeamInvitation).filter(TeamInvitation.organization_id == org.id, TeamInvitation.status == "pending", TeamInvitation.expires_at > now).count()
        if _active_member_count(db, org) + pending >= limit:
            raise _error(status.HTTP_402_PAYMENT_REQUIRED, "seat_limit_reached", "All seats included in your plan are in use or reserved by open invitations.", limit=limit)

    row = TeamInvitation(organization_id=org.id, email=email, role=role, status="pending", invited_by_user_id=inviter.id, locale=_locale(locale), delivery_attempts=0)
    db.add(row)
    db.flush()
    logger.info("team_invitation.created invitation_id=%s org_id=%s role=%s", row.id, org.id, role)
    result = _deliver(db, row, org, inviter)
    return row, result


def resend_invitation(db: Session, *, org: Organization, inviter: User, invitation_id: str) -> tuple[TeamInvitation, dict]:
    row = _org_invitation(db, org, invitation_id)
    state = effective_status(row)
    if state not in {"pending", "delivery_failed", "expired"}:
        raise _error(status.HTTP_409_CONFLICT, "invitation_not_resendable", "This invitation can no longer be resent.", status=state)
    if (row.delivery_attempts or 0) >= MAX_DELIVERY_ATTEMPTS:
        raise _error(status.HTTP_429_TOO_MANY_REQUESTS, "invitation_resend_limit", "This invitation has been sent the maximum number of times. Revoke it and create a new one.")
    if row.last_sent_at and datetime.utcnow() - row.last_sent_at < RESEND_MIN_INTERVAL:
        raise _error(status.HTTP_429_TOO_MANY_REQUESTS, "invitation_resend_too_soon", "Please wait a minute before resending.")
    result = _deliver(db, row, org, inviter)  # rotates the token: the previous link stops working
    return row, result


def revoke_invitation(db: Session, *, org: Organization, invitation_id: str) -> TeamInvitation:
    row = _org_invitation(db, org, invitation_id)
    if row.status == "accepted":
        raise _error(status.HTTP_409_CONFLICT, "invitation_already_accepted", "This invitation was already accepted.")
    row.status, row.token_hash, row.revoked_at = "revoked", None, datetime.utcnow()
    db.commit()
    db.refresh(row)
    logger.info("team_invitation.revoked invitation_id=%s org_id=%s", row.id, org.id)
    return row


def _org_invitation(db: Session, org: Organization, invitation_id: str) -> TeamInvitation:
    row = db.get(TeamInvitation, invitation_id)
    if not row or row.organization_id != org.id:
        raise _error(status.HTTP_404_NOT_FOUND, "invitation_not_found", "Invitation not found.")
    return row


def redeemable_invitation(db: Session, token: str, *, lock: bool = False) -> TeamInvitation:
    """Resolve a link token to an open invitation, or fail with a precise reason."""
    if not token or len(token) > 200:
        raise _error(status.HTTP_404_NOT_FOUND, "invitation_invalid", "This invitation link is invalid or has already been used.")
    query = db.query(TeamInvitation).filter(TeamInvitation.token_hash == hash_invitation_token(token))
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "invitation_invalid", "This invitation link is invalid or has already been used.")
    if effective_status(row) == "expired":
        row.status, row.token_hash = "expired", None
        db.commit()
        raise _error(status.HTTP_410_GONE, "invitation_expired", "This invitation has expired. Ask your administrator to send a new one.")
    if row.status != "pending":
        raise _error(status.HTTP_404_NOT_FOUND, "invitation_invalid", "This invitation link is invalid or has already been used.")
    return row


def accept_invitation_for_user(db: Session, *, row: TeamInvitation, user: User) -> OrganizationMembership:
    """Create (or confirm) the membership for the invited account and consume the token."""
    if (user.email or "").strip().lower() != row.email:
        raise _error(status.HTTP_403_FORBIDDEN, "invitation_email_mismatch", "This invitation was sent to a different email address. Sign in with that account to accept it.")
    org = db.get(Organization, row.organization_id)
    membership = db.query(OrganizationMembership).filter(
        OrganizationMembership.organization_id == row.organization_id, OrganizationMembership.user_id == user.id
    ).first()
    if membership is None:
        limit = _seat_limit(db, org)
        if limit is not None and _active_member_count(db, org) >= limit:
            raise _error(status.HTTP_402_PAYMENT_REQUIRED, "seat_limit_reached", "This organization has no free seats. Ask your administrator to add seats.")
        membership = OrganizationMembership(organization_id=row.organization_id, user_id=user.id, role=row.role, status="active")
        db.add(membership)
    row.status, row.token_hash = "accepted", None
    row.accepted_at, row.accepted_by_user_id = datetime.utcnow(), user.id
    db.flush()
    logger.info("team_invitation.accepted invitation_id=%s org_id=%s user_id=%s role=%s", row.id, row.organization_id, user.id, membership.role)
    return membership
