"""Lifecycle onboarding email endpoints: unsubscribe, provider events, admin view."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform_admin
from app.core.config import settings
from app.core.rate_limiting import limiter
from app.db.base import get_db
from app.models.lifecycle_email import LifecycleEmailEnrollment, LifecycleEmailSend
from app.models.saas import User
from app.services import lifecycle_emails
from app.services.lifecycle_email_i18n import LifecycleLocalizationUnavailable, localized_copy, resolve_locale, source_catalog

router = APIRouter(tags=["lifecycle-email"])
logger = logging.getLogger("agroai.lifecycle_email")


def _page_copy(db: Session, request: Request, user: User | None) -> tuple[dict[str, str], str]:
    preference_locale = None
    if user is not None:
        from app.models.saas import UserPreference

        preference = db.get(UserPreference, user.id)
        preference_locale = getattr(preference, "locale", None)
    accept = (request.headers.get("accept-language") or "").split(",")[0].split(";")[0]
    locale = resolve_locale(preference_locale, accept)
    try:
        copy, _how = localized_copy(locale)
    except LifecycleLocalizationUnavailable:
        # An interactive confirmation page cannot be deferred like an email.
        logger.error("lifecycle_unsubscribe_page_localization_unavailable locale=%s", locale)
        copy, locale = source_catalog(), "en"
    return copy, locale


def _page(locale: str, title: str, body: str, form: str = "") -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="{escape(locale, quote=True)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>AGRO-AI</title></head>
<body style="margin:0;background:#f6f3ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#10231b;">
<main style="max-width:520px;margin:48px auto;background:#fff;border:1px solid #e5e0d6;border-radius:18px;padding:32px;">
<div style="font-size:13px;letter-spacing:0.18em;text-transform:uppercase;color:#0b6b43;font-weight:700;">AGRO-AI</div>
<h1 style="font-size:22px;line-height:1.3;">{escape(title)}</h1><p style="font-size:15px;line-height:1.6;color:#4b5a51;">{escape(body)}</p>{form}</main></body></html>""",
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"},
    )


def _user_for_token(db: Session, user_id: str, token: str) -> User | None:
    if not lifecycle_emails.verify_unsubscribe_token(user_id, token):
        return None
    return db.get(User, user_id)


@router.get("/email/lifecycle/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
@limiter.limit("30/minute")
def unsubscribe_page(request: Request, u: str = "", t: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    # GET never unsubscribes: mail scanners prefetch links. A button confirms.
    user = _user_for_token(db, u, t)
    copy, locale = _page_copy(db, request, user)
    if user is None:
        return _page(locale, "AGRO-AI", copy["unsubscribe.invalid"])
    form = (
        f'<form method="post" action="/v1/email/lifecycle/unsubscribe?u={escape(u, quote=True)}&amp;t={escape(t, quote=True)}">'
        f'<button type="submit" style="background:#0b3326;color:#fff;border:0;border-radius:10px;padding:12px 22px;font-size:15px;font-weight:700;">{escape(copy["unsubscribe.confirm"])}</button></form>'
    )
    return _page(locale, copy["common.unsubscribe"], copy["common.unsubscribe_note"], form)


@router.post("/email/lifecycle/unsubscribe", include_in_schema=False)
@limiter.limit("30/minute")
async def unsubscribe_confirm(request: Request, u: str = "", t: str = "", db: Session = Depends(get_db)):
    """Form confirmation and RFC 8058 one-click (List-Unsubscribe-Post) unsubscribe."""
    user = _user_for_token(db, u, t)
    one_click = "one-click" in (await request.body()).decode("utf-8", "ignore").lower()
    copy, locale = _page_copy(db, request, user)
    if user is None:
        if one_click:
            return JSONResponse({"status": "invalid"}, status_code=400)
        return _page(locale, "AGRO-AI", copy["unsubscribe.invalid"])
    lifecycle_emails.unsubscribe(db, user.id, source="one_click" if one_click else "link")
    if one_click:
        return JSONResponse({"status": "unsubscribed"})
    return _page(locale, copy["unsubscribe.title"], copy["unsubscribe.body"])


def _verify_resend_signature(raw: bytes, headers) -> None:
    secret = (settings.RESEND_WEBHOOK_SECRET or "").strip()
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email provider events are not configured")
    message_id = headers.get("svix-id") or ""
    timestamp = headers.get("svix-timestamp") or ""
    signatures = headers.get("svix-signature") or ""
    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("stale")
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
    except (ValueError, IndexError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")
    expected = base64.b64encode(hmac.new(key, f"{message_id}.{timestamp}.".encode() + raw, hashlib.sha256).digest()).decode()
    provided = [part.split(",", 1)[1] for part in signatures.split() if "," in part]
    if not any(hmac.compare_digest(expected, value) for value in provided):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")


@router.post("/email/provider-events", include_in_schema=False)
async def provider_events(request: Request, db: Session = Depends(get_db)) -> dict:
    """Resend webhook: delivery, open, click, bounce and complaint for lifecycle sends."""
    raw = await request.body()
    _verify_resend_signature(raw, request.headers)
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    kind = str(event.get("type") or "")
    data = event.get("data") or {}
    message_id = str(data.get("email_id") or "")
    now = datetime.utcnow()
    row = db.query(LifecycleEmailSend).filter(LifecycleEmailSend.provider_message_id == message_id).first() if message_id else None
    column = {"email.delivered": "delivered_at", "email.opened": "opened_at", "email.clicked": "clicked_at", "email.bounced": "bounced_at"}.get(kind)
    if row is not None and column and getattr(row, column) is None:
        setattr(row, column, now)
    if kind in {"email.bounced", "email.complained"}:
        recipients = [str(value).strip().lower() for value in (data.get("to") or []) if value]
        users = db.query(User).filter(User.email.in_(recipients)).all() if recipients else []
        user_ids = {user.id for user in users} | ({row.user_id} if row is not None else set())
        for user_id in user_ids:
            enrollment = db.get(LifecycleEmailEnrollment, user_id)
            if enrollment is None:
                continue
            if kind == "email.complained":
                enrollment.unsubscribed_at = enrollment.unsubscribed_at or now
                lifecycle_emails._stop(enrollment, "complained")
            elif str((data.get("bounce") or {}).get("type") or "").lower() != "transient":
                lifecycle_emails._stop(enrollment, "address_bounced")
    db.commit()
    logger.info("lifecycle_email_provider_event type=%s matched=%s", kind, row is not None)
    return {"received": True}


@router.get("/admin/lifecycle-emails/{user_id}", include_in_schema=False)
def lifecycle_state(user_id: str, _admin: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)) -> dict:
    """Engineering view of one user's lifecycle sequence (platform administrators only)."""
    return lifecycle_emails.describe(db, user_id)
