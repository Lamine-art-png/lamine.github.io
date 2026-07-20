"""Platform API applications, program enrollment, and live-access review."""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context, require_platform_admin
from app.core.config import settings
from app.db.base import get_db
from app.models.platform_api import ApiProject
from app.models.platform_product import (
    PlatformApiApplication,
    PlatformLiveAccessRequest,
    PlatformPartnerDossier,
    PlatformProductAuditEvent,
    PlatformProgramEnrollment,
    PlatformTermsAcceptance,
    PlatformTermsDocument,
)
from app.models.saas import User
from app.platform_api.product_audit import record_product_audit
from app.platform_api.abuse import record_abuse_signal
from app.platform_api.product_emails import queue_and_send_product_email
from app.platform_api.deps import require_developer_control_plane
from app.platform_api.programs import PROGRAMS
from app.services.object_storage import get_object_store, object_storage_configured
from app.services.security_audit import privacy_hash

router = APIRouter(prefix="/platform", tags=["platform-access"])

APPLICATION_TYPES = frozenset({"developer_beta", "strategic_partner", "live_access", "enterprise_custom"})
APPLICATION_STATUSES = frozenset({"draft", "submitted", "under_review", "needs_information", "approved", "rejected", "withdrawn", "expired"})
REVIEW_STATUSES = frozenset({"under_review", "needs_information", "approved", "rejected", "expired"})
LIVE_STATUSES = frozenset({"submitted", "under_review", "needs_information", "approved", "denied", "suspended", "expired"})
EMAIL_RE = re.compile(r"^[^@\s\r\n]+@[^@\s\r\n]+\.[^@\s\r\n]+$")
APPLICATION_DOCUMENT_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/csv",
        "text/plain",
    }
)
APPLICATION_DOCUMENT_CONNECTION_ID = "platform-applications"


def _flag(name: str) -> None:
    if not bool(getattr(settings, name, False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _https_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("a credential-free HTTPS URL is required")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return value.strip()
    if not address.is_global:
        raise ValueError("public HTTPS URL required")
    return value.strip()


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 254 or not EMAIL_RE.fullmatch(normalized):
        raise ValueError("valid email address required")
    return normalized


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_type: str
    organization_website: str = Field(min_length=8, max_length=2048)
    corporate_email: str = Field(min_length=5, max_length=254)
    company_description: str = Field(min_length=20, max_length=4000)
    intended_product: str = Field(min_length=10, max_length=4000)
    use_case: str = Field(min_length=10, max_length=4000)
    target_users: str = Field(min_length=2, max_length=1000)
    expected_api_operations: list[str] = Field(min_length=1, max_length=50)
    expected_monthly_volume: str = Field(min_length=1, max_length=120)
    expected_data_volume: str = Field(min_length=1, max_length=120)
    requested_environment: str
    required_providers: list[str] = Field(default_factory=list, max_length=30)
    geography: list[str] = Field(default_factory=list, max_length=50)
    data_residency_needs: str | None = Field(default=None, max_length=2000)
    compliance_needs: str | None = Field(default=None, max_length=2000)
    security_contact: str
    technical_contact: str
    billing_contact: str | None = None
    target_integration_date: datetime | None = None
    requested_support: str = Field(min_length=2, max_length=120)
    partner_documentation_status: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)
    terms_version: str = Field(min_length=1, max_length=80)
    privacy_version: str = Field(min_length=1, max_length=80)
    provider_company: str | None = Field(default=None, max_length=200)
    integration_category: str | None = Field(default=None, max_length=120)
    sandbox_availability: str | None = Field(default=None, max_length=120)
    authentication_type: str | None = Field(default=None, max_length=120)
    expected_resources: list[str] = Field(default_factory=list, max_length=100)
    webhook_needs: str | None = Field(default=None, max_length=2000)
    read_capabilities: list[str] = Field(default_factory=list, max_length=100)
    potential_write_capabilities: list[str] = Field(default_factory=list, max_length=100)
    nda_status: str | None = Field(default=None, max_length=120)
    contract_status: str | None = Field(default=None, max_length=120)
    technical_owner: str | None = Field(default=None, max_length=254)
    commercial_owner: str | None = Field(default=None, max_length=254)
    implementation_stage: str | None = Field(default=None, max_length=120)
    readiness_blockers: list[str] = Field(default_factory=list, max_length=100)
    document_references: list[dict] = Field(default_factory=list, max_length=30)
    bot_field: str = Field(default="", max_length=0)

    @field_validator("application_type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in APPLICATION_TYPES:
            raise ValueError("unsupported application type")
        return value

    @field_validator("requested_environment")
    @classmethod
    def valid_environment(cls, value: str) -> str:
        if value not in {"test", "live", "test_and_live"}:
            raise ValueError("unsupported environment")
        return value

    @field_validator("organization_website")
    @classmethod
    def valid_website(cls, value: str) -> str:
        return _https_url(value)

    @field_validator("corporate_email", "security_contact", "technical_contact", "billing_contact", "technical_owner", "commercial_owner")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        return _email(value) if value else value

    @field_validator(
        "expected_api_operations",
        "required_providers",
        "geography",
        "expected_resources",
        "read_capabilities",
        "potential_write_capabilities",
        "readiness_blockers",
    )
    @classmethod
    def bounded_values(cls, values: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in values]
        if any(not item or len(item) > 200 or "\r" in item or "\n" in item for item in normalized):
            raise ValueError("list values must be non-empty and at most 200 characters")
        return list(dict.fromkeys(normalized))

    @field_validator("document_references")
    @classmethod
    def safe_document_refs(cls, values: list[dict]) -> list[dict]:
        safe: list[dict] = []
        allowed = {"object_id", "filename", "content_type", "sha256", "size_bytes"}
        for item in values:
            if set(item) - allowed or not item.get("object_id") or not item.get("sha256"):
                raise ValueError("document references must contain safe object-storage metadata only")
            if len(str(item["object_id"])) > 1000 or len(str(item.get("filename") or "")) > 240:
                raise ValueError("document metadata is too large")
            if str(item.get("content_type") or "") not in APPLICATION_DOCUMENT_CONTENT_TYPES:
                raise ValueError("document content type is not permitted")
            if not re.fullmatch(r"[a-f0-9]{64}", str(item["sha256"])):
                raise ValueError("document checksum is invalid")
            if not 0 < int(item.get("size_bytes") or 0) <= int(settings.PLATFORM_API_SUPPORT_MAX_ATTACHMENT_BYTES):
                raise ValueError("document is too large")
            safe.append({key: item[key] for key in allowed if key in item})
        return safe


class ApplicationDocumentInitiate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=240)
    content_type: str
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)

    @field_validator("content_type")
    @classmethod
    def safe_content_type(cls, value: str) -> str:
        if value not in APPLICATION_DOCUMENT_CONTENT_TYPES:
            raise ValueError("document content type is not permitted")
        return value

    @field_validator("size_bytes")
    @classmethod
    def safe_size(cls, value: int) -> int:
        if value > int(settings.PLATFORM_API_SUPPORT_MAX_ATTACHMENT_BYTES):
            raise ValueError("document is too large")
        return value


class ApplicationAdditionalInformation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = Field(min_length=10, max_length=4000)
    document_references: list[dict] = Field(default_factory=list, max_length=30)

    @field_validator("document_references")
    @classmethod
    def safe_document_refs(cls, values: list[dict]) -> list[dict]:
        return ApplicationCreate.safe_document_refs(values)


class ApplicationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    reason: str = Field(min_length=3, max_length=4000)
    assigned_reviewer_user_id: str | None = None
    program: str | None = None
    allowed_environments: list[str] = Field(default_factory=lambda: ["test"])
    maximum_projects: int = Field(default=1, ge=0, le=10000)
    maximum_live_projects: int = Field(default=0, ge=0, le=10000)
    maximum_service_accounts: int = Field(default=2, ge=0, le=10000)
    maximum_keys: int = Field(default=2, ge=0, le=10000)
    maximum_webhooks: int = Field(default=1, ge=0, le=10000)
    provider_restrictions: dict = Field(default_factory=dict)
    resource_restrictions: dict = Field(default_factory=dict)
    default_scopes: list[str] = Field(default_factory=list, max_length=100)
    rate_limit_policy: dict = Field(default_factory=dict)
    quota_policy: dict = Field(default_factory=dict)
    billing_mode: str = "none"
    plan_identifier: str | None = None
    contract_reference: str | None = Field(default=None, max_length=200)
    support_tier: str = Field(default="documentation", max_length=120)
    data_retention_policy: dict = Field(default_factory=dict)
    expires_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in REVIEW_STATUSES:
            raise ValueError("unsupported review status")
        return value

    @field_validator("program")
    @classmethod
    def valid_program(cls, value: str | None) -> str | None:
        if value is not None and value not in PROGRAMS:
            raise ValueError("unsupported program")
        return value

    @field_validator("allowed_environments")
    @classmethod
    def valid_environments(cls, values: list[str]) -> list[str]:
        if not values or any(value not in {"test", "live"} for value in values):
            raise ValueError("allowed environments must contain test and/or live")
        return list(dict.fromkeys(values))


class LiveAccessCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_project_id: str | None = None
    intended_production_use: str = Field(min_length=20, max_length=4000)
    expected_users: str = Field(min_length=1, max_length=200)
    expected_volume: str = Field(min_length=1, max_length=200)
    expected_peak_rate: str = Field(min_length=1, max_length=200)
    data_categories: list[str] = Field(min_length=1, max_length=50)
    provider_dependencies: list[str] = Field(default_factory=list, max_length=30)
    geographic_regions: list[str] = Field(min_length=1, max_length=50)
    security_contact: str
    incident_contact: str
    compliance_needs: str | None = Field(default=None, max_length=2000)
    cidr_strategy: str = Field(min_length=3, max_length=2000)
    webhook_use: str | None = Field(default=None, max_length=2000)
    data_retention: str = Field(min_length=2, max_length=200)
    billing_plan: str = Field(min_length=2, max_length=120)
    target_launch_date: datetime | None = None

    @field_validator("security_contact", "incident_contact")
    @classmethod
    def contacts(cls, value: str) -> str:
        return _email(value)


class LiveAccessReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    reason: str = Field(min_length=3, max_length=4000)
    conditions: list[str] = Field(default_factory=list, max_length=100)
    expires_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in LIVE_STATUSES - {"submitted"}:
            raise ValueError("unsupported live-access status")
        return value


class EnrollmentSuspend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=2000)


class TermsAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: str
    document_version: str = Field(min_length=1, max_length=80)

    @field_validator("document_type")
    @classmethod
    def legal_type(cls, value: str) -> str:
        if value not in {"api_terms", "acceptable_use", "privacy", "data_processing_addendum"}:
            raise ValueError("unsupported document type")
        return value


class TermsDocumentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(draft_legal_review_required|approved_effective|retired)$")
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    effective_at: datetime | None = None
    reacceptance_required: bool = False
    reason: str = Field(min_length=3, max_length=2000)


def _application_public(row: PlatformApiApplication, *, admin: bool = False) -> dict:
    result = {
        "id": row.id,
        "organization_id": row.organization_id,
        "application_type": row.application_type,
        "status": row.status,
        "organization_website": row.organization_website,
        "intended_product": row.intended_product,
        "use_case": row.use_case,
        "requested_environment": row.requested_environment,
        "required_providers": list(row.required_providers_json or []),
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
    if admin:
        result.update(
            {
                "applicant_user_id": row.applicant_user_id,
                "corporate_email": row.corporate_email,
                "company_description": row.company_description,
                "target_users": row.target_users,
                "expected_api_operations": list(row.expected_api_operations_json or []),
                "expected_monthly_volume": row.expected_monthly_volume,
                "expected_data_volume": row.expected_data_volume,
                "geography": list(row.geography_json or []),
                "compliance_needs": row.compliance_needs,
                "requested_support": row.requested_support,
                "partner_documentation_status": row.partner_documentation_status,
                "readiness_blockers": list(row.readiness_blockers_json or []),
                "document_references": list(row.document_references_json or []),
                "assigned_reviewer_user_id": row.assigned_reviewer_user_id,
                "decision_reason": row.decision_reason,
            }
        )
    return result


def _verify_application_documents(organization_id: str, documents: list[dict]) -> list[dict]:
    if not documents:
        return []
    if not object_storage_configured():
        raise HTTPException(status_code=503, detail={"code": "application_document_storage_not_configured"})
    store = get_object_store()
    verified: list[dict] = []
    for item in documents:
        try:
            stored = store.inspect(
                item["object_id"],
                tenant_id=organization_id,
                connection_id=APPLICATION_DOCUMENT_CONNECTION_ID,
                max_bytes=int(settings.PLATFORM_API_SUPPORT_MAX_ATTACHMENT_BYTES),
                expected_sha256=item["sha256"],
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail={"code": "application_document_invalid"}) from exc
        if stored.size_bytes != int(item["size_bytes"]) or stored.content_type != item["content_type"]:
            raise HTTPException(status_code=422, detail={"code": "application_document_metadata_mismatch"})
        verified.append(item)
    return verified


@router.post("/applications/documents", status_code=status.HTTP_201_CREATED)
def initiate_application_document(
    payload: ApplicationDocumentInitiate,
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    assert ctx.organization is not None
    if not object_storage_configured():
        raise HTTPException(status_code=503, detail={"code": "application_document_storage_not_configured"})
    store = get_object_store()
    upload_url, storage_uri, required_headers = store.create_presigned_upload(
        tenant_id=ctx.organization.id,
        connection_id=APPLICATION_DOCUMENT_CONNECTION_ID,
        filename=payload.filename,
        content_type=payload.content_type,
        expected_sha256=payload.sha256,
    )
    return {
        "document": {
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


@router.post("/applications", status_code=status.HTTP_202_ACCEPTED)
def submit_application(
    payload: ApplicationCreate,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    if payload.application_type == "strategic_partner":
        _flag("PLATFORM_API_PARTNER_PROGRAM_ENABLED")
        if not payload.provider_company or not payload.integration_category:
            raise HTTPException(status_code=422, detail={"code": "partner_fields_required"})
    since = datetime.utcnow() - timedelta(days=1)
    count = (
        db.query(PlatformApiApplication)
        .filter(
            PlatformApiApplication.applicant_user_id == ctx.user.id,
            PlatformApiApplication.created_at >= since,
        )
        .count()
    )
    if count >= int(settings.PLATFORM_API_APPLICATION_LIMIT_PER_DAY):
        assert ctx.organization is not None
        record_abuse_signal(
            db,
            signal_type="application_spam_threshold",
            severity="medium",
            organization_id=ctx.organization.id,
            automated_action="throttle",
            evidence={"window": "24h", "submission_count": count},
        )
        db.commit()
        raise HTTPException(status_code=429, detail={"code": "application_rate_limited", "message": "Application submission limit reached."})
    assert ctx.organization is not None
    row = PlatformApiApplication(
        applicant_user_id=ctx.user.id,
        organization_id=ctx.organization.id,
        application_type=payload.application_type,
        status="submitted",
        organization_website=payload.organization_website,
        corporate_email=payload.corporate_email,
        company_description=payload.company_description,
        intended_product=payload.intended_product,
        use_case=payload.use_case,
        target_users=payload.target_users,
        expected_api_operations_json=payload.expected_api_operations,
        expected_monthly_volume=payload.expected_monthly_volume,
        expected_data_volume=payload.expected_data_volume,
        requested_environment=payload.requested_environment,
        required_providers_json=payload.required_providers,
        geography_json=payload.geography,
        data_residency_needs=payload.data_residency_needs,
        compliance_needs=payload.compliance_needs,
        security_contact=payload.security_contact,
        technical_contact=payload.technical_contact,
        billing_contact=payload.billing_contact,
        target_integration_date=payload.target_integration_date,
        requested_support=payload.requested_support,
        partner_documentation_status=payload.partner_documentation_status,
        notes=payload.notes,
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
        provider_company=payload.provider_company,
        integration_category=payload.integration_category,
        sandbox_availability=payload.sandbox_availability,
        authentication_type=payload.authentication_type,
        expected_resources_json=payload.expected_resources,
        webhook_needs=payload.webhook_needs,
        read_capabilities_json=payload.read_capabilities,
        potential_write_capabilities_json=payload.potential_write_capabilities,
        nda_status=payload.nda_status,
        contract_status=payload.contract_status,
        technical_owner=payload.technical_owner,
        commercial_owner=payload.commercial_owner,
        implementation_stage=payload.implementation_stage,
        readiness_blockers_json=payload.readiness_blockers,
        document_references_json=_verify_application_documents(ctx.organization.id, payload.document_references),
        submitted_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    record_product_audit(
        db,
        event_type="platform.application.submitted",
        subject_type="application",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
        metadata={"application_type": row.application_type},
    )
    queue_and_send_product_email(
        db,
        organization_id=row.organization_id,
        user_id=ctx.user.id,
        to_email=ctx.user.email,
        notification_type="application_received",
        dedupe_key=f"application:{row.id}:received",
    )
    db.commit()
    return {"status": "submitted", "application": _application_public(row)}


@router.get("/applications")
def list_applications(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    assert ctx.organization is not None
    rows = (
        db.query(PlatformApiApplication)
        .filter(PlatformApiApplication.organization_id == ctx.organization.id)
        .order_by(PlatformApiApplication.created_at.desc())
        .all()
    )
    return {"applications": [_application_public(row) for row in rows]}


@router.post("/applications/{application_id}/additional-information", status_code=status.HTTP_202_ACCEPTED)
def submit_application_additional_information(
    application_id: str,
    payload: ApplicationAdditionalInformation,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    assert ctx.organization is not None
    row = (
        db.query(PlatformApiApplication)
        .filter(
            PlatformApiApplication.id == application_id,
            PlatformApiApplication.organization_id == ctx.organization.id,
            PlatformApiApplication.applicant_user_id == ctx.user.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    if row.status != "needs_information":
        raise HTTPException(status_code=409, detail={"code": "application_information_not_requested"})
    documents = _verify_application_documents(ctx.organization.id, payload.document_references)
    row.notes = payload.notes
    row.document_references_json = list(row.document_references_json or []) + documents
    row.status = "submitted"
    row.submitted_at = datetime.utcnow()
    row.decided_at = None
    record_product_audit(
        db,
        event_type="platform.application.additional_information_submitted",
        subject_type="application",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
        metadata={"document_count": len(documents)},
    )
    db.commit()
    return {"status": "submitted", "application": _application_public(row)}


@router.post("/applications/{application_id}/withdraw")
def withdraw_application(
    application_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    assert ctx.organization is not None
    row = (
        db.query(PlatformApiApplication)
        .filter(
            PlatformApiApplication.id == application_id,
            PlatformApiApplication.organization_id == ctx.organization.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    is_applicant = row.applicant_user_id == ctx.user.id
    is_org_admin = bool(
        ctx.membership
        and getattr(ctx.membership, "status", "active") == "active"
        and ctx.membership.role in {"owner", "admin"}
    )
    if not is_applicant and not is_org_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "application_withdrawal_not_authorized"},
        )
    if row.status not in {"draft", "submitted", "under_review", "needs_information"}:
        raise HTTPException(status_code=409, detail={"code": "application_not_withdrawable"})
    row.status = "withdrawn"
    record_product_audit(
        db,
        event_type="platform.application.withdrawn",
        subject_type="application",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return {"status": "withdrawn", "application_id": row.id}


@router.get("/admin/applications")
def admin_list_applications(
    application_status: str | None = Query(default=None, alias="status"),
    application_type: str | None = None,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    query = db.query(PlatformApiApplication)
    if application_status:
        query = query.filter(PlatformApiApplication.status == application_status)
    if application_type:
        query = query.filter(PlatformApiApplication.application_type == application_type)
    rows = query.order_by(PlatformApiApplication.created_at.desc()).limit(500).all()
    return {"applications": [_application_public(row, admin=True) for row in rows]}


@router.post("/admin/applications/{application_id}/review")
def review_application(
    application_id: str,
    payload: ApplicationReview,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    row = db.get(PlatformApiApplication, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    if row.status in {"withdrawn", "expired"}:
        raise HTTPException(status_code=409, detail={"code": "application_terminal"})
    row.status = payload.status
    row.decision_reason = payload.reason
    row.assigned_reviewer_user_id = payload.assigned_reviewer_user_id or ctx.user.id
    row.decided_at = datetime.utcnow() if payload.status in {"approved", "rejected"} else None
    enrollment = None
    if payload.status == "approved":
        if payload.program is None:
            raise HTTPException(status_code=422, detail={"code": "program_required"})
        if "live" in payload.allowed_environments:
            raise HTTPException(
                status_code=409,
                detail={"code": "live_access_separate_approval_required", "message": "Application approval cannot grant live access."},
            )
        enrollment = (
            db.query(PlatformProgramEnrollment)
            .filter(
                PlatformProgramEnrollment.organization_id == row.organization_id,
                PlatformProgramEnrollment.program == payload.program,
            )
            .first()
        )
        if enrollment is None:
            enrollment = PlatformProgramEnrollment(
                organization_id=row.organization_id,
                application_id=row.id,
                program=payload.program,
            )
            db.add(enrollment)
        enrollment.status = "active"
        enrollment.approved_by_user_id = ctx.user.id
        enrollment.approved_at = datetime.utcnow()
        enrollment.allowed_environments_json = payload.allowed_environments
        enrollment.maximum_projects = payload.maximum_projects
        enrollment.maximum_live_projects = payload.maximum_live_projects
        enrollment.maximum_service_accounts = payload.maximum_service_accounts
        enrollment.maximum_keys = payload.maximum_keys
        enrollment.maximum_webhooks = payload.maximum_webhooks
        enrollment.provider_restrictions_json = payload.provider_restrictions
        enrollment.resource_restrictions_json = payload.resource_restrictions
        enrollment.default_scopes_json = payload.default_scopes
        enrollment.rate_limit_policy_json = payload.rate_limit_policy
        enrollment.quota_policy_json = payload.quota_policy
        enrollment.billing_mode = payload.billing_mode
        enrollment.plan_identifier = payload.plan_identifier
        enrollment.contract_reference = payload.contract_reference
        enrollment.support_tier = payload.support_tier
        enrollment.data_retention_policy_json = payload.data_retention_policy
        enrollment.effective_at = datetime.utcnow()
        enrollment.expires_at = payload.expires_at
        db.flush()
    event = f"platform.application.{payload.status}"
    record_product_audit(
        db,
        event_type=event,
        subject_type="application",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={"program": payload.program} if payload.program else {},
    )
    applicant = db.get(User, row.applicant_user_id)
    if applicant:
        notification = {
            "needs_information": "needs_information",
            "approved": "application_approved",
            "rejected": "application_rejected",
        }.get(payload.status)
        if notification:
            queue_and_send_product_email(
                db,
                organization_id=row.organization_id,
                user_id=applicant.id,
                to_email=applicant.email,
                notification_type=notification,
                dedupe_key=f"application:{row.id}:{payload.status}",
            )
    db.commit()
    return {
        "status": payload.status,
        "application": _application_public(row, admin=True),
        "enrollment_id": enrollment.id if enrollment else None,
    }


@router.post("/admin/enrollments/{enrollment_id}/suspend")
def suspend_enrollment(
    enrollment_id: str,
    payload: EnrollmentSuspend,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    enrollment = db.get(PlatformProgramEnrollment, enrollment_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Not found")
    enrollment.status = "suspended"
    enrollment.suspended_at = datetime.utcnow()
    enrollment.suspension_reason = payload.reason
    record_product_audit(
        db,
        event_type="platform.enrollment.suspended",
        subject_type="program_enrollment",
        subject_id=enrollment.id,
        organization_id=enrollment.organization_id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return {"status": "suspended", "enrollment_id": enrollment.id}


@router.get("/admin/enrollments")
def admin_list_enrollments(
    enrollment_status: str | None = Query(default=None, alias="status"),
    program: str | None = None,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_APPLICATIONS_ENABLED")
    query = db.query(PlatformProgramEnrollment)
    if enrollment_status:
        query = query.filter(PlatformProgramEnrollment.status == enrollment_status)
    if program:
        if program not in PROGRAMS:
            raise HTTPException(status_code=422, detail={"code": "unknown_platform_program"})
        query = query.filter(PlatformProgramEnrollment.program == program)
    rows = query.order_by(PlatformProgramEnrollment.created_at.desc()).limit(500).all()
    return {
        "enrollments": [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "application_id": row.application_id,
                "program": row.program,
                "status": row.status,
                "allowed_environments": list(row.allowed_environments_json or []),
                "limits": {
                    "projects": row.maximum_projects,
                    "live_projects": row.maximum_live_projects,
                    "service_accounts": row.maximum_service_accounts,
                    "keys": row.maximum_keys,
                    "webhooks": row.maximum_webhooks,
                },
                "provider_restrictions": dict(row.provider_restrictions_json or {}),
                "resource_restrictions": dict(row.resource_restrictions_json or {}),
                "billing_mode": row.billing_mode,
                "plan_identifier": row.plan_identifier,
                "support_tier": row.support_tier,
                "effective_at": row.effective_at.isoformat() if row.effective_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in rows
        ]
    }


@router.post("/live-access", status_code=status.HTTP_202_ACCEPTED)
def submit_live_access(
    payload: LiveAccessCreate,
    request: Request,
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED")
    if settings.PLATFORM_API_LIVE_AUTO_APPROVAL_ENABLED:
        raise HTTPException(status_code=503, detail={"code": "unsafe_live_auto_approval_configuration"})
    assert ctx.organization is not None
    if payload.api_project_id:
        project = (
            db.query(ApiProject)
            .filter(ApiProject.id == payload.api_project_id, ApiProject.organization_id == ctx.organization.id)
            .first()
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Not found")
    row = PlatformLiveAccessRequest(
        organization_id=ctx.organization.id,
        requested_by_user_id=ctx.user.id,
        api_project_id=payload.api_project_id,
        status="submitted",
        intended_production_use=payload.intended_production_use,
        expected_users=payload.expected_users,
        expected_volume=payload.expected_volume,
        expected_peak_rate=payload.expected_peak_rate,
        data_categories_json=payload.data_categories,
        provider_dependencies_json=payload.provider_dependencies,
        geographic_regions_json=payload.geographic_regions,
        security_contact=payload.security_contact,
        incident_contact=payload.incident_contact,
        compliance_needs=payload.compliance_needs,
        cidr_strategy=payload.cidr_strategy,
        webhook_use=payload.webhook_use,
        data_retention=payload.data_retention,
        billing_plan=payload.billing_plan,
        target_launch_date=payload.target_launch_date,
        submitted_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    record_product_audit(
        db,
        event_type="platform.live_access.submitted",
        subject_type="live_access_request",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
    )
    queue_and_send_product_email(
        db,
        organization_id=row.organization_id,
        user_id=ctx.user.id,
        to_email=ctx.user.email,
        notification_type="live_access_received",
        dedupe_key=f"live-access:{row.id}:received",
    )
    db.commit()
    return {"status": "submitted", "live_access_request_id": row.id}


@router.get("/live-access")
def list_live_access(ctx: AuthContext = Depends(require_developer_control_plane), db: Session = Depends(get_db)) -> dict:
    _flag("PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED")
    assert ctx.organization is not None
    rows = (
        db.query(PlatformLiveAccessRequest)
        .filter(PlatformLiveAccessRequest.organization_id == ctx.organization.id)
        .order_by(PlatformLiveAccessRequest.created_at.desc())
        .all()
    )
    return {
        "requests": [
            {
                "id": row.id,
                "api_project_id": row.api_project_id,
                "status": row.status,
                "billing_plan": row.billing_plan,
                "target_launch_date": row.target_launch_date.isoformat() if row.target_launch_date else None,
                "conditions": list(row.conditions_json or []),
                "decision_reason": row.decision_reason,
            }
            for row in rows
        ]
    }


@router.get("/admin/live-access")
def admin_list_live_access(
    live_status: str | None = Query(default=None, alias="status"),
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED")
    query = db.query(PlatformLiveAccessRequest)
    if live_status:
        query = query.filter(PlatformLiveAccessRequest.status == live_status)
    rows = query.order_by(PlatformLiveAccessRequest.created_at.asc()).limit(500).all()
    return {
        "requests": [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "api_project_id": row.api_project_id,
                "status": row.status,
                "intended_production_use": row.intended_production_use,
                "expected_users": row.expected_users,
                "expected_volume": row.expected_volume,
                "expected_peak_rate": row.expected_peak_rate,
                "provider_dependencies": list(row.provider_dependencies_json or []),
                "geographic_regions": list(row.geographic_regions_json or []),
                "security_contact": row.security_contact,
                "incident_contact": row.incident_contact,
                "billing_plan": row.billing_plan,
                "target_launch_date": row.target_launch_date.isoformat() if row.target_launch_date else None,
                "conditions": list(row.conditions_json or []),
                "decision_reason": row.decision_reason,
            }
            for row in rows
        ]
    }


@router.post("/admin/live-access/{request_id}/review")
def review_live_access(
    request_id: str,
    payload: LiveAccessReview,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED")
    row = db.get(PlatformLiveAccessRequest, request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    row.status = payload.status
    row.decision_reason = payload.reason
    row.conditions_json = payload.conditions
    row.assigned_reviewer_user_id = ctx.user.id
    row.decided_at = datetime.utcnow() if payload.status in {"approved", "denied"} else None
    row.expires_at = payload.expires_at
    if payload.status == "approved":
        enrollments = (
            db.query(PlatformProgramEnrollment)
            .filter(
                PlatformProgramEnrollment.organization_id == row.organization_id,
                PlatformProgramEnrollment.status.in_(["active", "approved"]),
            )
            .all()
        )
        if not enrollments:
            raise HTTPException(status_code=409, detail={"code": "active_program_enrollment_required"})
        for enrollment in enrollments:
            allowed = set(enrollment.allowed_environments_json or [])
            allowed.add("live")
            enrollment.allowed_environments_json = sorted(allowed)
    record_product_audit(
        db,
        event_type=f"platform.live_access.{payload.status}",
        subject_type="live_access_request",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
    )
    applicant = db.get(User, row.requested_by_user_id)
    notification = {"approved": "live_access_approved", "denied": "live_access_denied", "suspended": "access_suspended"}.get(payload.status)
    if applicant and notification:
        queue_and_send_product_email(
            db,
            organization_id=row.organization_id,
            user_id=applicant.id,
            to_email=applicant.email,
            notification_type=notification,
            dedupe_key=f"live-access:{row.id}:{payload.status}",
        )
    db.commit()
    return {"status": row.status, "live_access_request_id": row.id}


@router.get("/admin/applications/{application_id}/audit")
def application_audit(
    application_id: str,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    row = db.get(PlatformApiApplication, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    events = (
        db.query(PlatformProductAuditEvent)
        .filter(
            PlatformProductAuditEvent.subject_type == "application",
            PlatformProductAuditEvent.subject_id == application_id,
        )
        .order_by(PlatformProductAuditEvent.created_at.asc())
        .all()
    )
    return {
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "outcome": event.outcome,
                "reason": event.reason,
                "actor_type": event.actor_type,
                "actor_user_id": event.actor_user_id,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ]
    }


@router.post("/terms/accept")
def accept_terms(
    payload: TermsAccept,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_TERMS_ENFORCEMENT_ENABLED")
    assert ctx.organization is not None
    document = (
        db.query(PlatformTermsDocument)
        .filter(
            PlatformTermsDocument.document_type == payload.document_type,
            PlatformTermsDocument.version == payload.document_version,
            PlatformTermsDocument.status == "approved_effective",
            PlatformTermsDocument.effective_at.is_not(None),
            PlatformTermsDocument.effective_at <= datetime.utcnow(),
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=422, detail={"code": "platform_terms_version_not_effective"})
    existing = (
        db.query(PlatformTermsAcceptance)
        .filter(
            PlatformTermsAcceptance.organization_id == ctx.organization.id,
            PlatformTermsAcceptance.user_id == ctx.user.id,
            PlatformTermsAcceptance.document_id == document.id,
            PlatformTermsAcceptance.document_type == payload.document_type,
            PlatformTermsAcceptance.document_version == payload.document_version,
        )
        .first()
    )
    if existing:
        return {"status": "accepted", "acceptance_id": existing.id}
    row = PlatformTermsAcceptance(
        organization_id=ctx.organization.id,
        user_id=ctx.user.id,
        document_id=document.id,
        document_type=payload.document_type,
        document_version=payload.document_version,
        ip_hash=privacy_hash(request.client.host if request.client else None, "platform-terms-ip"),
        user_agent_hash=privacy_hash(request.headers.get("user-agent", "")[:512], "platform-terms-user-agent"),
    )
    db.add(row)
    db.flush()
    record_product_audit(
        db,
        event_type="platform.terms.accepted",
        subject_type="terms_acceptance",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
        metadata={"document_type": row.document_type, "document_version": row.document_version},
    )
    db.commit()
    return {"status": "accepted", "acceptance_id": row.id}


@router.get("/terms")
def list_required_terms(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_TERMS_ENFORCEMENT_ENABLED")
    from app.platform_api.terms import required_documents

    return {
        "documents": [
            {
                "document_type": row.document_type,
                "version": row.version,
                "content_digest": row.content_digest,
                "effective_at": row.effective_at.isoformat() if row.effective_at else None,
                "legal_review_status": row.status,
                "reacceptance_required": bool(row.reacceptance_required),
            }
            for row in required_documents(db)
        ]
    }


@router.put("/admin/terms/{document_type}/{version}")
def upsert_terms_document(
    document_type: str,
    version: str,
    payload: TermsDocumentWrite,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_TERMS_ENFORCEMENT_ENABLED")
    if document_type not in {"api_terms", "acceptable_use", "privacy", "data_processing_addendum"}:
        raise HTTPException(status_code=422, detail={"code": "unsupported_terms_document"})
    if not version or len(version) > 80:
        raise HTTPException(status_code=422, detail={"code": "invalid_terms_version"})
    if payload.status == "approved_effective" and payload.effective_at is None:
        raise HTTPException(status_code=422, detail={"code": "terms_effective_at_required"})
    row = (
        db.query(PlatformTermsDocument)
        .filter(
            PlatformTermsDocument.document_type == document_type,
            PlatformTermsDocument.version == version,
        )
        .first()
    )
    if row is None:
        row = PlatformTermsDocument(document_type=document_type, version=version)
        db.add(row)
        db.flush()
    row.status = payload.status
    row.content_digest = payload.content_digest
    row.effective_at = payload.effective_at
    row.reacceptance_required = payload.reacceptance_required
    record_product_audit(
        db,
        event_type="platform.terms.document_updated",
        subject_type="terms_document",
        subject_id=row.id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={"document_type": document_type, "version": version, "status": payload.status},
    )
    db.commit()
    return {"document_type": document_type, "version": version, "status": row.status}
