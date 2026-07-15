"""Protected production API for previewing, sending, and measuring AGRO-AI outreach."""
from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import replace
from html import escape
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .config import OutreachSettings
from .resend_client import ResendClient, ResendError
from .schemas import BatchSendRequest, OutreachProspect, PreviewRequest, SendRequest, SuppressionRequest, VerificationStatus
from .store import store
from .templates import RenderedEmail, render_email
from .tokens import InvalidUnsubscribeToken, create_unsubscribe_token, verify_unsubscribe_token
from .tracking import InvalidTrackingToken, create_tracking_token, verify_tracking_token


# This router is mounted inside product_shell_router, which production app.main
# already mounts with prefix="/v1". Final public paths are /v1/outreach/*.
router = APIRouter(prefix="/outreach", tags=["outreach"])
settings = OutreachSettings.from_env()
resend = ResendClient(settings)
SENDABLE_STATUSES = {
    VerificationStatus.verified_public_direct,
    VerificationStatus.verified_public_role,
    VerificationStatus.verified_vendor,
    VerificationStatus.first_party_signup,
}
_PIXEL_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
_TRACKED_LINK_KEYS = ("portal", "meeting", "video", "live_demo")


def _require_admin(x_outreach_token: str | None = Header(default=None)) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="OUTREACH_ADMIN_TOKEN is not configured")
    if not x_outreach_token or not hmac.compare_digest(x_outreach_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Invalid outreach admin token")


def _tracking_destinations() -> dict[str, str]:
    return {
        "portal": settings.enterprise_portal_url,
        "meeting": settings.calendly_url,
        "video": settings.launch_video_url,
        "live_demo": settings.live_demo_url,
    }


def _instrument_rendered(rendered: RenderedEmail, *, send_id: str) -> RenderedEmail:
    token = quote(create_tracking_token(send_id=send_id, secret=settings.unsubscribe_secret))
    base = settings.public_api_base_url
    open_url = f"{base}/v1/outreach/t/open?token={token}"
    html = rendered.html
    for link_key, destination in _tracking_destinations().items():
        tracked = f"{base}/v1/outreach/t/click/{link_key}?token={token}"
        html = html.replace(
            escape(destination, quote=True),
            escape(tracked, quote=True),
        )
    pixel = (
        f'<img src="{escape(open_url, quote=True)}" width="1" height="1" alt="" '
        'style="display:block;width:1px;height:1px;border:0;opacity:0;overflow:hidden;">'
    )
    html = html.replace("</body>", f"{pixel}</body>")
    return replace(rendered, html=html)


def _rendered(
    prospect: OutreachProspect,
    *,
    engagement_tracking: bool = False,
    send_id: str | None = None,
) -> RenderedEmail:
    if not settings.unsubscribe_secret:
        raise HTTPException(status_code=503, detail="OUTREACH_UNSUBSCRIBE_SECRET is not configured")
    token = create_unsubscribe_token(prospect.email, settings.unsubscribe_secret)
    url = f"{settings.public_api_base_url}/v1/outreach/unsubscribe?token={quote(token)}"
    rendered = render_email(prospect, settings, unsubscribe_url=url)
    if not engagement_tracking:
        return rendered
    if not send_id:
        raise ValueError("send_id is required when engagement tracking is enabled")
    return _instrument_rendered(rendered, send_id=send_id)


def _assert_sendable(prospect: OutreachProspect) -> None:
    if prospect.email_verification_status not in SENDABLE_STATUSES:
        raise HTTPException(status_code=422, detail="Recipient email is not sendable. Guessed or pattern-inferred addresses cannot be sent.")
    if store.is_suppressed(prospect.email):
        raise HTTPException(status_code=409, detail="Recipient is on the suppression list")


def _assert_live_localization(rendered: RenderedEmail) -> None:
    if rendered.language != "en" and not rendered.localization_ready:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Non-English live send blocked because dynamic personalization is not fully localized.",
                "resolved_language": rendered.language,
                "required": [
                    "localized_observation",
                    "localized_pilot_wedge",
                    "localized_role_relevance when role_relevance is populated",
                    "localized_why_now when why_now is populated",
                    "localized_subject when a custom subject is populated",
                ],
                "rule": "The machine refuses mixed-language customer emails.",
            },
        )


def _idempotency_key(prospect: OutreachProspect, rendered: RenderedEmail) -> str:
    raw = (
        f"agroai-outreach-v4|{prospect.message_type.value}|{prospect.prospect_id}|"
        f"{prospect.email}|{rendered.language}|{rendered.subject}"
    ).encode("utf-8")
    return "agroai-" + hashlib.sha256(raw).hexdigest()


def _language_metadata(rendered: RenderedEmail) -> dict[str, Any]:
    return {
        "language": rendered.language,
        "language_source": rendered.language_source,
        "language_confidence": rendered.language_confidence,
        "localization_ready": rendered.localization_ready,
    }


def _message_metadata(prospect: OutreachProspect) -> dict[str, Any]:
    return {
        "message_type": prospect.message_type.value,
        "recipient_provenance": prospect.email_verification_status.value,
    }


def _execute_one(prospect: OutreachProspect, *, send_now: bool) -> dict[str, Any]:
    _assert_sendable(prospect)
    base_rendered = _rendered(prospect)
    key = _idempotency_key(prospect, base_rendered)
    live = bool(send_now and not settings.dry_run)

    if not live:
        record_id = store.log_send(
            prospect_id=prospect.prospect_id,
            email=prospect.email,
            account=prospect.account,
            subject=base_rendered.subject,
            status="preview",
            idempotency_key=key,
            dry_run=True,
            metadata={
                "verification": prospect.email_verification_status.value,
                "requested_send_now": send_now,
                "server_dry_run": settings.dry_run,
                "engagement_tracking": False,
                **_message_metadata(prospect),
                **_language_metadata(base_rendered),
            },
        )
        return {
            "status": "preview",
            "record_id": record_id,
            "prospect_id": prospect.prospect_id,
            "email": prospect.email,
            "account": prospect.account,
            "subject": base_rendered.subject,
            "reply_to": settings.reply_to,
            **_message_metadata(prospect),
            **_language_metadata(base_rendered),
            "send_now_requested": send_now,
            "server_dry_run": settings.dry_run,
            "engagement_tracking": False,
        }

    _assert_live_localization(base_rendered)

    if not settings.send_ready:
        raise HTTPException(status_code=503, detail="Live sending requires OUTREACH_RESEND_API_KEY, OUTREACH_ADMIN_TOKEN, and OUTREACH_UNSUBSCRIBE_SECRET")
    if store.count_live_sends_last_24h() >= settings.daily_send_limit:
        raise HTTPException(status_code=429, detail=f"Daily outreach limit reached ({settings.daily_send_limit} live sends / 24h)")

    tracking_send_id = str(uuid.uuid4())
    rendered = _rendered(prospect, engagement_tracking=True, send_id=tracking_send_id)
    common_metadata = {
        "verification": prospect.email_verification_status.value,
        "engagement_tracking": True,
        "tracked_links": list(_TRACKED_LINK_KEYS),
        **_message_metadata(prospect),
        **_language_metadata(rendered),
    }

    try:
        result = resend.send(
            to=prospect.email,
            rendered=rendered,
            idempotency_key=key,
            account_tag=prospect.account.lower().replace("&", "and").replace(" ", "_")[:200],
        )
    except ResendError as exc:
        record_id = store.log_send(
            record_id=tracking_send_id,
            prospect_id=prospect.prospect_id,
            email=prospect.email,
            account=prospect.account,
            subject=rendered.subject,
            status="failed",
            idempotency_key=key,
            dry_run=False,
            error_text=str(exc),
            metadata={"resend_status_code": exc.status_code, **common_metadata},
        )
        raise HTTPException(status_code=502, detail={"message": str(exc), "record_id": record_id}) from exc

    record_id = store.log_send(
        record_id=tracking_send_id,
        prospect_id=prospect.prospect_id,
        email=prospect.email,
        account=prospect.account,
        subject=rendered.subject,
        status="sent",
        idempotency_key=key,
        dry_run=False,
        resend_id=result.id,
        metadata=common_metadata,
    )
    return {
        "status": "sent",
        "record_id": record_id,
        "resend_id": result.id,
        "prospect_id": prospect.prospect_id,
        "email": prospect.email,
        "account": prospect.account,
        "subject": rendered.subject,
        "reply_to": settings.reply_to,
        "engagement_tracking": True,
        **_message_metadata(prospect),
        **_language_metadata(rendered),
    }


def _pixel_response() -> Response:
    return Response(
        content=_PIXEL_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, max-age=0, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@router.get("/t/open", include_in_schema=False)
async def track_open(request: Request, token: str = Query(min_length=20, max_length=1000)) -> Response:
    try:
        identity = verify_tracking_token(token, settings.unsubscribe_secret)
    except InvalidTrackingToken:
        return _pixel_response()
    store.log_event(
        send_id=identity.send_id,
        event_type="first_party.opened",
        user_agent=request.headers.get("user-agent", ""),
        metadata={"measurement": "email_client_image_load"},
    )
    return _pixel_response()


@router.get("/t/click/{link_key}", include_in_schema=False)
async def track_click(
    request: Request,
    link_key: str,
    token: str = Query(min_length=20, max_length=1000),
) -> RedirectResponse:
    destination = _tracking_destinations().get(link_key)
    if destination is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown outreach link")
    try:
        identity = verify_tracking_token(token, settings.unsubscribe_secret)
    except InvalidTrackingToken as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tracking link") from exc
    send = store.get_send(identity.send_id)
    if not send or send.get("status") != "sent" or bool(send.get("dry_run")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tracking link")
    store.log_event(
        send_id=identity.send_id,
        event_type=f"first_party.clicked.{link_key}",
        link_key=link_key,
        user_agent=request.headers.get("user-agent", ""),
        metadata={"destination_class": link_key},
    )
    return RedirectResponse(
        url=destination,
        status_code=status.HTTP_302_FOUND,
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


@router.get("/status")
async def outreach_status(_: None = Depends(_require_admin)) -> dict[str, Any]:
    try:
        live_sends = store.count_live_sends_last_24h()
        store.recent_events(limit=1)
        ledger_ready = True
        engagement_ready = True
    except Exception:
        live_sends = None
        ledger_ready = False
        engagement_ready = False
    return {
        "configured": settings.preview_ready,
        "send_ready": settings.send_ready,
        "dry_run": settings.dry_run,
        "sender": settings.sender,
        "reply_to": settings.reply_to,
        "resend_key_variable": "OUTREACH_RESEND_API_KEY",
        "launch_video_url": settings.launch_video_url,
        "launch_video_thumbnail_url": settings.launch_video_thumbnail_url,
        "thumbnail_profile": "hd_16_9",
        "live_demo_url": settings.live_demo_url,
        "live_demo_thumbnail_url": settings.live_demo_thumbnail_url,
        "live_demo_thumbnail_profile": "hd_16_9_maxres",
        "daily_send_limit": settings.daily_send_limit,
        "live_sends_last_24h": live_sends,
        "max_batch_size": settings.max_batch_size,
        "ledger_ready": ledger_ready,
        "engagement_tracking": {
            "ready": engagement_ready,
            "live_html_sends_only": True,
            "open_signal": "first_party_pixel_approximate",
            "clicks": list(_TRACKED_LINK_KEYS),
            "preview_tracking": "disabled",
            "ip_fingerprinting": "disabled",
        },
        "supported_message_types": ["cold_outreach", "post_signup_founder_followup"],
        "first_party_signup_followup": {
            "enabled": True,
            "cold_outreach_use": "blocked",
            "lifecycle_language": "en",
        },
        "multilingual_outreach": {
            "supported_languages": ["en", "fr", "es", "pt", "ar"],
            "auto_country_routing": True,
            "explicit_override": True,
            "mixed_language_live_sends": "blocked",
            "ambiguous_global_accounts": "english_fallback_unless_overridden",
        },
        "outreach_release": "production-live-demo-hd-cta-engagement-v2",
        "email_integrity_rule": "guessed or pattern-inferred addresses are refused; first-party signup addresses are lifecycle-only",
    }


@router.post("/preview")
async def preview_email(payload: PreviewRequest, _: None = Depends(_require_admin)) -> dict[str, Any]:
    rendered = _rendered(payload.prospect, engagement_tracking=False)
    return {
        "prospect_id": payload.prospect.prospect_id,
        "to": payload.prospect.email,
        "from": settings.sender,
        "reply_to": settings.reply_to,
        "subject": rendered.subject,
        **_message_metadata(payload.prospect),
        **_language_metadata(rendered),
        "engagement_tracking": False,
        "html": rendered.html,
        "text": rendered.text,
        "unsubscribe_url": rendered.unsubscribe_url,
    }


@router.post("/send")
async def send_email(payload: SendRequest, _: None = Depends(_require_admin)) -> dict[str, Any]:
    return _execute_one(payload.prospect, send_now=payload.send_now)


@router.post("/batch")
async def send_batch(payload: BatchSendRequest, _: None = Depends(_require_admin)) -> dict[str, Any]:
    if len(payload.prospects) > settings.max_batch_size:
        raise HTTPException(status_code=422, detail=f"Batch exceeds configured maximum of {settings.max_batch_size}")
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for prospect in payload.prospects:
        try:
            results.append(_execute_one(prospect, send_now=payload.send_now))
        except HTTPException as exc:
            errors.append({"prospect_id": prospect.prospect_id, "email": prospect.email, "account": prospect.account, "status_code": exc.status_code, "detail": exc.detail})
            if payload.on_error == "stop":
                break
    return {"requested": len(payload.prospects), "completed": len(results), "errors": errors, "results": results, "send_now_requested": payload.send_now, "server_dry_run": settings.dry_run}


@router.post("/suppress")
async def suppress_recipient(payload: SuppressionRequest, _: None = Depends(_require_admin)) -> dict[str, str]:
    store.suppress(payload.email, payload.reason)
    return {"status": "suppressed", "email": payload.email.strip().lower(), "reason": payload.reason}


@router.get("/recent")
async def recent_sends(
    limit: int = Query(default=100, ge=1, le=1000),
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    rows = store.recent_sends(limit=limit)
    return {"count": len(rows), "items": rows}


@router.get("/engagement")
async def engagement_summary(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return store.engagement_summary()


@router.get("/events")
async def recent_events(
    limit: int = Query(default=250, ge=1, le=1000),
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    rows = store.recent_events(limit=limit)
    return {"count": len(rows), "items": rows}


@router.get("/unsubscribe", response_class=HTMLResponse)
@router.post("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: str = Query(min_length=20, max_length=2000)) -> HTMLResponse:
    try:
        email = verify_unsubscribe_token(token, settings.unsubscribe_secret)
    except InvalidUnsubscribeToken as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid unsubscribe link") from exc
    store.suppress(email, "recipient_unsubscribe")
    return HTMLResponse("""<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Unsubscribed · AGRO-AI</title></head><body style=\"margin:0;background:#f5f7f6;font-family:Arial,sans-serif;color:#17211c\"><div style=\"max-width:620px;margin:70px auto;padding:40px;background:#fff;border:1px solid #e3e8e5;border-radius:12px\"><div style=\"height:5px;background:#176b45;margin:-40px -40px 32px;border-radius:12px 12px 0 0\"></div><h1 style=\"font-size:26px;margin:0 0 12px\">You’re unsubscribed.</h1><p style=\"line-height:1.6;color:#526158\">AGRO-AI will not send further outreach to this address.</p></div></body></html>""")


__all__ = ["router"]
