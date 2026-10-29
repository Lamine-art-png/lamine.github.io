"""One-time, opt-in Academy A1 launch notice. Only activated by an operator-controlled Render environment flag.

Uses the existing production database and Resend credential. No public admin route,
hardcoded recipients, credential export or public audience artifact.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.saas import SaaSRequest

logger = logging.getLogger(__name__)
CAMPAIGN = "academy-a1-live-2026-10-29-v1"
SOURCE = "academy/early-access"
SUBJECT = "Your early access starts now — AGRO-AI Academy is open"
SENDER = "AGRO-AI Academy <academy@mail.agroai-pilot.com>"
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "email_templates"
ALLOWED_AUDIT_DOMAINS = {"gmail.com"}
MAX_AUDIENCE = 2500


def _email(s: str) -> str:
    value = str(s or "").strip().lower()
    if not re.fullmatch(r"[^\s@,]+@[^\s@,]+\.[a-zA-Z]{2,}", value):
        return ""
    return value


def _consent(meta: dict[str, Any]) -> bool:
    value = meta.get("email_opt_in")
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _current_status(row: SaaSRequest) -> str:
    return str(((row.metadata_json or {}).get("academy_campaign_delivery") or {}).get(CAMPAIGN, {}).get("status") or "")


def _save_status(db: Session, rows: list[SaaSRequest], *, status: str, provider_id: str = "", reason: str = "") -> None:
    changed = datetime.now(timezone.utc).isoformat()
    for row in rows:
        meta = dict(row.metadata_json or {})
        original = dict(meta.get("academy_campaign_delivery") or {})
        original[CAMPAIGN] = {
            "status": status,
            "at": changed,
            "provider": "resend",
            **({"provider_id": provider_id} if provider_id else {}),
            **({"reason": reason[:90]} if reason else {}),
        }
        meta["academy_campaign_delivery"] = original
        row.metadata_json = meta
        db.add(row)
    db.commit()


def _render(name: str, h: str, t: str) -> tuple[str, str]:
    clean = " ".join(str(name or "").split())
    first = re.sub(r"[^\w\-'.\u00c0-\u024f]", "", clean.split()[0])[:60] if clean else ""
    first = first or "there"
    return h.replace("{{first_name}}", html.escape(first, quote=True)), t.replace("{{first_name}}", first)


def send_academy_launch_once() -> dict[str, int]:
    """Deliberate, idempotent one-time batch. Never expose recipients or credentials in logs."""
    if os.environ.get("AGROAI_ACADEMY_A1_LAUNCH_SEND") != CAMPAIGN:
        return {"not_enabled": 1}
    audit = _email(os.environ.get("AGROAI_ACADEMY_A1_LAUNCH_BCC", ""))
    if audit != "dabolamine811@gmail.com" or audit.rsplit("@", 1)[-1] not in ALLOWED_AUDIT_DOMAINS:
        logger.error("ACADEMY_CAMPAIGN_BLOCKED: missing or incorrect approved private BCC")
        return {"blocked": 1}
    if not settings.RESEND_API_KEY or not str(settings.RESEND_API_KEY).startswith("re_"):
        logger.error("ACADEMY_CAMPAIGN_BLOCKED: existing production Resend credential unavailable")
        return {"blocked": 1}
    if "mail.agroai-pilot.com" != parseaddr(str(settings.FROM_EMAIL))[1].rsplit("@", 1)[-1].lower():
        logger.error("ACADEMY_CAMPAIGN_BLOCKED: production Resend domain not verified in sender config")
        return {"blocked": 1}
    h = (TEMPLATE_DIR / "academy_launch_20261029.html").read_text(encoding="utf-8")
    t = (TEMPLATE_DIR / "academy_launch_20261029.txt").read_text(encoding="utf-8")
    if any("{{first_name}}" not in x for x in (h, t)) or "https://academy.agroai-pilot.com/" not in h or "https://agroai-pilot.com/news/agro-ai-academy-courses-now-open" not in h:
        logger.error("ACADEMY_CAMPAIGN_BLOCKED: invalid or stale templates")
        return {"blocked": 1}
    excluded = {_email(e) for e in os.environ.get("AGROAI_ACADEMY_A1_LAUNCH_EXCLUDES", "").split(",")}
    excluded.update({"laminedabo221@outlook.com", "contact@agroai-pilot.com", "daabolaamiine@gmail.com", audit})
    results = {"eligible": 0, "accepted": 0, "failed": 0, "previous": 0, "skipped": 0}
    with SessionLocal() as db:
        rows = (
            db.query(SaaSRequest)
            .filter(SaaSRequest.source_page == SOURCE)
            .order_by(SaaSRequest.created_at.asc())
            .all()
        )
        groups: dict[str, list[SaaSRequest]] = defaultdict(list)
        for row in rows:
            meta = row.metadata_json or {}
            email = _email(row.email)
            if (
                not email or email in excluded or email.endswith(".test") or
                email.endswith(".invalid") or "example." in email or not _consent(meta)
            ):
                results["skipped"] += 1
                continue
            groups[email].append(row)
        results["eligible"] = len(groups)
        logger.info("ACADEMY_CAMPAIGN_AUDIENCE eligible=%s excluded_or_not_opted=%s", len(groups), results["skipped"])
        if not 1 <= len(groups) <= MAX_AUDIENCE:
            logger.error("ACADEMY_CAMPAIGN_BLOCKED: audience count outside approved bounds")
            return {**results, "blocked": 1}
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            for index, (recipient, duplicate_rows) in enumerate(groups.items(), 1):
                if any(_current_status(row) in {"reserved", "accepted"} for row in duplicate_rows):
                    results["previous"] += 1
                    continue
                body, plain = _render(duplicate_rows[0].name or "", h, t)
                message = {
                    "from": SENDER,
                    "to": [recipient],
                    "bcc": [audit],
                    "reply_to": "contact@agroai-pilot.com",
                    "subject": SUBJECT,
                    "html": body,
                    "text": plain,
                    "tags": [{"name": "campaign", "value": "academy-a1-launch-20261029"}],
                }
                request_headers = {
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": f"academy-a1-launch-20261029-{hashlib.sha256(recipient.encode()).hexdigest()[:24]}",
                }
                _save_status(db, duplicate_rows, status="reserved")
                try:
                    response = client.post("https://api.resend.com/emails", json=message, headers=request_headers)
                    data = response.json() if response.content else {}
                    provider_id = str(data.get("id") or "")
                    if 200 <= response.status_code < 300 and provider_id:
                        _save_status(db, duplicate_rows, status="accepted", provider_id=provider_id)
                        results["accepted"] += 1
                        logger.info("ACADEMY_CAMPAIGN_ACCEPTED index=%s of=%s id=%s", index, len(groups), provider_id)
                    else:
                        reason = str(data.get("name") or data.get("message") or "provider_rejected")[:80]
                        _save_status(db, duplicate_rows, status="failed", reason=reason)
                        results["failed"] += 1
                        logger.error("ACADEMY_CAMPAIGN_REJECTED index=%s status=%s reason=%s", index, response.status_code, reason)
                        if response.status_code in (401, 403, 422):
                            logger.error("ACADEMY_CAMPAIGN_STOP: authorization or provider validation")
                            break
                        if response.status_code == 429:
                            logger.error("ACADEMY_CAMPAIGN_STOP: Resend rate limit")
                            break
                except (httpx.HTTPError, ValueError) as exc:
                    _save_status(db, duplicate_rows, status="unknown", reason=type(exc).__name__)
                    results["failed"] += 1
                    logger.error("ACADEMY_CAMPAIGN_STOP: network/unknown provider response after reservation")
                    break
                time.sleep(0.65)
    logger.warning("ACADEMY_CAMPAIGN_COMPLETE eligible=%s accepted=%s failed=%s previous=%s skipped=%s", *[results[k] for k in ("eligible", "accepted", "failed", "previous", "skipped")])
    return results
