"""Platform API support, status, partner dossier, and abuse operations."""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform_admin
from app.core.config import settings
from app.db.base import get_db
from app.models.platform_api import ApiProject, PlatformApiKey, PlatformWebhookDeliveryAttempt, PlatformWebhookEndpoint
from app.models.operational_records import IngestionJob
from app.models.platform_product import (
    PlatformAbuseEvent,
    PlatformApiApplication,
    PlatformProgramEnrollment,
    PlatformPartnerDossier,
    PlatformProductAuditEvent,
    PlatformRequestLog,
    PlatformStatusComponent,
    PlatformStatusIncident,
    PlatformStatusIncidentUpdate,
    PlatformSupportMessage,
    PlatformSupportRequest,
)
from app.models.saas import Organization, User
from app.platform_api.deps import require_developer_control_plane
from app.platform_api.product_audit import record_product_audit
from app.platform_api.product_emails import queue_and_send_product_email
from app.services.object_storage import get_object_store, object_storage_configured

router = APIRouter(prefix="/platform", tags=["platform-operations"])

SUPPORT_CATEGORIES = frozenset({"access", "authentication", "integration", "billing", "usage", "webhook", "incident", "security", "provider", "other"})
SUPPORT_SEVERITIES = frozenset({"low", "normal", "high", "critical"})
SUPPORT_STATUSES = frozenset({"open", "triaged", "in_progress", "waiting_on_customer", "resolved", "closed"})
INCIDENT_STATUSES = frozenset({"investigating", "identified", "monitoring", "resolved"})
COMPONENTS = (
    ("platform_api", "Platform API"),
    ("authentication", "Authentication"),
    ("developer_console", "Developer Console"),
    ("webhooks", "Webhooks"),
    ("usage_processing", "Usage Processing"),
    ("billing", "Billing"),
    ("data_ingestion", "Data Ingestion"),
    ("recommendations", "Recommendations"),
    ("reports", "Reports"),
    ("provider_integrations", "Provider Integrations"),
)
SUPPORT_ATTACHMENT_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/csv",
        "text/plain",
    }
)
SUPPORT_ATTACHMENT_CONNECTION_ID = "platform-support"


def _flag(name: str) -> None:
    if not bool(getattr(settings, name, False)):
        raise HTTPException(status_code=404, detail="Not found")


class SupportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_project_id: str | None = None
    category: str
    severity: str = "normal"
    subject: str = Field(min_length=3, max_length=240)
    description: str = Field(min_length=10, max_length=8000)
    environment: str | None = Field(default=None, pattern="^(test|live)$")
    request_id: str | None = Field(default=None, max_length=128)
    key_fingerprint: str | None = Field(default=None, max_length=32)
    job_id: str | None = Field(default=None, max_length=128)
    webhook_delivery_id: str | None = Field(default=None, max_length=128)
    invoice_reference: str | None = Field(default=None, max_length=128)
    contact_email: str = Field(min_length=5, max_length=254)
    attachments: list[dict] = Field(default_factory=list, max_length=10)

    @field_validator("category")
    @classmethod
    def category_allowed(cls, value: str) -> str:
        if value not in SUPPORT_CATEGORIES:
            raise ValueError("unsupported support category")
        return value

    @field_validator("severity")
    @classmethod
    def severity_allowed(cls, value: str) -> str:
        if value not in SUPPORT_SEVERITIES:
            raise ValueError("unsupported support severity")
        return value

    @field_validator("attachments")
    @classmethod
    def safe_attachments(cls, values: list[dict]) -> list[dict]:
        allowed = {"object_id", "filename", "content_type", "sha256", "size_bytes"}
        result = []
        for item in values:
            if set(item) - allowed or not item.get("object_id") or not item.get("sha256"):
                raise ValueError("attachments must be safe object-storage references")
            if len(str(item["object_id"])) > 1000 or len(str(item.get("filename") or "")) > 240:
                raise ValueError("attachment metadata is too large")
            if str(item.get("content_type") or "") not in SUPPORT_ATTACHMENT_CONTENT_TYPES:
                raise ValueError("attachment content type is not permitted")
            if not re.fullmatch(r"[a-f0-9]{64}", str(item["sha256"])):
                raise ValueError("attachment checksum is invalid")
            if not 0 < int(item.get("size_bytes") or 0) <= int(settings.PLATFORM_API_SUPPORT_MAX_ATTACHMENT_BYTES):
                raise ValueError("attachment is too large")
            result.append({key: item[key] for key in allowed if key in item})
        return result


class SupportAttachmentInitiate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=240)
    content_type: str
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)

    @field_validator("content_type")
    @classmethod
    def safe_content_type(cls, value: str) -> str:
        if value not in SUPPORT_ATTACHMENT_CONTENT_TYPES:
            raise ValueError("attachment content type is not permitted")
        return value

    @field_validator("size_bytes")
    @classmethod
    def safe_size(cls, value: int) -> int:
        if value > int(settings.PLATFORM_API_SUPPORT_MAX_ATTACHMENT_BYTES):
            raise ValueError("attachment is too large")
        return value


class SupportReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=8000)


class SupportAdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    assigned_to_user_id: str | None = None
    internal_note: str | None = Field(default=None, max_length=8000)
    customer_response: str | None = Field(default=None, max_length=8000)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str | None) -> str | None:
        if value and value not in SUPPORT_STATUSES:
            raise ValueError("unsupported support status")
        return value


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=240)
    severity: str = Field(pattern="^(minor|major|critical)$")
    public_summary: str = Field(min_length=3, max_length=4000)
    component_keys: list[str] = Field(min_length=1, max_length=20)


class IncidentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    public_message: str = Field(min_length=3, max_length=4000)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in INCIDENT_STATUSES:
            raise ValueError("unsupported incident status")
        return value


class ComponentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(operational|degraded_performance|partial_outage|major_outage|maintenance)$")
    reason: str = Field(min_length=3, max_length=2000)


class PartnerDossierWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: str
    enrollment_id: str | None = None
    application_id: str | None = None
    partner_name: str = Field(min_length=2, max_length=240)
    provider_id: str = Field(min_length=2, max_length=120)
    commercial_owner: str | None = Field(default=None, max_length=254)
    technical_owner: str | None = Field(default=None, max_length=254)
    nda_status: str = Field(default="not_started", max_length=120)
    contract_status: str = Field(default="awaiting_partner_contract", max_length=120)
    documentation_received: bool = False
    authentication_confirmed: bool = False
    sandbox_credentials_received: bool = False
    endpoint_allowlist_approved: bool = False
    schemas_received: bool = False
    rate_limits_received: bool = False
    webhook_contract_received: bool = False
    data_retention_terms: str | None = Field(default=None, max_length=4000)
    support_contacts: list[dict] = Field(default_factory=list, max_length=30)
    milestones: list[dict] = Field(default_factory=list, max_length=100)
    read_readiness: str = Field(default="awaiting_partner_contract", max_length=120)
    write_readiness: str = Field(default="disabled", max_length=120)
    sandbox_readiness: str = Field(default="awaiting_partner_contract", max_length=120)
    production_readiness: str = Field(default="awaiting_partner_contract", max_length=120)
    blockers: list[str] = Field(default_factory=list, max_length=100)
    custom_rate_card: dict = Field(default_factory=dict)
    custom_limits: dict = Field(default_factory=dict)
    document_references: list[dict] = Field(default_factory=list, max_length=30)
    credential_vault_references: list[dict] = Field(default_factory=list, max_length=30)

    @field_validator("provider_id")
    @classmethod
    def truthful_provider(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("production_readiness", "read_readiness", "sandbox_readiness")
    @classmethod
    def protect_partner_readiness(cls, value: str, info) -> str:
        provider = (info.data.get("provider_id") or "").lower()
        if provider in {"earthdaily", "valley_irrigation", "valley"} and value != "awaiting_partner_contract":
            raise ValueError("EarthDaily and Valley must remain awaiting_partner_contract until official contracts are supplied and tested")
        return value

    @field_validator("write_readiness")
    @classmethod
    def no_physical_writes(cls, value: str) -> str:
        if value not in {"disabled", "contract_review"}:
            raise ValueError("provider write readiness cannot be activated from the dossier")
        return value

    @field_validator("document_references")
    @classmethod
    def safe_document_references(cls, values: list[dict]) -> list[dict]:
        allowed = {"object_id", "filename", "content_type", "sha256", "size_bytes", "document_type"}
        result: list[dict] = []
        for item in values:
            if set(item) - allowed or not item.get("object_id") or not item.get("sha256"):
                raise ValueError("documents must be safe source-library or object-storage references")
            result.append({key: item[key] for key in allowed if key in item})
        return result

    @field_validator("credential_vault_references")
    @classmethod
    def safe_vault_references(cls, values: list[dict]) -> list[dict]:
        allowed = {"credential_id", "provider_id", "purpose", "key_version", "status"}
        result: list[dict] = []
        for item in values:
            if set(item) - allowed or not item.get("credential_id"):
                raise ValueError("credential references must contain vault metadata only")
            result.append({key: item[key] for key in allowed if key in item})
        return result


class AbuseReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(open|monitoring|resolved|false_positive)$")
    action: str | None = Field(default=None, pattern="^(throttle|challenge|disable_key|disable_project|require_review)$")
    reason: str = Field(min_length=3, max_length=2000)


def _support_public(row: PlatformSupportRequest, *, admin: bool = False) -> dict:
    result = {
        "id": row.id,
        "api_project_id": row.api_project_id,
        "category": row.category,
        "severity": row.severity,
        "subject": row.subject,
        "description": row.description,
        "environment": row.environment,
        "request_id": row.request_id_reference,
        "key_fingerprint": row.key_fingerprint,
        "job_id": row.job_id,
        "webhook_delivery_id": row.webhook_delivery_id,
        "invoice_reference": row.invoice_reference,
        "contact_email": row.contact_email,
        "attachments": row.attachment_references_json or [],
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
    if admin:
        result["organization_id"] = row.organization_id
        result["assigned_to_user_id"] = row.assigned_to_user_id
    return result


def _verify_support_attachments(organization_id: str, attachments: list[dict]) -> list[dict]:
    if not attachments:
        return []
    if not object_storage_configured():
        raise HTTPException(status_code=503, detail={"code": "support_attachment_storage_not_configured"})
    store = get_object_store()
    verified: list[dict] = []
    for item in attachments:
        try:
            stored = store.inspect(
                item["object_id"],
                tenant_id=organization_id,
                connection_id=SUPPORT_ATTACHMENT_CONNECTION_ID,
                max_bytes=int(settings.PLATFORM_API_SUPPORT_MAX_ATTACHMENT_BYTES),
                expected_sha256=item["sha256"],
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail={"code": "support_attachment_invalid"}) from exc
        if stored.size_bytes != int(item["size_bytes"]) or stored.content_type != item["content_type"]:
            raise HTTPException(status_code=422, detail={"code": "support_attachment_metadata_mismatch"})
        verified.append(item)
    return verified


@router.post("/developer/support/attachments", status_code=status.HTTP_201_CREATED)
def initiate_support_attachment(
    payload: SupportAttachmentInitiate,
    ctx: AuthContext = Depends(require_developer_control_plane),
) -> dict:
    _flag("PLATFORM_API_SUPPORT_ENABLED")
    if not object_storage_configured():
        raise HTTPException(status_code=503, detail={"code": "support_attachment_storage_not_configured"})
    store = get_object_store()
    upload_url, storage_uri, required_headers = store.create_presigned_upload(
        tenant_id=ctx.organization.id,
        connection_id=SUPPORT_ATTACHMENT_CONNECTION_ID,
        filename=payload.filename,
        content_type=payload.content_type,
        expected_sha256=payload.sha256,
    )
    return {
        "attachment": {
            "object_id": storage_uri,
            "filename": payload.filename,
            "content_type": payload.content_type,
            "sha256": payload.sha256,
            "size_bytes": payload.size_bytes,
        },
        "upload": {
            "method": "PUT",
            "url": upload_url,
            "required_headers": {"content-type": payload.content_type, **required_headers},
            "expires_in_seconds": 900,
        },
    }


@router.post("/developer/support", status_code=status.HTTP_201_CREATED)
def create_support_request(
    payload: SupportCreate,
    request: Request,
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_SUPPORT_ENABLED")
    if payload.api_project_id:
        project = (
            db.query(ApiProject)
            .filter(ApiProject.id == payload.api_project_id, ApiProject.organization_id == ctx.organization.id)
            .first()
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Not found")
    if payload.webhook_delivery_id:
        delivery = (
            db.query(PlatformWebhookDeliveryAttempt)
            .join(PlatformWebhookEndpoint, PlatformWebhookEndpoint.id == PlatformWebhookDeliveryAttempt.endpoint_id)
            .filter(
                PlatformWebhookDeliveryAttempt.id == payload.webhook_delivery_id,
                PlatformWebhookEndpoint.organization_id == ctx.organization.id,
            )
            .first()
        )
        if delivery is None:
            raise HTTPException(status_code=404, detail="Not found")
    if payload.key_fingerprint:
        key = (
            db.query(PlatformApiKey)
            .filter(
                PlatformApiKey.organization_id == ctx.organization.id,
                PlatformApiKey.fingerprint == payload.key_fingerprint,
            )
            .first()
        )
        if key is None:
            raise HTTPException(status_code=404, detail="Not found")
    if payload.job_id:
        job = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.id == payload.job_id,
                IngestionJob.tenant_id == ctx.organization.id,
            )
            .first()
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Not found")
    if payload.request_id:
        request_log = (
            db.query(PlatformRequestLog)
            .filter(
                PlatformRequestLog.organization_id == ctx.organization.id,
                PlatformRequestLog.request_id == payload.request_id,
            )
            .first()
        )
        if request_log is None:
            raise HTTPException(status_code=404, detail="Not found")
    row = PlatformSupportRequest(
        organization_id=ctx.organization.id,
        api_project_id=payload.api_project_id,
        created_by_user_id=ctx.user.id,
        category=payload.category,
        severity=payload.severity,
        subject=payload.subject,
        description=payload.description,
        environment=payload.environment,
        request_id_reference=payload.request_id,
        key_fingerprint=payload.key_fingerprint,
        job_id=payload.job_id,
        webhook_delivery_id=payload.webhook_delivery_id,
        invoice_reference=payload.invoice_reference,
        contact_email=payload.contact_email,
        attachment_references_json=_verify_support_attachments(ctx.organization.id, payload.attachments),
        status="open",
    )
    db.add(row)
    db.flush()
    record_product_audit(
        db,
        event_type="platform.support.created",
        subject_type="support_request",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
        metadata={"category": row.category, "severity": row.severity},
    )
    queue_and_send_product_email(
        db,
        organization_id=row.organization_id,
        user_id=ctx.user.id,
        to_email=ctx.user.email,
        notification_type="support_received",
        dedupe_key=f"support:{row.id}:received",
    )
    db.commit()
    return {"support_request": _support_public(row)}


@router.get("/developer/support")
def list_support_requests(
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_SUPPORT_ENABLED")
    rows = (
        db.query(PlatformSupportRequest)
        .filter(PlatformSupportRequest.organization_id == ctx.organization.id)
        .order_by(PlatformSupportRequest.created_at.desc())
        .all()
    )
    return {"support_requests": [_support_public(row) for row in rows]}


@router.post("/developer/support/{support_id}/messages")
def customer_support_reply(
    support_id: str,
    payload: SupportReply,
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_SUPPORT_ENABLED")
    ticket = (
        db.query(PlatformSupportRequest)
        .filter(
            PlatformSupportRequest.id == support_id,
            PlatformSupportRequest.organization_id == ctx.organization.id,
        )
        .first()
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Not found")
    message = PlatformSupportMessage(
        support_request_id=ticket.id,
        author_user_id=ctx.user.id,
        visibility="customer",
        body=payload.body,
    )
    db.add(message)
    ticket.status = "open"
    db.flush()
    record_product_audit(
        db,
        event_type="platform.support.customer_replied",
        subject_type="support_request",
        subject_id=ticket.id,
        organization_id=ticket.organization_id,
        actor_user_id=ctx.user.id,
        metadata={"message_id": message.id},
    )
    db.commit()
    return {"status": "created", "message_id": message.id}


@router.get("/admin/support")
def admin_support_queue(
    support_status: str | None = Query(default=None, alias="status"),
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_SUPPORT_ENABLED")
    query = db.query(PlatformSupportRequest)
    if support_status:
        query = query.filter(PlatformSupportRequest.status == support_status)
    rows = query.order_by(PlatformSupportRequest.created_at.asc()).limit(500).all()
    return {"support_requests": [_support_public(row, admin=True) for row in rows]}


@router.patch("/admin/support/{support_id}")
def admin_update_support(
    support_id: str,
    payload: SupportAdminUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_SUPPORT_ENABLED")
    ticket = db.get(PlatformSupportRequest, support_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.status:
        ticket.status = payload.status
    if payload.assigned_to_user_id is not None:
        ticket.assigned_to_user_id = payload.assigned_to_user_id
    if payload.internal_note:
        db.add(
            PlatformSupportMessage(
                support_request_id=ticket.id,
                author_user_id=ctx.user.id,
                visibility="internal",
                body=payload.internal_note,
            )
        )
    if payload.customer_response:
        customer_message = PlatformSupportMessage(
            support_request_id=ticket.id,
            author_user_id=ctx.user.id,
            visibility="customer",
            body=payload.customer_response,
        )
        db.add(customer_message)
        db.flush()
        customer = db.get(User, ticket.created_by_user_id)
        if customer is not None:
            queue_and_send_product_email(
                db,
                organization_id=ticket.organization_id,
                user_id=customer.id,
                to_email=customer.email,
                notification_type="support_response",
                dedupe_key=f"support:{ticket.id}:response:{customer_message.id}",
            )
    record_product_audit(
        db,
        event_type="platform.support.updated",
        subject_type="support_request",
        subject_id=ticket.id,
        organization_id=ticket.organization_id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        request_id=getattr(request.state, "request_id", None),
        metadata={"status": ticket.status},
    )
    db.commit()
    return {"support_request": _support_public(ticket, admin=True)}


@router.get("/status")
def public_status(db: Session = Depends(get_db)) -> dict:
    _flag("PLATFORM_API_STATUS_PAGE_ENABLED")
    components = db.query(PlatformStatusComponent).filter(PlatformStatusComponent.public.is_(True)).all()
    incidents = (
        db.query(PlatformStatusIncident)
        .filter(PlatformStatusIncident.status != "resolved")
        .order_by(PlatformStatusIncident.started_at.desc())
        .all()
    )
    return {
        "status": "published_without_sla",
        "uptime_claim": None,
        "components": [{"key": row.component_key, "name": row.display_name, "status": row.status} for row in components],
        "incidents": [
            {
                "id": row.id,
                "title": row.title,
                "status": row.status,
                "severity": row.severity,
                "summary": row.public_summary,
                "components": row.component_keys_json,
                "started_at": row.started_at.isoformat(),
                "updates": [
                    {
                        "status": update.status,
                        "message": update.public_message,
                        "created_at": update.created_at.isoformat(),
                    }
                    for update in (
                        db.query(PlatformStatusIncidentUpdate)
                        .filter(PlatformStatusIncidentUpdate.incident_id == row.id)
                        .order_by(PlatformStatusIncidentUpdate.created_at.asc())
                        .all()
                    )
                ],
            }
            for row in incidents
        ],
    }


@router.post("/admin/status/components/seed")
def seed_status_components(
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_STATUS_PAGE_ENABLED")
    for key, name in COMPONENTS:
        if db.query(PlatformStatusComponent).filter(PlatformStatusComponent.component_key == key).first() is None:
            db.add(PlatformStatusComponent(component_key=key, display_name=name, status="operational", public=True))
    record_product_audit(
        db,
        event_type="platform.status.components_seeded",
        subject_type="status_component_catalog",
        subject_id="platform-api",
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        request_id=getattr(request.state, "request_id", None),
        metadata={"component_count": len(COMPONENTS)},
    )
    db.commit()
    return {"status": "seeded", "component_count": len(COMPONENTS)}


@router.patch("/admin/status/components/{component_key}")
def update_status_component(
    component_key: str,
    payload: ComponentUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_STATUS_PAGE_ENABLED")
    row = (
        db.query(PlatformStatusComponent)
        .filter(PlatformStatusComponent.component_key == component_key)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    row.status = payload.status
    record_product_audit(
        db,
        event_type="platform.status.component_updated",
        subject_type="status_component",
        subject_id=row.id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={"component_key": component_key, "status": payload.status},
    )
    db.commit()
    return {"component_key": component_key, "status": row.status}


@router.post("/admin/status/incidents", status_code=status.HTTP_201_CREATED)
def create_incident(
    payload: IncidentCreate,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_STATUS_PAGE_ENABLED")
    known = {key for key, _name in COMPONENTS}
    if any(key not in known for key in payload.component_keys):
        raise HTTPException(status_code=422, detail={"code": "unknown_status_component"})
    row = PlatformStatusIncident(
        title=payload.title,
        status="investigating",
        severity=payload.severity,
        public_summary=payload.public_summary,
        component_keys_json=payload.component_keys,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    record_product_audit(
        db,
        event_type="platform.status.incident_created",
        subject_type="status_incident",
        subject_id=row.id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return {"incident_id": row.id, "status": row.status}


@router.post("/admin/status/incidents/{incident_id}/updates")
def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_STATUS_PAGE_ENABLED")
    incident = db.get(PlatformStatusIncident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Not found")
    incident.status = payload.status
    incident.public_summary = payload.public_message
    incident.resolved_at = datetime.utcnow() if payload.status == "resolved" else None
    update = PlatformStatusIncidentUpdate(
        incident_id=incident.id,
        status=payload.status,
        public_message=payload.public_message,
        created_by_user_id=ctx.user.id,
    )
    db.add(update)
    record_product_audit(
        db,
        event_type="platform.status.incident_updated",
        subject_type="status_incident",
        subject_id=incident.id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        request_id=getattr(request.state, "request_id", None),
        metadata={"status": payload.status},
    )
    db.commit()
    return {"incident_id": incident.id, "status": incident.status, "update_id": update.id}


@router.put("/admin/partner-dossiers/{provider_id}")
def upsert_partner_dossier(
    provider_id: str,
    payload: PartnerDossierWrite,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_PARTNER_PROGRAM_ENABLED")
    normalized = provider_id.strip().lower()
    if normalized != payload.provider_id:
        raise HTTPException(status_code=422, detail={"code": "provider_id_mismatch"})
    if db.get(Organization, payload.organization_id) is None:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.application_id:
        application = db.get(PlatformApiApplication, payload.application_id)
        if application is None or application.organization_id != payload.organization_id:
            raise HTTPException(status_code=404, detail="Not found")
    if payload.enrollment_id:
        enrollment = db.get(PlatformProgramEnrollment, payload.enrollment_id)
        if enrollment is None or enrollment.organization_id != payload.organization_id:
            raise HTTPException(status_code=404, detail="Not found")
    row = (
        db.query(PlatformPartnerDossier)
        .filter(
            PlatformPartnerDossier.organization_id == payload.organization_id,
            PlatformPartnerDossier.provider_id == normalized,
        )
        .first()
    )
    if row is None:
        row = PlatformPartnerDossier(organization_id=payload.organization_id, provider_id=normalized, partner_name=payload.partner_name)
        db.add(row)
    for field_name, value in payload.model_dump().items():
        column = {
            "support_contacts": "support_contacts_json",
            "milestones": "milestones_json",
            "blockers": "blockers_json",
            "custom_rate_card": "custom_rate_card_json",
            "custom_limits": "custom_limits_json",
            "document_references": "document_references_json",
            "credential_vault_references": "credential_vault_references_json",
        }.get(field_name, field_name)
        if field_name not in {"organization_id", "provider_id"}:
            setattr(row, column, value)
    row.integration_owner_user_id = ctx.user.id
    record_product_audit(
        db,
        event_type="platform.partner_dossier.updated",
        subject_type="partner_dossier",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        request_id=getattr(request.state, "request_id", None),
        metadata={"provider_id": row.provider_id},
    )
    db.commit()
    return {
        "dossier": {
            "id": row.id,
            "organization_id": row.organization_id,
            "partner_name": row.partner_name,
            "provider_id": row.provider_id,
            "contract_status": row.contract_status,
            "read_readiness": row.read_readiness,
            "write_readiness": row.write_readiness,
            "sandbox_readiness": row.sandbox_readiness,
            "production_readiness": row.production_readiness,
            "blockers": row.blockers_json,
        }
    }


@router.get("/admin/partner-dossiers")
def list_partner_dossiers(
    provider_id: str | None = None,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_PARTNER_PROGRAM_ENABLED")
    query = db.query(PlatformPartnerDossier)
    if provider_id:
        query = query.filter(PlatformPartnerDossier.provider_id == provider_id.strip().lower())
    rows = query.order_by(PlatformPartnerDossier.updated_at.desc()).limit(500).all()
    return {
        "dossiers": [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "application_id": row.application_id,
                "enrollment_id": row.enrollment_id,
                "partner_name": row.partner_name,
                "provider_id": row.provider_id,
                "contract_status": row.contract_status,
                "documentation_received": row.documentation_received,
                "authentication_confirmed": row.authentication_confirmed,
                "read_readiness": row.read_readiness,
                "write_readiness": row.write_readiness,
                "sandbox_readiness": row.sandbox_readiness,
                "production_readiness": row.production_readiness,
                "blockers": list(row.blockers_json or []),
                "document_references": list(row.document_references_json or []),
                "credential_vault_references": list(row.credential_vault_references_json or []),
            }
            for row in rows
        ]
    }


@router.get("/admin/abuse")
def list_abuse_events(
    abuse_status: str | None = Query(default=None, alias="status"),
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_PRIVATE_BETA_ENABLED")
    query = db.query(PlatformAbuseEvent)
    if abuse_status:
        query = query.filter(PlatformAbuseEvent.status == abuse_status)
    rows = query.order_by(PlatformAbuseEvent.created_at.desc()).limit(500).all()
    return {
        "events": [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "api_project_id": row.api_project_id,
                "signal_type": row.signal_type,
                "severity": row.severity,
                "status": row.status,
                "automated_action": row.automated_action,
                "evidence_summary": row.evidence_summary_json,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.post("/admin/abuse/{event_id}/review")
def review_abuse_event(
    event_id: str,
    payload: AbuseReview,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_PRIVATE_BETA_ENABLED")
    row = db.get(PlatformAbuseEvent, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    row.status = payload.status
    row.reviewed_by_user_id = ctx.user.id
    row.reviewed_at = datetime.utcnow()
    if payload.action == "disable_key" and row.api_key_id:
        key = db.get(PlatformApiKey, row.api_key_id)
        if key and key.organization_id == row.organization_id:
            key.status = "disabled"
    elif payload.action == "disable_project" and row.api_project_id:
        project = db.get(ApiProject, row.api_project_id)
        if project and project.organization_id == row.organization_id:
            project.status = "disabled"
    row.automated_action = payload.action
    record_product_audit(
        db,
        event_type="platform.abuse.reviewed",
        subject_type="abuse_event",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        metadata={"action": payload.action},
    )
    db.commit()
    return {"status": row.status, "action": row.automated_action}
