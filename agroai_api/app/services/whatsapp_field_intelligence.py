"""Durable WhatsApp-to-Field-Intelligence orchestration."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_approved_organization
from app.core.config import settings
from app.models.operational_records import ConnectorConnection
from app.models.saas import OrganizationMembership, User, Workspace
from app.models.whatsapp import (
    WhatsAppContactBinding,
    WhatsAppInboundEvent,
    WhatsAppOutboundMessage,
)
from app.services import field_intelligence as field_svc
from app.services.media_inspection import (
    inspect_media_file,
    validate_media_for_kind,
    verify_capped_media_duration,
)
from app.services.whatsapp_cloud import (
    WhatsAppCloudError,
    retrieve_media_to_temp,
    send_template,
    send_text,
)
from app.services.whatsapp_crypto import (
    decrypt_wa_id,
    encrypt_wa_id,
    masked_wa_id,
    normalize_wa_id,
    wa_id_hash,
)

logger = logging.getLogger(__name__)

_MESSAGE_TYPES = {"text", "audio", "image", "video", "document", "location", "sticker", "button", "interactive"}
_MEDIA_TYPES = {"audio", "image", "video", "document", "sticker"}
_EVENT_LEASE_SECONDS = 120
_OUTBOUND_LEASE_SECONDS = 120
_CONTEXT_TOKEN = re.compile(r"(?P<key>field|field_id|block|block_id|crop)=(?P<value>[^,;]+)", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def webhook_url() -> str:
    return str(getattr(settings, "API_URL", "") or "").rstrip("/") + "/v1/whatsapp/webhook"


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_text(value: Any, limit: int = 8000) -> str | None:
    text = _CONTROL.sub(" ", str(value or "")).strip()
    return text[:limit] or None


def _parse_timestamp(value: Any) -> datetime:
    try:
        return datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.utcnow()


def _find_connection(db: Session, phone_number_id: str) -> ConnectorConnection | None:
    candidates = (
        db.query(ConnectorConnection)
        .filter(ConnectorConnection.provider == "whatsapp")
        .filter(ConnectorConnection.status.in_(["active", "connected", "configured"]))
        .all()
    )
    for connection in candidates:
        if str((connection.config_json or {}).get("phone_number_id") or "") == str(phone_number_id or ""):
            return connection
    return None


def _find_or_create_binding(
    db: Session,
    connection: ConnectorConnection,
    sender_wa_id: str,
) -> WhatsAppContactBinding:
    normalized = normalize_wa_id(sender_wa_id)
    digest = wa_id_hash(normalized)
    existing = (
        db.query(WhatsAppContactBinding)
        .filter(WhatsAppContactBinding.tenant_id == connection.tenant_id)
        .filter(WhatsAppContactBinding.connector_connection_id == connection.id)
        .filter(WhatsAppContactBinding.wa_id_hash == digest)
        .first()
    )
    if existing:
        return existing

    binding_id = str(uuid.uuid4())
    ciphertext, nonce, version = encrypt_wa_id(
        normalized, tenant_id=connection.tenant_id, binding_id=binding_id
    )
    row = WhatsAppContactBinding(
        id=binding_id,
        tenant_id=connection.tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        wa_id_hash=digest,
        wa_id_ciphertext_b64=ciphertext,
        wa_id_nonce_b64=nonce,
        wa_id_key_version=version,
        masked_wa_id=masked_wa_id(normalized),
        status="pending",
        consent_status="unknown",
        context_json={},
        last_inbound_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _message_text(message: dict) -> str | None:
    message_type = str(message.get("type") or "")
    if message_type == "text":
        return _safe_text((message.get("text") or {}).get("body"))
    if message_type in {"image", "video", "document"}:
        return _safe_text((message.get(message_type) or {}).get("caption"))
    if message_type == "button":
        return _safe_text((message.get("button") or {}).get("text"))
    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        for key in ("button_reply", "list_reply"):
            value = interactive.get(key) or {}
            if value.get("title") or value.get("id"):
                return _safe_text(value.get("title") or value.get("id"))
    return None


def _media_fields(message: dict) -> tuple[str | None, str | None, str | None]:
    message_type = str(message.get("type") or "")
    if message_type not in _MEDIA_TYPES:
        return None, None, None
    media = message.get(message_type) or {}
    return (
        _safe_text(media.get("id"), 240),
        _safe_text(media.get("mime_type"), 200),
        _safe_text(media.get("filename"), 240),
    )


def _redacted_message_payload(message: dict, phone_number_id: str) -> dict:
    message_type = str(message.get("type") or "unknown")
    context = message.get("context") or {}
    return {
        "phone_number_id": str(phone_number_id or "")[:120],
        "message_id": _safe_text(message.get("id"), 240),
        "message_type": message_type[:32],
        "reply_to_message_id": _safe_text(context.get("id"), 240),
        "has_text": bool(_message_text(message)),
        "has_media": message_type in _MEDIA_TYPES,
        "has_location": message_type == "location",
    }


def ingest_webhook_payload(db: Session, payload: dict) -> dict:
    """Persist a Meta webhook delivery without running external I/O.

    Exact payload deliveries are deduplicated. Raw webhook bodies, contact names,
    and sender phone identifiers are never persisted.
    """
    accepted = duplicates = unknown_connections = statuses = 0
    entries = payload.get("entry") if isinstance(payload, dict) else []
    for entry in entries or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")
            connection = _find_connection(db, phone_number_id)
            if connection is None:
                unknown_connections += 1
                continue

            for message in value.get("messages") or []:
                sender = str((message or {}).get("from") or "")
                try:
                    binding = _find_or_create_binding(db, connection, sender)
                except ValueError:
                    logger.warning("Rejected malformed WhatsApp sender identifier")
                    continue
                message_type = str((message or {}).get("type") or "unknown")[:32]
                media_id, media_mime, media_filename = _media_fields(message or {})
                location = (message or {}).get("location") or {}
                minimal = _redacted_message_payload(message or {}, phone_number_id)
                payload_hash = _canonical_hash({
                    "connection": connection.id,
                    "event": "message",
                    "message_id": minimal.get("message_id"),
                    "type": message_type,
                })
                exists = (
                    db.query(WhatsAppInboundEvent)
                    .filter(WhatsAppInboundEvent.connector_connection_id == connection.id)
                    .filter(WhatsAppInboundEvent.payload_hash == payload_hash)
                    .first()
                )
                if exists:
                    duplicates += 1
                    continue
                supported = message_type in _MESSAGE_TYPES
                row = WhatsAppInboundEvent(
                    id=str(uuid.uuid4()),
                    tenant_id=connection.tenant_id,
                    workspace_id=binding.workspace_id or connection.workspace_id,
                    connector_connection_id=connection.id,
                    contact_binding_id=binding.id,
                    meta_message_id=_safe_text((message or {}).get("id"), 240),
                    payload_hash=payload_hash,
                    event_type="message",
                    message_type=message_type,
                    text_content=_message_text(message or {}),
                    media_id=media_id,
                    media_mime_type=media_mime,
                    media_filename=media_filename,
                    latitude=_float_or_none(location.get("latitude")),
                    longitude=_float_or_none(location.get("longitude")),
                    occurred_at=_parse_timestamp((message or {}).get("timestamp")),
                    status="queued" if supported else "ignored",
                    max_attempts=int(getattr(settings, "WHATSAPP_MAX_ATTEMPTS", 5)),
                    next_attempt_at=datetime.utcnow(),
                    redacted_payload_json=minimal,
                    completed_at=None if supported else datetime.utcnow(),
                )
                db.add(row)
                binding.last_inbound_at = datetime.utcnow()
                accepted += 1

            for delivery in value.get("statuses") or []:
                message_id = _safe_text((delivery or {}).get("id"), 240)
                delivery_status = _safe_text((delivery or {}).get("status"), 32)
                minimal = {
                    "phone_number_id": phone_number_id[:120],
                    "message_id": message_id,
                    "delivery_status": delivery_status,
                }
                payload_hash = _canonical_hash({
                    "connection": connection.id,
                    "event": "status",
                    **minimal,
                    "timestamp": (delivery or {}).get("timestamp"),
                })
                if not db.query(WhatsAppInboundEvent).filter(
                    WhatsAppInboundEvent.connector_connection_id == connection.id,
                    WhatsAppInboundEvent.payload_hash == payload_hash,
                ).first():
                    db.add(WhatsAppInboundEvent(
                        id=str(uuid.uuid4()),
                        tenant_id=connection.tenant_id,
                        workspace_id=connection.workspace_id,
                        connector_connection_id=connection.id,
                        meta_message_id=message_id,
                        payload_hash=payload_hash,
                        event_type="status",
                        delivery_status=delivery_status,
                        status="completed",
                        occurred_at=_parse_timestamp((delivery or {}).get("timestamp")),
                        redacted_payload_json=minimal,
                        completed_at=datetime.utcnow(),
                    ))
                    statuses += 1
                _apply_delivery_status(db, connection.id, message_id, delivery_status)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicates += 1
    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "status_updates": statuses,
        "unknown_connections": unknown_connections,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_STATUS_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}


def _apply_delivery_status(
    db: Session,
    connection_id: str,
    meta_message_id: str | None,
    delivery_status: str | None,
) -> None:
    if not meta_message_id or not delivery_status:
        return
    row = db.query(WhatsAppOutboundMessage).filter(
        WhatsAppOutboundMessage.connector_connection_id == connection_id,
        WhatsAppOutboundMessage.meta_message_id == meta_message_id,
    ).first()
    if row is None:
        return
    if delivery_status == "failed":
        row.status = "failed"
        row.last_error = "Meta reported delivery failure"
        return
    if _STATUS_RANK.get(delivery_status, -1) >= _STATUS_RANK.get(row.status, -1):
        row.status = delivery_status


def _auth_context_for_binding(
    db: Session,
    binding: WhatsAppContactBinding,
) -> AuthContext:
    user = db.get(User, binding.user_id) if binding.user_id else None
    if (
        user is None
        or not user.is_active
        or getattr(user, "account_status", "active") != "active"
        or getattr(user, "email_verification_status", "") != "verified"
        or not getattr(user, "email_verified_at", None)
    ):
        raise PermissionError("bound portal user is unavailable")
    membership = db.query(OrganizationMembership).filter(
        OrganizationMembership.organization_id == binding.tenant_id,
        OrganizationMembership.user_id == user.id,
        OrganizationMembership.status == "active",
    ).first()
    if membership is None:
        raise PermissionError("active organization membership is required")
    require_approved_organization(membership.organization)
    if binding.workspace_id:
        workspace = db.get(Workspace, binding.workspace_id)
        if workspace is None or workspace.organization_id != binding.tenant_id:
            raise PermissionError("bound workspace is unavailable")
    return AuthContext(user=user, organization=membership.organization, membership=membership)


def _parse_context_command(text: str) -> dict:
    updates: dict[str, str] = {}
    for match in _CONTEXT_TOKEN.finditer(text):
        key = match.group("key").lower()
        value = _safe_text(match.group("value"), 200)
        if not value:
            continue
        canonical = {
            "field": "field_name",
            "field_id": "field_id",
            "block": "block_name",
            "block_id": "block_id",
            "crop": "crop",
        }[key]
        updates[canonical] = value
    return updates


def queue_outbound_text(
    db: Session,
    binding: WhatsAppContactBinding,
    body: str,
    *,
    idempotency_key: str,
) -> WhatsAppOutboundMessage:
    existing = db.query(WhatsAppOutboundMessage).filter(
        WhatsAppOutboundMessage.tenant_id == binding.tenant_id,
        WhatsAppOutboundMessage.idempotency_key == idempotency_key,
    ).first()
    if existing:
        return existing
    row = WhatsAppOutboundMessage(
        id=str(uuid.uuid4()),
        tenant_id=binding.tenant_id,
        workspace_id=binding.workspace_id,
        connector_connection_id=binding.connector_connection_id,
        contact_binding_id=binding.id,
        idempotency_key=idempotency_key[:180],
        message_kind="text",
        body_text=_safe_text(body, 4096),
        status="queued",
        max_attempts=int(getattr(settings, "WHATSAPP_MAX_ATTEMPTS", 5)),
        next_attempt_at=datetime.utcnow(),
    )
    db.add(row)
    return row


def queue_outbound_template(
    db: Session,
    binding: WhatsAppContactBinding,
    *,
    template_name: str,
    language_code: str,
    parameters: list[str] | None,
    idempotency_key: str,
) -> WhatsAppOutboundMessage:
    existing = db.query(WhatsAppOutboundMessage).filter(
        WhatsAppOutboundMessage.tenant_id == binding.tenant_id,
        WhatsAppOutboundMessage.idempotency_key == idempotency_key,
    ).first()
    if existing:
        return existing
    row = WhatsAppOutboundMessage(
        id=str(uuid.uuid4()),
        tenant_id=binding.tenant_id,
        workspace_id=binding.workspace_id,
        connector_connection_id=binding.connector_connection_id,
        contact_binding_id=binding.id,
        idempotency_key=idempotency_key[:180],
        message_kind="template",
        template_name=_safe_text(template_name, 200),
        language_code=_safe_text(language_code, 20) or "en_US",
        parameters_json=[_safe_text(value, 1024) or "" for value in (parameters or [])[:20]],
        status="queued",
        max_attempts=int(getattr(settings, "WHATSAPP_MAX_ATTEMPTS", 5)),
        next_attempt_at=datetime.utcnow(),
    )
    db.add(row)
    return row


def _process_command(
    db: Session,
    event: WhatsAppInboundEvent,
    binding: WhatsAppContactBinding,
    text: str,
) -> bool:
    command = text.strip()
    upper = command.upper()
    if upper in {"STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}:
        binding.consent_status = "revoked"
        binding.consent_revoked_at = datetime.utcnow()
        binding.status = "disabled"
        queue_outbound_text(
            db, binding,
            "WhatsApp capture is disabled for this number. Send START after your administrator re-enables access.",
            idempotency_key=f"wa-stop-{event.id}",
        )
        return True
    if upper in {"START", "AGREE", "CONSENT"}:
        if binding.user_id and binding.status in {"invited", "active", "disabled"}:
            binding.consent_status = "granted"
            binding.consent_granted_at = datetime.utcnow()
            binding.consent_revoked_at = None
            binding.status = "active"
            body = "AGRO-AI Field Intelligence is active for this number. Send a voice note, photo, location, or field update."
        else:
            body = "This number is awaiting authorization by your AGRO-AI workspace administrator."
        queue_outbound_text(db, binding, body, idempotency_key=f"wa-start-{event.id}")
        return True
    if upper in {"HELP", "/HELP"}:
        queue_outbound_text(
            db, binding,
            "Send a field update, voice note, photo, document, or location. Use /context field=NAME, block=NAME, crop=NAME to set context. Send STOP to disable capture.",
            idempotency_key=f"wa-help-{event.id}",
        )
        return True
    if command.lower().startswith("/context"):
        updates = _parse_context_command(command)
        if updates:
            context = dict(binding.context_json or {})
            context.update(updates)
            binding.context_json = context
            summary = ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in updates.items())
            body = f"Context updated — {summary}."
        else:
            context = dict(binding.context_json or {})
            body = "Current context: " + (
                ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in context.items())
                if context else "not set"
            )
        queue_outbound_text(db, binding, body, idempotency_key=f"wa-context-{event.id}")
        return True
    return False


def _media_kind(message_type: str) -> str:
    return {
        "audio": "audio",
        "image": "photo",
        "sticker": "photo",
        "video": "video",
        "document": "file",
    }[message_type]


def _verified_media(
    path: str,
    *,
    kind: str,
    content_type: str,
) -> float | None:
    if kind == "file":
        return None
    inspection = inspect_media_file(path)
    ok, reason = validate_media_for_kind(
        inspection,
        kind=kind,
        content_type=content_type,
        max_audio_seconds=float(settings.FIELD_AUDIO_MAX_SECONDS),
    )
    if not ok:
        raise WhatsAppCloudError(f"WhatsApp media rejected: {reason or 'unsupported'}")
    if kind not in {"audio", "video"}:
        return inspection.duration_seconds
    verified, probe_reason, duration = verify_capped_media_duration(
        path,
        inspection,
        kind=kind,
        max_seconds=float(settings.FIELD_AUDIO_MAX_SECONDS),
        ffprobe_path=str(settings.FIELD_MEDIA_FFPROBE_PATH or "ffprobe"),
        timeout_seconds=float(settings.FIELD_MEDIA_PROBE_TIMEOUT_SECONDS),
        max_output_bytes=int(settings.FIELD_MEDIA_PROBE_MAX_OUTPUT_BYTES),
        memory_limit_mb=int(settings.FIELD_MEDIA_PROBE_MEMORY_LIMIT_MB),
    )
    if not verified:
        raise WhatsAppCloudError(f"WhatsApp media duration could not be verified: {probe_reason}")
    return duration


def _process_message(db: Session, event: WhatsAppInboundEvent) -> None:
    binding = db.get(WhatsAppContactBinding, event.contact_binding_id)
    if binding is None:
        event.status = "quarantined"
        event.last_error = "contact binding unavailable"
        return

    text = event.text_content or ""
    if text and _process_command(db, event, binding, text):
        event.status = "completed"
        event.completed_at = datetime.utcnow()
        return

    if binding.status != "active" or binding.consent_status != "granted" or not binding.user_id:
        event.status = "quarantined"
        event.last_error = "contact is not authorized and consented"
        return

    ctx = _auth_context_for_binding(db, binding)
    connection = db.get(ConnectorConnection, event.connector_connection_id)
    if connection is None or connection.status not in {"active", "connected", "configured"}:
        raise WhatsAppCloudError("WhatsApp channel is unavailable")

    context = dict(binding.context_json or {})
    manifest: list[dict] = []
    spool_path: str | None = None
    asset_kind: str | None = None
    content_type: str | None = None
    digest: str | None = None
    total = 0
    duration: float | None = None
    filename: str | None = None

    try:
        if event.message_type in _MEDIA_TYPES:
            if not event.media_id:
                raise WhatsAppCloudError("WhatsApp media id is missing")
            spool_path, content_type, digest, total = retrieve_media_to_temp(
                db, connection, event.media_id
            )
            asset_kind = _media_kind(str(event.message_type))
            duration = _verified_media(spool_path, kind=asset_kind, content_type=content_type)
            filename = _safe_text(event.media_filename, 200) or f"whatsapp-{event.id[:8]}"
            manifest = [{
                "client_asset_id": f"wa-asset-{event.meta_message_id or event.id}"[:200],
                "kind": asset_kind,
                "content_type": content_type,
            }]

        note = text or (
            "Location shared from WhatsApp."
            if event.message_type == "location"
            else "Field media received through WhatsApp."
        )
        capture_payload = {
            "client_capture_id": f"wa-{event.connector_connection_id}-{event.meta_message_id or event.id}"[:200],
            "idempotency_key": f"wa:{event.connector_connection_id}:{event.meta_message_id or event.id}"[:120],
            "workspace_id": binding.workspace_id,
            "capture_source": "voice" if event.message_type in {"audio", "video"} else "typed",
            "note_text": note,
            "field_id": context.get("field_id"),
            "field_name": context.get("field_name"),
            "block_id": context.get("block_id"),
            "block_name": context.get("block_name"),
            "crop": context.get("crop"),
            "latitude": event.latitude,
            "longitude": event.longitude,
            "asset_manifest": manifest,
            "occurred_at": event.occurred_at,
            "metadata": {
                "surface": "whatsapp",
                "connector_connection_id": event.connector_connection_id,
                "whatsapp_event_id": event.id,
                "whatsapp_message_id": event.meta_message_id,
                "contact_binding_id": binding.id,
            },
        }
        capture = field_svc.initiate_capture(db, ctx, capture_payload)
        if spool_path and asset_kind and digest and content_type:
            field_svc.register_asset(
                db,
                ctx,
                capture.id,
                client_asset_id=manifest[0]["client_asset_id"],
                kind=asset_kind,
                content_type=content_type,
                filename=filename,
                content_sha256=digest,
                size_bytes=total,
                duration_seconds=duration,
                spool_path=spool_path,
            )
        observation = field_svc.complete_capture(
            db, ctx, capture.id, {"language": binding.locale or "en"}
        )
        event.capture_session_id = capture.id
        event.observation_id = observation.id
        event.workspace_id = capture.workspace_id
        event.status = "completed"
        event.completed_at = datetime.utcnow()
        if str((connection.config_json or {}).get("confirmation_mode") or "receipt") != "silent":
            queue_outbound_text(
                db,
                binding,
                "Captured in AGRO-AI Field Intelligence. The record is processing and will remain available in the Enterprise Portal.",
                idempotency_key=f"wa-receipt-{event.id}",
            )
    finally:
        if spool_path:
            Path(spool_path).unlink(missing_ok=True)


def _claim_inbound(db: Session, event_id: str, worker_id: str) -> WhatsAppInboundEvent | None:
    now = datetime.utcnow()
    updated = db.query(WhatsAppInboundEvent).filter(
        WhatsAppInboundEvent.id == event_id,
        WhatsAppInboundEvent.status.in_(["queued", "processing"]),
        (WhatsAppInboundEvent.lease_expires_at.is_(None)) | (WhatsAppInboundEvent.lease_expires_at <= now),
    ).update({
        WhatsAppInboundEvent.status: "processing",
        WhatsAppInboundEvent.worker_id: worker_id,
        WhatsAppInboundEvent.lease_expires_at: now + timedelta(seconds=_EVENT_LEASE_SECONDS),
        WhatsAppInboundEvent.attempt_count: WhatsAppInboundEvent.attempt_count + 1,
    }, synchronize_session=False)
    db.commit()
    return db.get(WhatsAppInboundEvent, event_id) if updated == 1 else None


def _retry_inbound(db: Session, event_id: str, exc: Exception) -> None:
    event = db.get(WhatsAppInboundEvent, event_id)
    if event is None:
        return
    terminal = int(event.attempt_count or 0) >= int(event.max_attempts or 5)
    event.status = "failed" if terminal else "queued"
    event.last_error = f"{exc.__class__.__name__}: {str(exc)}"[:500]
    event.worker_id = None
    event.lease_expires_at = None
    event.next_attempt_at = None if terminal else datetime.utcnow() + timedelta(
        seconds=min(2 ** max(1, int(event.attempt_count or 1)) * 5, 600)
    )
    if terminal:
        event.completed_at = datetime.utcnow()
    db.commit()


def run_whatsapp_ingress_jobs(
    db: Session,
    *,
    limit: int = 25,
    worker_id: str | None = None,
) -> dict:
    if not bool(getattr(settings, "WHATSAPP_ENABLED", False)):
        return {"processed": 0, "failed": 0, "disabled": True}
    worker_id = worker_id or f"wa-worker-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()
    ids = [
        row[0] for row in db.query(WhatsAppInboundEvent.id).filter(
            WhatsAppInboundEvent.event_type == "message",
            WhatsAppInboundEvent.status.in_(["queued", "processing"]),
            (WhatsAppInboundEvent.next_attempt_at.is_(None)) | (WhatsAppInboundEvent.next_attempt_at <= now),
            (WhatsAppInboundEvent.lease_expires_at.is_(None)) | (WhatsAppInboundEvent.lease_expires_at <= now),
        ).order_by(WhatsAppInboundEvent.created_at.asc()).limit(limit).all()
    ]
    processed = failed = 0
    for event_id in ids:
        event = _claim_inbound(db, event_id, worker_id)
        if event is None:
            continue
        try:
            _process_message(db, event)
            event.worker_id = None
            event.lease_expires_at = None
            db.commit()
            processed += 1
        except Exception as exc:
            db.rollback()
            _retry_inbound(db, event_id, exc)
            failed += 1
    return {"processed": processed, "failed": failed, "worker_id": worker_id}


def _claim_outbound(db: Session, row_id: str, worker_id: str) -> WhatsAppOutboundMessage | None:
    now = datetime.utcnow()
    updated = db.query(WhatsAppOutboundMessage).filter(
        WhatsAppOutboundMessage.id == row_id,
        WhatsAppOutboundMessage.status.in_(["queued", "sending"]),
        (WhatsAppOutboundMessage.lease_expires_at.is_(None)) | (WhatsAppOutboundMessage.lease_expires_at <= now),
    ).update({
        WhatsAppOutboundMessage.status: "sending",
        WhatsAppOutboundMessage.worker_id: worker_id,
        WhatsAppOutboundMessage.lease_expires_at: now + timedelta(seconds=_OUTBOUND_LEASE_SECONDS),
        WhatsAppOutboundMessage.attempt_count: WhatsAppOutboundMessage.attempt_count + 1,
    }, synchronize_session=False)
    db.commit()
    return db.get(WhatsAppOutboundMessage, row_id) if updated == 1 else None


def _retry_outbound(db: Session, row_id: str, exc: Exception) -> None:
    row = db.get(WhatsAppOutboundMessage, row_id)
    if row is None:
        return
    terminal = int(row.attempt_count or 0) >= int(row.max_attempts or 5)
    row.status = "failed" if terminal else "queued"
    row.last_error = f"{exc.__class__.__name__}: {str(exc)}"[:500]
    row.worker_id = None
    row.lease_expires_at = None
    row.next_attempt_at = None if terminal else datetime.utcnow() + timedelta(
        seconds=min(2 ** max(1, int(row.attempt_count or 1)) * 5, 600)
    )
    db.commit()


def run_whatsapp_outbox(
    db: Session,
    *,
    limit: int = 25,
    worker_id: str | None = None,
) -> dict:
    if not bool(getattr(settings, "WHATSAPP_ENABLED", False)):
        return {"sent": 0, "failed": 0, "disabled": True}
    worker_id = worker_id or f"wa-outbox-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()
    ids = [
        row[0] for row in db.query(WhatsAppOutboundMessage.id).filter(
            WhatsAppOutboundMessage.status.in_(["queued", "sending"]),
            (WhatsAppOutboundMessage.next_attempt_at.is_(None)) | (WhatsAppOutboundMessage.next_attempt_at <= now),
            (WhatsAppOutboundMessage.lease_expires_at.is_(None)) | (WhatsAppOutboundMessage.lease_expires_at <= now),
        ).order_by(WhatsAppOutboundMessage.created_at.asc()).limit(limit).all()
    ]
    sent = failed = 0
    for row_id in ids:
        row = _claim_outbound(db, row_id, worker_id)
        if row is None:
            continue
        try:
            binding = db.get(WhatsAppContactBinding, row.contact_binding_id)
            connection = db.get(ConnectorConnection, row.connector_connection_id)
            if binding is None or connection is None:
                raise WhatsAppCloudError("WhatsApp outbound ownership is unavailable")
            if binding.consent_status != "granted":
                raise WhatsAppCloudError("WhatsApp contact has not granted consent")
            recipient = decrypt_wa_id(
                binding.wa_id_ciphertext_b64,
                binding.wa_id_nonce_b64,
                tenant_id=binding.tenant_id,
                binding_id=binding.id,
                key_version=binding.wa_id_key_version,
            )
            if row.message_kind == "template":
                message_id = send_template(
                    db, connection, to=recipient,
                    name=str(row.template_name or ""),
                    language_code=str(row.language_code or "en_US"),
                    parameters=list(row.parameters_json or []),
                )
            else:
                window_hours = int(getattr(settings, "WHATSAPP_SERVICE_WINDOW_HOURS", 24))
                if not binding.last_inbound_at or binding.last_inbound_at < datetime.utcnow() - timedelta(hours=window_hours):
                    raise WhatsAppCloudError("A template is required outside the customer service window")
                message_id = send_text(db, connection, to=recipient, body=str(row.body_text or ""))
            row.meta_message_id = message_id
            row.status = "sent"
            row.sent_at = datetime.utcnow()
            row.last_error = None
            row.worker_id = None
            row.lease_expires_at = None
            binding.last_outbound_at = datetime.utcnow()
            db.commit()
            sent += 1
        except Exception as exc:
            db.rollback()
            _retry_outbound(db, row_id, exc)
            failed += 1
    return {"sent": sent, "failed": failed, "worker_id": worker_id}


def channel_summary(db: Session, tenant_id: str) -> dict:
    connections = db.query(ConnectorConnection).filter(
        ConnectorConnection.tenant_id == tenant_id,
        ConnectorConnection.provider == "whatsapp",
    ).order_by(ConnectorConnection.created_at.desc()).all()
    return {
        "enabled": bool(getattr(settings, "WHATSAPP_ENABLED", False)),
        "webhook_url": webhook_url(),
        "signature_verification_configured": bool(getattr(settings, "WHATSAPP_APP_SECRET", "")),
        "challenge_verification_configured": bool(getattr(settings, "WHATSAPP_VERIFY_TOKEN", "")),
        "graph_api_version_configured": bool(getattr(settings, "WHATSAPP_GRAPH_API_VERSION", "")),
        "connections": [{
            "id": row.id,
            "workspace_id": row.workspace_id,
            "display_name": row.display_name,
            "status": row.status,
            "phone_number_id": str((row.config_json or {}).get("phone_number_id") or ""),
            "waba_id": str((row.config_json or {}).get("waba_id") or ""),
            "confirmation_mode": str((row.config_json or {}).get("confirmation_mode") or "receipt"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
            "last_error": row.last_error,
        } for row in connections],
        "contacts": db.query(WhatsAppContactBinding).filter(
            WhatsAppContactBinding.tenant_id == tenant_id
        ).count(),
        "queued_events": db.query(WhatsAppInboundEvent).filter(
            WhatsAppInboundEvent.tenant_id == tenant_id,
            WhatsAppInboundEvent.status.in_(["queued", "processing"]),
        ).count(),
        "queued_outbound": db.query(WhatsAppOutboundMessage).filter(
            WhatsAppOutboundMessage.tenant_id == tenant_id,
            WhatsAppOutboundMessage.status.in_(["queued", "sending"]),
        ).count(),
    }


def serialize_binding(row: WhatsAppContactBinding) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "connector_connection_id": row.connector_connection_id,
        "user_id": row.user_id,
        "masked_wa_id": row.masked_wa_id,
        "role": row.role,
        "locale": row.locale,
        "status": row.status,
        "consent_status": row.consent_status,
        "context": row.context_json or {},
        "last_inbound_at": row.last_inbound_at.isoformat() if row.last_inbound_at else None,
        "last_outbound_at": row.last_outbound_at.isoformat() if row.last_outbound_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_event(row: WhatsAppInboundEvent) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "connector_connection_id": row.connector_connection_id,
        "contact_binding_id": row.contact_binding_id,
        "event_type": row.event_type,
        "message_type": row.message_type,
        "delivery_status": row.delivery_status,
        "status": row.status,
        "masked_message_id": f"…{row.meta_message_id[-8:]}" if row.meta_message_id else None,
        "capture_session_id": row.capture_session_id,
        "observation_id": row.observation_id,
        "attempt_count": row.attempt_count,
        "last_error": row.last_error,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
