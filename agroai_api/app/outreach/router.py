"""Protected production API for previewing and sending AGRO-AI outreach."""
from __future__ import annotations

import hashlib
import hmac
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from .config import OutreachSettings
from .resend_client import ResendClient, ResendError
from .schemas import BatchSendRequest, OutreachProspect, PreviewRequest, SendRequest, SuppressionRequest, VerificationStatus
from .store import store
from .templates import RenderedEmail, render_email
from .tokens import InvalidUnsubscribeToken, create_unsubscribe_token, verify_unsubscribe_token


# This router is mounted inside product_shell_router, which production app.main
# already mounts with prefix="/v1". Final public paths are /v1/outreach/*.
router = APIRouter(prefix="/outreach", tags=["outreach"])
settings = OutreachSettings.from_env()
resend = ResendClient(settings)
VERIFIED_STATUSES = {
    VerificationStatus.verified_public_direct,
    VerificationStatus.verified_public_role,
    VerificationStatus.verified_vendor,
}


def _require_admin(x_outreach_token: str | None = Header(default=None)) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="OUTREACH_ADMIN_TOKEN is not configured")
    if not x_outreach_token or not hmac.compare_digest(x_outreach_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Invalid outreach admin token")


def _rendered(prospect: OutreachProspect) -> RenderedEmail:
    if not settings.unsubscribe_secret:
        raise HTTPException(status_code=503, detail="OUTREACH_UNSUBSCRIBE_SECRET is not configured")
    token = create_unsubscribe_token(prospect.email, settings.unsubscribe_secret)
    url = f"{settings.public_api_base_url}/v1/outreach/unsubscribe?token={quote(token)}"
    return render_email(prospect, settings, unsubscribe_url=url)


def _assert_sendable(prospect: OutreachProspect) -> None:
    if prospect.email_verification_status not in VERIFIED_STATUSES:
        raise HTTPException(status_code=422, detail="Recipient email is not verified. Guessed or pattern-inferred addresses cannot be sent.")
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
    raw = f"agroai-outreach-v3|{prospect.prospect_id}|{prospect.email}|{rendered.language}|{rendered.subject}".encode("utf-8")
    return "agroai-" + hashlib.sha256(raw).hexdigest()


def _language_metadata(rendered: RenderedEmail) -> dict[str, Any]:
    return {
        "language": rendered.language,
        "language_source": rendered.language_source,
        "language_confidence": rendered.language_confidence,
        "localization_ready": rendered.localization_ready,
    }


def _execute_one(prospect: OutreachProspect, *, send_now: bool) -> dict[str, Any]:
    _assert_sendable(prospect)
    rendered = _rendered(prospect)
    key = _idempotency_key(prospect, rendered)
    live = bool(send_now and not settings.dry_run)

    if not live:
        record_id = store.log_send(
            prospect_id=prospect.prospect_id,
            email=prospect.email,
            account=prospect.account,
            subject=rendered.subject,
            status="preview",
            idempotency_key=key,
            dry_run=True,
            metadata={
                "verification": prospect.email_verification_status.value,
                "requested_send_now": send_now,
                "server_dry_run": settings.dry_run,
                **_language_metadata(rendered),
            },
        )
        return {
            "status": "preview",
            "record_id": record_id,
            "prospect_id": prospect.prospect_id,
            "email": prospect.email,
            "account": prospect.account,
            "subject": rendered.subject,
            "reply_to": settings.reply_to,
            **_language_metadata(rendered),
            "send_now_requested": send_now,
            "server_dry_run": settings.dry_run,
        }

    _assert_live_localization(rendered)

    if not settings.send_ready:
        raise HTTPException(status_code=503, detail="Live sending requires OUTREACH_RESEND_API_KEY, OUTREACH_ADMIN_TOKEN, and OUTREACH_UNSUBSCRIBE_SECRET")
    if store.count_live_sends_last_24h() >= settings.daily_send_limit:
        raise HTTPException(status_code=429, detail=f"Daily outreach limit reached ({settings.daily_send_limit} live sends / 24h)")

    try:
        result = resend.send(
            to=prospect.email,
            rendered=rendered,
            idempotency_key=key,
            account_tag=prospect.account.lower().replace("&", "and").replace(" ", "_")[:200],
        )
    except ResendError as exc:
        record_id = store.log_send(
            prospect_id=prospect.prospect_id,
            email=prospect.email,
            account=prospect.account,
            subject=rendered.subject,
            status="failed",
            idempotency_key=key,
            dry_run=False,
            error_text=str(exc),
            metadata={
                "verification": prospect.email_verification_status.value,
                "resend_status_code": exc.status_code,
                **_language_metadata(rendered),
            },
        )
        raise HTTPException(status_code=502, detail={"message": str(exc), "record_id": record_id}) from exc

    record_id = store.log_send(
        prospect_id=prospect.prospect_id,
        email=prospect.email,
        account=prospect.account,
        subject=rendered.subject,
        status="sent",
        idempotency_key=key,
        dry_run=False,
        resend_id=result.id,
        metadata={"verification": prospect.email_verification_status.value, **_language_metadata(rendered)},
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
        **_language_metadata(rendered),
    }


@router.get("/status")
async def outreach_status(_: None = Depends(_require_admin)) -> dict[str, Any]:
    try:
        live_sends = store.count_live_sends_last_24h()
        ledger_ready = True
    except Exception:
        live_sends = None
        ledger_ready = False
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
        "daily_send_limit": settings.daily_send_limit,
        "live_sends_last_24h": live_sends,
        "max_batch_size": settings.max_batch_size,
        "ledger_ready": ledger_ready,
        "multilingual_outreach": {
            "supported_languages": ["en", "fr", "es", "pt", "ar"],
            "auto_country_routing": True,
            "explicit_override": True,
            "mixed_language_live_sends": "blocked",
            "ambiguous_global_accounts": "english_fallback_unless_overridden",
        },
        "outreach_release": "production-i18n-hd-thumbnail-v1",
        "email_integrity_rule": "unverified addresses are refused",
    }


@router.post("/preview")
async def preview_email(payload: PreviewRequest, _: None = Depends(_require_admin)) -> dict[str, Any]:
    rendered = _rendered(payload.prospect)
    return {
        "prospect_id": payload.prospect.prospect_id,
        "to": payload.prospect.email,
        "from": settings.sender,
        "reply_to": settings.reply_to,
        "subject": rendered.subject,
        **_language_metadata(rendered),
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
