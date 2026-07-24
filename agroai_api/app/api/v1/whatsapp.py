"""Official WhatsApp Cloud API ingress and administration."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.api.v1.field_intelligence import enforce_field_intelligence_release
from app.core.config import settings
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection
from app.models.saas import OrganizationMembership, User, Workspace
from app.models.whatsapp import WhatsAppContactBinding, WhatsAppInboundEvent
from app.services import field_intelligence as field_svc
from app.services.connector_vault import (
    credential_reference,
    revoke_connector_credentials,
    store_connector_credentials,
)
from app.services.whatsapp_cloud import probe_phone_number, verify_challenge_token, verify_webhook_signature
from app.services.whatsapp_crypto import encrypt_wa_id, masked_wa_id, normalize_wa_id, wa_id_hash
from app.services.whatsapp_field_intelligence import (
    channel_summary,
    ingest_webhook_payload,
    queue_outbound_template,
    queue_outbound_text,
    serialize_binding,
    serialize_event,
)

public_router = APIRouter(prefix="/whatsapp", tags=["whatsapp-webhook"])
management_router = APIRouter(
    prefix="/field-intelligence/whatsapp",
    tags=["field-intelligence-whatsapp"],
    dependencies=[Depends(enforce_field_intelligence_release)],
)

_PHONE_ID = re.compile(r"^[0-9]{5,40}$")


def _require_owner_admin(ctx: AuthContext) -> None:
    role = str(getattr(ctx.membership, "role", "") or "")
    if role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "owner_or_admin_required", "message": "Organization owner or administrator access is required."},
        )


def _org_id(ctx: AuthContext) -> str:
    return field_svc.require_org(ctx)


def _connection(db: Session, ctx: AuthContext, connection_id: str) -> ConnectorConnection:
    row = db.query(ConnectorConnection).filter(
        ConnectorConnection.id == connection_id,
        ConnectorConnection.tenant_id == _org_id(ctx),
        ConnectorConnection.provider == "whatsapp",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="WhatsApp connection not found")
    return row


class ConnectRequest(BaseModel):
    workspace_id: str | None = None
    display_name: str = Field(default="WhatsApp Field Intelligence", min_length=2, max_length=160)
    phone_number_id: str = Field(min_length=5, max_length=40)
    waba_id: str = Field(min_length=5, max_length=80)
    access_token: str = Field(min_length=20, max_length=4096)
    confirmation_mode: Literal["receipt", "silent"] = "receipt"
    activate: bool = True

    @field_validator("phone_number_id")
    @classmethod
    def valid_phone_id(cls, value: str) -> str:
        if not _PHONE_ID.fullmatch(value.strip()):
            raise ValueError("phone_number_id must contain digits only")
        return value.strip()


class ChannelPatchRequest(BaseModel):
    workspace_id: str | None = None
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    confirmation_mode: Literal["receipt", "silent"] | None = None
    status: Literal["active", "configured", "disabled"] | None = None


class ContactBindRequest(BaseModel):
    connection_id: str
    wa_id: str = Field(min_length=7, max_length=40)
    user_id: str
    workspace_id: str | None = None
    role: Literal["operator", "manager", "advisor"] = "operator"
    locale: str = Field(default="en", min_length=2, max_length=20)
    consent_confirmed: bool = False
    context: dict = Field(default_factory=dict)

    @field_validator("context")
    @classmethod
    def bounded_context(cls, value: dict) -> dict:
        allowed = {"field_id", "field_name", "block_id", "block_name", "crop"}
        cleaned = {str(k): str(v)[:200] for k, v in value.items() if k in allowed and v is not None}
        if len(json.dumps(cleaned)) > 2000:
            raise ValueError("context is too large")
        return cleaned


class OutboundRequest(BaseModel):
    contact_binding_id: str
    body: str | None = Field(default=None, min_length=1, max_length=4096)
    template_name: str | None = Field(default=None, min_length=1, max_length=200)
    language_code: str = Field(default="en_US", min_length=2, max_length=20)
    parameters: list[str] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(min_length=8, max_length=180)


@public_router.get("/webhook")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    if hub_mode != "subscribe" or not verify_challenge_token(hub_verify_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")
    return Response(content=str(hub_challenge or ""), media_type="text/plain")


@public_router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
) -> dict:
    if not bool(getattr(settings, "WHATSAPP_ENABLED", False)):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="WhatsApp channel is disabled")
    declared = request.headers.get("content-length", "")
    max_bytes = int(getattr(settings, "WHATSAPP_WEBHOOK_MAX_BYTES", 2 * 1024 * 1024))
    if declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook body too large")
    raw = await request.body()
    if len(raw) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook body too large")
    if not verify_webhook_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported webhook object")
    result = ingest_webhook_payload(db, payload)
    return {"status": "received", **result}


@management_router.get("/status")
def get_status(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    field_svc.require_capability(db, ctx, "field_intelligence.capture")
    return {"status": "ok", **channel_summary(db, _org_id(ctx))}


@management_router.post("/connect")
def connect_channel(
    payload: ConnectRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _require_owner_admin(ctx)
    field_svc.require_capability(db, ctx, "field_intelligence.capture")
    tenant_id = _org_id(ctx)
    workspace_id = payload.workspace_id
    if workspace_id:
        workspace = db.get(Workspace, workspace_id)
        if workspace is None or workspace.organization_id != tenant_id:
            raise HTTPException(status_code=404, detail="Workspace not found")

    rows = db.query(ConnectorConnection).filter(
        ConnectorConnection.tenant_id == tenant_id,
        ConnectorConnection.provider == "whatsapp",
    ).all()
    connection = next(
        (
            item for item in rows
            if str((item.config_json or {}).get("phone_number_id") or "") == payload.phone_number_id
        ),
        None,
    )
    if connection is None:
        connection = ConnectorConnection(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            provider="whatsapp",
            display_name=payload.display_name,
            status="configured",
            mode="cloud_api",
            required_plan="professional",
            config_json={},
        )
        db.add(connection)
        db.flush()

    connection.workspace_id = workspace_id
    connection.display_name = payload.display_name
    connection.mode = "cloud_api"
    connection.config_json = {
        **dict(connection.config_json or {}),
        "phone_number_id": payload.phone_number_id,
        "waba_id": payload.waba_id,
        "confirmation_mode": payload.confirmation_mode,
        "webhook_path": "/v1/whatsapp/webhook",
        "transport": "official_cloud_api",
    }
    credential = store_connector_credentials(
        db,
        tenant_id=tenant_id,
        connection=connection,
        provider="whatsapp",
        payload={"access_token": payload.access_token},
        scopes=["whatsapp_business_messaging", "whatsapp_business_management"],
    )
    connection.credentials_ref = credential_reference(credential)
    connection.status = "configured"
    connection.last_error = None
    db.commit()

    identity = None
    if payload.activate:
        try:
            identity = probe_phone_number(db, connection)
            connection.status = "active"
            connection.last_test_at = datetime.utcnow()
            connection.last_error = None
        except Exception as exc:
            connection.status = "error"
            connection.last_test_at = datetime.utcnow()
            connection.last_error = f"{exc.__class__.__name__}: {str(exc)}"[:500]
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "whatsapp_connection_test_failed",
                    "message": "The credential was encrypted and saved, but Meta did not validate the phone-number connection.",
                    "connection_id": connection.id,
                },
            ) from exc
        db.commit()
    return {
        "status": "connected" if connection.status == "active" else "configured",
        "connection_id": connection.id,
        "identity": identity,
    }


@management_router.patch("/connections/{connection_id}")
def patch_channel(
    connection_id: str,
    payload: ChannelPatchRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _require_owner_admin(ctx)
    row = _connection(db, ctx, connection_id)
    changes = payload.model_dump(exclude_none=True)
    if "workspace_id" in changes and changes["workspace_id"]:
        workspace = db.get(Workspace, changes["workspace_id"])
        if workspace is None or workspace.organization_id != row.tenant_id:
            raise HTTPException(status_code=404, detail="Workspace not found")
        row.workspace_id = changes.pop("workspace_id")
    if "display_name" in changes:
        row.display_name = changes.pop("display_name")
    if "status" in changes:
        row.status = changes.pop("status")
    config = dict(row.config_json or {})
    if "confirmation_mode" in changes:
        config["confirmation_mode"] = changes["confirmation_mode"]
    row.config_json = config
    db.commit()
    return {"status": "updated", "connection": row.id}


@management_router.post("/connections/{connection_id}/test")
def test_channel(
    connection_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _require_owner_admin(ctx)
    row = _connection(db, ctx, connection_id)
    try:
        identity = probe_phone_number(db, row)
        row.status = "active"
        row.last_error = None
    except Exception as exc:
        row.status = "error"
        row.last_error = f"{exc.__class__.__name__}: {str(exc)}"[:500]
        identity = None
    row.last_test_at = datetime.utcnow()
    db.commit()
    if identity is None:
        raise HTTPException(status_code=502, detail="Meta connection test failed")
    return {"status": "ok", "identity": identity}


@management_router.delete("/connections/{connection_id}")
def disconnect_channel(
    connection_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _require_owner_admin(ctx)
    row = _connection(db, ctx, connection_id)
    revoke_connector_credentials(db, tenant_id=row.tenant_id, connection_id=row.id)
    row.status = "disabled"
    row.credentials_ref = None
    db.commit()
    return {"status": "disconnected", "connection_id": row.id}


@management_router.get("/contacts")
def list_contacts(
    connection_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    tenant_id = _org_id(ctx)
    query = db.query(WhatsAppContactBinding).filter(WhatsAppContactBinding.tenant_id == tenant_id)
    if connection_id:
        _connection(db, ctx, connection_id)
        query = query.filter(WhatsAppContactBinding.connector_connection_id == connection_id)
    total = query.count()
    rows = query.order_by(WhatsAppContactBinding.updated_at.desc()).offset(offset).limit(limit).all()
    return {"status": "ok", "contacts": [serialize_binding(row) for row in rows], "total": total}


@management_router.post("/contacts")
def bind_contact(
    payload: ContactBindRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _require_owner_admin(ctx)
    connection = _connection(db, ctx, payload.connection_id)
    tenant_id = connection.tenant_id
    user = db.get(User, payload.user_id)
    membership = db.query(OrganizationMembership).filter(
        OrganizationMembership.organization_id == tenant_id,
        OrganizationMembership.user_id == payload.user_id,
        OrganizationMembership.status == "active",
    ).first()
    if user is None or membership is None:
        raise HTTPException(status_code=404, detail="Active organization member not found")
    workspace_id = payload.workspace_id or connection.workspace_id
    if workspace_id:
        workspace = db.get(Workspace, workspace_id)
        if workspace is None or workspace.organization_id != tenant_id:
            raise HTTPException(status_code=404, detail="Workspace not found")

    normalized = normalize_wa_id(payload.wa_id)
    digest = wa_id_hash(normalized)
    row = db.query(WhatsAppContactBinding).filter(
        WhatsAppContactBinding.tenant_id == tenant_id,
        WhatsAppContactBinding.connector_connection_id == connection.id,
        WhatsAppContactBinding.wa_id_hash == digest,
    ).first()
    if row is None:
        binding_id = str(uuid.uuid4())
        ciphertext, nonce, version = encrypt_wa_id(
            normalized, tenant_id=tenant_id, binding_id=binding_id
        )
        row = WhatsAppContactBinding(
            id=binding_id,
            tenant_id=tenant_id,
            connector_connection_id=connection.id,
            wa_id_hash=digest,
            wa_id_ciphertext_b64=ciphertext,
            wa_id_nonce_b64=nonce,
            wa_id_key_version=version,
            masked_wa_id=masked_wa_id(normalized),
        )
        db.add(row)
    row.user_id = user.id
    row.workspace_id = workspace_id
    row.role = payload.role
    row.locale = payload.locale
    row.context_json = payload.context
    row.status = "active" if payload.consent_confirmed else "invited"
    row.consent_status = "granted" if payload.consent_confirmed else "pending"
    row.consent_granted_at = datetime.utcnow() if payload.consent_confirmed else None
    row.consent_revoked_at = None
    db.commit()
    db.refresh(row)
    return {"status": "bound", "contact": serialize_binding(row)}


@management_router.delete("/contacts/{binding_id}")
def revoke_contact(
    binding_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _require_owner_admin(ctx)
    row = db.query(WhatsAppContactBinding).filter(
        WhatsAppContactBinding.id == binding_id,
        WhatsAppContactBinding.tenant_id == _org_id(ctx),
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="WhatsApp contact not found")
    row.status = "disabled"
    row.consent_status = "revoked"
    row.consent_revoked_at = datetime.utcnow()
    db.commit()
    return {"status": "revoked", "contact_binding_id": row.id}


@management_router.get("/events")
def list_events(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(WhatsAppInboundEvent).filter(
        WhatsAppInboundEvent.tenant_id == _org_id(ctx)
    )
    if status_filter:
        query = query.filter(WhatsAppInboundEvent.status == status_filter)
    total = query.count()
    rows = query.order_by(WhatsAppInboundEvent.created_at.desc()).offset(offset).limit(limit).all()
    return {"status": "ok", "events": [serialize_event(row) for row in rows], "total": total}


@management_router.post("/outbound")
def create_outbound(
    payload: OutboundRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    role = str(getattr(ctx.membership, "role", "") or "")
    if role not in {"owner", "admin", "manager", "operator"}:
        raise HTTPException(status_code=403, detail="Your role cannot send WhatsApp messages")
    binding = db.query(WhatsAppContactBinding).filter(
        WhatsAppContactBinding.id == payload.contact_binding_id,
        WhatsAppContactBinding.tenant_id == _org_id(ctx),
    ).first()
    if binding is None:
        raise HTTPException(status_code=404, detail="WhatsApp contact not found")
    if payload.template_name:
        row = queue_outbound_template(
            db,
            binding,
            template_name=payload.template_name,
            language_code=payload.language_code,
            parameters=payload.parameters,
            idempotency_key=payload.idempotency_key,
        )
    elif payload.body:
        row = queue_outbound_text(
            db, binding, payload.body, idempotency_key=payload.idempotency_key
        )
    else:
        raise HTTPException(status_code=422, detail="body or template_name is required")
    db.commit()
    return {"status": "queued", "outbound_message_id": row.id}
