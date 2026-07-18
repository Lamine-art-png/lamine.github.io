from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.platform_api import (
    PlatformWebhookDeliveryAttempt,
    PlatformWebhookEndpoint,
    PlatformWebhookEvent,
    PlatformWebhookOutbox,
)
from app.platform_api.webhooks import (
    resolve_webhook_destination,
    retrieve_webhook_secrets_for_delivery,
    webhook_signature,
)
from app.services.redis_task_queue import get_task_publisher


WEBHOOK_TASK_TYPE = "platform_webhook_delivery"
EVENT_VERSION = "2026-07-18"
_CLAIM_TIMEOUT = timedelta(minutes=5)
_MAX_REDIRECTS = 3


def emit_webhook_event(
    db: Session,
    *,
    organization_id: str,
    api_project_id: str,
    event_type: str,
    payload: dict,
) -> PlatformWebhookEvent:
    event = PlatformWebhookEvent(
        organization_id=organization_id,
        api_project_id=api_project_id,
        event_type=event_type,
        version=EVENT_VERSION,
        payload_json=dict(payload),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.flush()
    endpoints = (
        db.query(PlatformWebhookEndpoint)
        .filter(
            PlatformWebhookEndpoint.organization_id == organization_id,
            PlatformWebhookEndpoint.api_project_id == api_project_id,
            PlatformWebhookEndpoint.status == "active",
            PlatformWebhookEndpoint.revoked_at.is_(None),
        )
        .all()
    )
    now = datetime.utcnow()
    for endpoint in endpoints:
        if event_type not in set(endpoint.subscribed_event_types or []):
            continue
        db.add(
            PlatformWebhookOutbox(
                organization_id=organization_id,
                api_project_id=api_project_id,
                event_id=event.id,
                endpoint_id=endpoint.id,
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    return event


def _publishable(now: datetime):
    return or_(
        and_(
            PlatformWebhookOutbox.status.in_(["pending", "retrying"]),
            or_(
                PlatformWebhookOutbox.next_attempt_at.is_(None),
                PlatformWebhookOutbox.next_attempt_at <= now,
            ),
        ),
    )


def _deliverable(now: datetime):
    return or_(
        PlatformWebhookOutbox.status == "queued",
        and_(
            PlatformWebhookOutbox.status == "delivering",
            PlatformWebhookOutbox.claimed_at <= now - _CLAIM_TIMEOUT,
        ),
    )


def publish_pending_webhook_outbox(db: Session, *, limit: int = 100) -> dict[str, int]:
    if not bool(getattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", False)):
        return {"published": 0, "failed": 0, "disabled": 1}
    now = datetime.utcnow()
    rows = (
        db.query(PlatformWebhookOutbox)
        .filter(_publishable(now))
        .order_by(PlatformWebhookOutbox.created_at.asc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    if not rows:
        return {"published": 0, "failed": 0, "disabled": 0}
    queue = get_task_publisher()
    published = 0
    failed = 0
    for row in rows:
        try:
            queue.enqueue(row.id, row.organization_id, WEBHOOK_TASK_TYPE)
            row.status = "queued"
            row.updated_at = datetime.utcnow()
            db.commit()
            published += 1
        except Exception:
            db.rollback()
            failed += 1
    return {"published": published, "failed": failed, "disabled": 0}


def _pinned_url(destination, address: str) -> str:
    parsed = urlparse(destination.url)
    host = f"[{address}]" if ":" in address else address
    netloc = host if destination.port == 443 else f"{host}:{destination.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def _bounded_body(response: httpx.Response, max_bytes: int) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        remaining = max_bytes - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= max_bytes:
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


def _post_pinned(
    url: str,
    *,
    body: bytes,
    headers: dict[str, str],
    client: httpx.Client | None = None,
) -> tuple[int, str]:
    timeout = max(0.5, min(float(getattr(settings, "PLATFORM_API_WEBHOOK_TIMEOUT_SECONDS", 10.0)), 30.0))
    max_body = max(0, min(int(getattr(settings, "PLATFORM_API_WEBHOOK_MAX_RESPONSE_BYTES", 8192)), 65536))
    owned = client is None
    transport_client = client or httpx.Client(timeout=timeout, follow_redirects=False)
    current = url
    try:
        for redirect_count in range(_MAX_REDIRECTS + 1):
            destination = resolve_webhook_destination(current)
            address = destination.addresses[0]
            request_headers = dict(headers)
            request_headers["host"] = destination.hostname if destination.port == 443 else f"{destination.hostname}:{destination.port}"
            request = httpx.Request(
                "POST",
                _pinned_url(destination, address),
                headers=request_headers,
                content=body,
                extensions={"sni_hostname": destination.hostname.encode("ascii")},
            )
            response = transport_client.send(request, stream=True)
            try:
                excerpt = _bounded_body(response, max_body)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    return response.status_code, excerpt
                location = response.headers.get("location")
            finally:
                response.close()
            if not location or redirect_count >= _MAX_REDIRECTS:
                raise RuntimeError("webhook redirect policy rejected the response")
            current = urljoin(destination.url, location)
        raise RuntimeError("webhook redirect limit exceeded")
    finally:
        if owned:
            transport_client.close()


def process_webhook_delivery(
    db: Session,
    *,
    outbox_id: str,
    organization_id: str,
    worker_id: str,
    client: httpx.Client | None = None,
) -> str:
    if not bool(getattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", False)):
        return "disabled"
    now = datetime.utcnow()
    claimed = db.execute(
        update(PlatformWebhookOutbox)
        .where(
            PlatformWebhookOutbox.id == outbox_id,
            PlatformWebhookOutbox.organization_id == organization_id,
            _deliverable(now),
        )
        .values(status="delivering", claimed_at=now, updated_at=now)
    )
    db.commit()
    if claimed.rowcount != 1:
        row = db.get(PlatformWebhookOutbox, outbox_id)
        return row.status if row is not None else "failed"

    outbox = db.get(PlatformWebhookOutbox, outbox_id)
    endpoint = db.get(PlatformWebhookEndpoint, outbox.endpoint_id)
    event = db.get(PlatformWebhookEvent, outbox.event_id)
    if (
        endpoint is None
        or event is None
        or endpoint.organization_id != organization_id
        or endpoint.api_project_id != outbox.api_project_id
        or event.organization_id != organization_id
        or event.api_project_id != outbox.api_project_id
        or endpoint.status != "active"
        or endpoint.revoked_at is not None
    ):
        outbox.status = "failed"
        outbox.last_error = "endpoint_or_event_inactive"
        outbox.completed_at = datetime.utcnow()
        db.commit()
        return "failed"

    attempt_number = int(outbox.attempt_count or 0) + 1
    request_id = f"whd_{uuid.uuid4().hex}"
    attempt = PlatformWebhookDeliveryAttempt(
        event_id=event.id,
        endpoint_id=endpoint.id,
        attempt_number=attempt_number,
        request_id=request_id,
        status="delivering",
        started_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    db.add(attempt)
    outbox.attempt_count = attempt_number
    signing_secrets = retrieve_webhook_secrets_for_delivery(
        db,
        endpoint_id=endpoint.id,
        organization_id=organization_id,
        api_project_id=outbox.api_project_id,
        worker_id=worker_id,
        request_id=request_id,
    )
    db.commit()

    envelope = {
        "id": event.id,
        "type": event.event_type,
        "version": event.version,
        "created_at": event.created_at.isoformat() + "Z",
        "data": event.payload_json or {},
    }
    body = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.utcnow().timestamp()))
    headers = {
        "content-type": "application/json",
        "user-agent": "AGRO-AI-Webhook/1.0",
        "x-agroai-event-id": event.id,
        "x-agroai-event-version": event.version,
        "x-agroai-webhook-timestamp": timestamp,
        "x-agroai-webhook-signature": ",".join(
            f"v1={webhook_signature(secret, timestamp=timestamp, event_id=event.id, payload=body)}"
            for secret in signing_secrets
        ),
    }
    response_status = None
    excerpt = None
    error = None
    try:
        response_status, excerpt = _post_pinned(endpoint.url, body=body, headers=headers, client=client)
        succeeded = 200 <= response_status < 300
        if not succeeded:
            error = f"http_{response_status}"
    except Exception as exc:
        succeeded = False
        error = exc.__class__.__name__

    completed = datetime.utcnow()
    attempt = db.get(PlatformWebhookDeliveryAttempt, attempt.id)
    outbox = db.get(PlatformWebhookOutbox, outbox.id)
    attempt.response_status = response_status
    attempt.response_excerpt = excerpt
    attempt.error_classification = error
    attempt.completed_at = completed
    if succeeded:
        attempt.status = "succeeded"
        outbox.status = "delivered"
        outbox.completed_at = completed
        outbox.next_attempt_at = None
        outbox.last_error = None
        db.commit()
        return "succeeded"

    attempt.status = "failed"
    max_attempts = max(1, min(int(getattr(settings, "PLATFORM_API_WEBHOOK_MAX_ATTEMPTS", 6)), 12))
    if attempt_number >= max_attempts:
        outbox.status = "failed"
        outbox.completed_at = completed
        outbox.next_attempt_at = None
        outbox.last_error = error
        db.commit()
        return "failed"
    delay = min(3600, 2 ** min(attempt_number, 11))
    outbox.status = "retrying"
    outbox.next_attempt_at = completed + timedelta(seconds=delay)
    outbox.last_error = error
    attempt.next_retry_at = outbox.next_attempt_at
    db.commit()
    return "retrying"


def process_webhook_delivery_task(
    *,
    outbox_id: str,
    organization_id: str,
    worker_id: str,
) -> str:
    db = SessionLocal()
    try:
        return process_webhook_delivery(
            db,
            outbox_id=outbox_id,
            organization_id=organization_id,
            worker_id=worker_id,
        )
    finally:
        db.close()
