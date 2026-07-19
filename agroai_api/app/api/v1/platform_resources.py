"""Intentional customer-facing Platform API resources."""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import get_db
from app.models.operational_records import DataSource, EvidenceRecord, GeneratedArtifact, IngestionJob, IntelligenceRun
from app.models.platform_api import ApiProject, PlatformApiUsageEvent
from app.models.platform_product import PlatformApiPlan, PlatformCreditReservation, PlatformRequestLog
from app.models.saas import ManagedEntity
from app.models.task_outbox import TaskOutbox
from app.platform_api.credits import commit_credits, release_credits, reserve_credits
from app.platform_api.deps import require_developer_control_plane, require_platform_api_principal
from app.platform_api.idempotency import begin_idempotent_operation, complete_idempotent_operation
from app.platform_api.jobs import PLATFORM_OPERATION_TASK_TYPE
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.restrictions import enforce_resource_access
from app.platform_api.sandbox import ensure_sandbox_state, reset_sandbox, sandbox_dataset
from app.platform_api.scopes import require_scopes
from app.services.object_storage import get_object_store, object_storage_configured

router = APIRouter(prefix="/platform", tags=["platform-resources"])


class FieldWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    external_id: str | None = Field(default=None, max_length=200)
    workspace_id: str | None = None
    crop: str | None = Field(default=None, max_length=120)
    area_hectares: float | None = Field(default=None, gt=0, le=10_000_000)
    boundary: dict | None = None
    metadata: dict = Field(default_factory=dict)

    @field_validator("boundary")
    @classmethod
    def valid_boundary(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        if value.get("type") not in {"Polygon", "MultiPolygon"} or not isinstance(value.get("coordinates"), list):
            raise ValueError("boundary must be GeoJSON Polygon or MultiPolygon")
        encoded = json.dumps(value, separators=(",", ":"))
        if len(encoded) > 250_000:
            raise ValueError("boundary is too large")
        return value

    @field_validator("metadata")
    @classmethod
    def safe_metadata(cls, value: dict) -> dict:
        encoded = json.dumps(value, default=str)
        if len(encoded) > 16_000:
            raise ValueError("metadata is too large")
        if any(str(key).lower() in {"secret", "password", "token", "authorization", "credential"} for key in value):
            raise ValueError("secret metadata is not accepted")
        return value


class FieldPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=200)
    crop: str | None = Field(default=None, max_length=120)
    boundary: dict | None = None
    metadata: dict | None = None

    @field_validator("boundary")
    @classmethod
    def valid_boundary(cls, value: dict | None) -> dict | None:
        return FieldWrite.valid_boundary(value)

    @field_validator("metadata")
    @classmethod
    def safe_metadata(cls, value: dict | None) -> dict | None:
        return FieldWrite.safe_metadata(value) if value is not None else None


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: str = Field(min_length=2, max_length=120)
    provider: str = Field(default="customer_upload", min_length=2, max_length=120)
    filename: str | None = Field(default=None, max_length=240)
    content_type: str | None = Field(default=None, max_length=160)
    content_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    metadata: dict = Field(default_factory=dict)


class UploadInitiate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=3, max_length=160)
    content_sha256: str = Field(pattern="^[a-f0-9]{64}$")


class ObservationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    type: str = Field(min_length=1, max_length=120)
    occurred_at: datetime
    value: Any
    unit: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=240)
    summary: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(default=1.0, ge=0, le=1)
    provenance: dict = Field(default_factory=dict)
    quality_flags: list[str] = Field(default_factory=list, max_length=30)


class ObservationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str | None = None
    observations: list[ObservationItem] = Field(min_length=1, max_length=1000)


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    objective: str = Field(default="agronomic_recommendation", min_length=2, max_length=200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    parameters: dict = Field(default_factory=dict)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=240)
    field_ids: list[str] = Field(default_factory=list, max_length=200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=500)
    report_type: str = Field(default="field_summary", max_length=120)


def _project(db: Session, principal: PlatformPrincipal) -> ApiProject:
    row = (
        db.query(ApiProject)
        .filter(
            ApiProject.id == principal.api_project_id,
            ApiProject.organization_id == principal.organization_id,
            ApiProject.status == "active",
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=401, detail={"code": "api_project_inactive"})
    return row


def _cursor(row: Any) -> str:
    payload = {"created_at": row.created_at.isoformat(), "id": row.id}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, str] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(payload["created_at"]), str(payload["id"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_cursor"}) from exc


def _page(rows: list[Any], limit: int, serializer) -> dict:
    selected = rows[:limit]
    return {
        "items": [serializer(row) for row in selected],
        "next_cursor": _cursor(selected[-1]) if len(rows) > limit and selected else None,
        "has_more": len(rows) > limit,
    }


def _field_public(row: ManagedEntity) -> dict:
    metadata = dict(row.metadata_json or {})
    return {
        "id": row.id,
        "external_id": row.external_id,
        "name": row.display_name,
        "status": row.status,
        "workspace_id": row.workspace_id,
        "crop": metadata.get("crop"),
        "area_hectares": metadata.get("area_hectares"),
        "boundary": metadata.get("boundary"),
        "metadata": metadata.get("customer_metadata") or {},
        "synthetic": bool(metadata.get("synthetic")),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _source_public(row: DataSource) -> dict:
    metadata = dict(row.metadata_json or {})
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "source_type": row.source_type,
        "provider": row.provider,
        "filename": row.filename,
        "content_type": row.content_type,
        "status": row.status,
        "content_sha256": row.content_sha256,
        "object_size_bytes": row.object_size_bytes,
        "metadata": metadata.get("customer_metadata") or {},
        "synthetic": bool(metadata.get("synthetic")),
        "created_at": row.created_at.isoformat(),
    }


def _job_public(row: IngestionJob) -> dict:
    return {
        "id": row.id,
        "job_type": row.job_type,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "safe_error_code": row.error if row.error and len(row.error) < 120 else None,
        "output": dict(row.output_json or {}),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _logical_id(idempotency_key: str | None, principal: PlatformPrincipal) -> str:
    return idempotency_key or principal.request_id or str(uuid.uuid4())


def _create_job(
    db: Session,
    *,
    principal: PlatformPrincipal,
    job_type: str,
    payload: dict,
    idempotency_key: str,
    source_id: str | None = None,
) -> IngestionJob:
    digest = hashlib.sha256(
        f"{principal.organization_id}|{principal.api_project_id}|{job_type}|{idempotency_key}".encode()
    ).hexdigest()
    existing = (
        db.query(IngestionJob)
        .filter(IngestionJob.tenant_id == principal.organization_id, IngestionJob.idempotency_key == digest)
        .first()
    )
    if existing:
        return existing
    row = IngestionJob(
        tenant_id=principal.organization_id,
        workspace_id=principal.workspace_id,
        data_source_id=source_id,
        job_type=job_type,
        status="queued",
        input_json={**payload, "api_project_id": principal.api_project_id, "synthetic": principal.environment == "test"},
        output_json={},
        idempotency_key=digest,
        attempt_count=0,
        max_attempts=int(settings.TASK_QUEUE_MAX_ATTEMPTS),
    )
    db.add(row)
    db.flush()
    db.add(
        TaskOutbox(
            job_id=row.id,
            tenant_id=principal.organization_id,
            task_type=PLATFORM_OPERATION_TASK_TYPE,
            payload_json={"job_id": row.id},
            status="pending",
        )
    )
    return row


@router.get("/fields")
def list_fields(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"fields:read"})
    project = _project(db, principal)
    query = db.query(ManagedEntity).filter(
        ManagedEntity.organization_id == principal.organization_id,
        ManagedEntity.entity_type == "platform_field",
        ManagedEntity.metadata_json["api_project_id"].as_string() == principal.api_project_id,
    )
    if principal.workspace_id:
        query = query.filter(ManagedEntity.workspace_id == principal.workspace_id)
    if status_filter:
        query = query.filter(ManagedEntity.status == status_filter)
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, row_id = decoded
        query = query.filter((ManagedEntity.created_at < created_at) | ((ManagedEntity.created_at == created_at) & (ManagedEntity.id < row_id)))
    rows = query.order_by(ManagedEntity.created_at.desc(), ManagedEntity.id.desc()).limit(limit + 1).all()
    if project.environment == "test" and not rows:
        dataset = sandbox_dataset(project)
        return {"items": dataset["fields"][:limit], "next_cursor": None, "has_more": False, "synthetic": True}
    visible = []
    for row in rows:
        try:
            enforce_resource_access(principal, resource_id=row.id, resource_type="field")
        except HTTPException:
            continue
        visible.append(row)
    return _page(visible, limit, _field_public)


@router.post("/fields", status_code=status.HTTP_201_CREATED)
def create_field(
    payload: FieldWrite,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"fields:write"})
    project = _project(db, principal)
    if payload.workspace_id and payload.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=403, detail={"code": "workspace_restricted"})
    idem, replay = begin_idempotent_operation(db, principal=principal, operation="fields.create", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    reservation = reserve_credits(db, principal=principal, operation_id="field_creation", logical_operation_id=idempotency_key)
    row = ManagedEntity(
        organization_id=principal.organization_id,
        workspace_id=principal.workspace_id,
        entity_type="platform_field",
        external_id=payload.external_id,
        display_name=payload.name,
        status="active",
        metadata_json={
            "crop": payload.crop,
            "area_hectares": payload.area_hectares,
            "boundary": payload.boundary,
            "customer_metadata": payload.metadata,
            "api_project_id": project.id,
            "synthetic": project.environment == "test",
        },
    )
    db.add(row)
    db.flush()
    body = {"field": _field_public(row)}
    complete_idempotent_operation(idem, response_status=201, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=201)
    db.commit()
    response.headers["Location"] = f"/v1/platform/fields/{row.id}"
    return body


@router.get("/fields/{field_id}")
def get_field(
    field_id: str,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"fields:read"})
    enforce_resource_access(principal, resource_id=field_id, resource_type="field")
    project = _project(db, principal)
    row = (
        db.query(ManagedEntity)
        .filter(
            ManagedEntity.id == field_id,
            ManagedEntity.organization_id == principal.organization_id,
            ManagedEntity.entity_type == "platform_field",
            ManagedEntity.metadata_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row:
        return {"field": _field_public(row)}
    if project.environment == "test":
        match = next((item for item in sandbox_dataset(project)["fields"] if item["id"] == field_id), None)
        if match:
            return {"field": match}
    raise HTTPException(status_code=404, detail="Not found")


@router.patch("/fields/{field_id}")
def update_field(
    field_id: str,
    payload: FieldPatch,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"fields:write"})
    enforce_resource_access(principal, resource_id=field_id, resource_type="field")
    row = (
        db.query(ManagedEntity)
        .filter(
            ManagedEntity.id == field_id,
            ManagedEntity.organization_id == principal.organization_id,
            ManagedEntity.entity_type == "platform_field",
            ManagedEntity.metadata_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    idem, replay = begin_idempotent_operation(db, principal=principal, operation=f"fields.update:{field_id}", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    reservation = reserve_credits(db, principal=principal, operation_id="metadata_write", logical_operation_id=idempotency_key)
    if payload.name is not None:
        row.display_name = payload.name
    metadata = dict(row.metadata_json or {})
    for key, value in {"crop": payload.crop, "boundary": payload.boundary, "customer_metadata": payload.metadata}.items():
        if value is not None:
            metadata[key] = value
    row.metadata_json = metadata
    row.updated_at = datetime.utcnow()
    body = {"field": _field_public(row)}
    complete_idempotent_operation(idem, response_status=200, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=200)
    db.commit()
    return body


@router.delete("/fields/{field_id}")
def archive_field(
    field_id: str,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"fields:write"})
    enforce_resource_access(principal, resource_id=field_id, resource_type="field")
    idem, replay = begin_idempotent_operation(
        db,
        principal=principal,
        operation=f"fields.archive:{field_id}",
        idempotency_key=idempotency_key,
        payload={"field_id": field_id},
    )
    if replay and idem and idem.response_json:
        return idem.response_json
    row = (
        db.query(ManagedEntity)
        .filter(
            ManagedEntity.id == field_id,
            ManagedEntity.organization_id == principal.organization_id,
            ManagedEntity.entity_type == "platform_field",
            ManagedEntity.metadata_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    reservation = reserve_credits(
        db,
        principal=principal,
        operation_id="metadata_write",
        logical_operation_id=idempotency_key,
    )
    row.status = "archived"
    row.updated_at = datetime.utcnow()
    body = {"status": "archived", "field_id": row.id}
    complete_idempotent_operation(idem, response_status=200, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=200)
    db.commit()
    return body


@router.post("/sources")
def create_source(
    payload: SourceCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"sources:write"})
    project = _project(db, principal)
    idem, replay = begin_idempotent_operation(db, principal=principal, operation="sources.create", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    reservation = reserve_credits(db, principal=principal, operation_id="metadata_write", logical_operation_id=idempotency_key)
    row = DataSource(
        tenant_id=principal.organization_id,
        workspace_id=principal.workspace_id,
        source_type=payload.source_type,
        provider=payload.provider,
        filename=payload.filename,
        content_type=payload.content_type,
        content_sha256=payload.content_sha256,
        metadata_json={"customer_metadata": payload.metadata, "api_project_id": project.id, "synthetic": project.environment == "test"},
        status="ready" if payload.filename is None else "registered",
    )
    db.add(row)
    db.flush()
    body = {"source": _source_public(row)}
    complete_idempotent_operation(idem, response_status=201, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=201)
    db.commit()
    return body


@router.post("/sources/uploads")
def initiate_upload(
    payload: UploadInitiate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"sources:write"})
    project = _project(db, principal)
    if not object_storage_configured():
        raise HTTPException(status_code=503, detail={"code": "durable_upload_storage_not_configured"})
    idem, replay = begin_idempotent_operation(db, principal=principal, operation="sources.upload.initiate", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    reservation = reserve_credits(db, principal=principal, operation_id="source_upload_initiation", logical_operation_id=idempotency_key)
    row = DataSource(
        tenant_id=principal.organization_id,
        workspace_id=principal.workspace_id,
        source_type="customer_upload",
        provider="direct_upload",
        filename=payload.filename,
        content_type=payload.content_type,
        content_sha256=payload.content_sha256,
        metadata_json={"api_project_id": project.id, "synthetic": project.environment == "test"},
        status="awaiting_upload",
    )
    db.add(row)
    db.flush()
    store = get_object_store()
    upload_url, storage_uri, required_headers = store.create_presigned_upload(
        tenant_id=principal.organization_id,
        connection_id=f"platform-project-{project.id}",
        filename=payload.filename,
        content_type=payload.content_type,
        expected_sha256=payload.content_sha256,
    )
    row.storage_path = storage_uri
    body = {
        "upload": {
            "id": row.id,
            "method": "PUT",
            "url": upload_url,
            "required_headers": {"content-type": payload.content_type, **required_headers},
            "expires_in_seconds": 900,
        },
        "source": _source_public(row),
    }
    complete_idempotent_operation(idem, response_status=201, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=201)
    db.commit()
    return body


@router.get("/sources")
def list_sources(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    provider: str | None = None,
    source_status: str | None = Query(default=None, alias="status"),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"sources:read"})
    query = db.query(DataSource).filter(
        DataSource.tenant_id == principal.organization_id,
        DataSource.metadata_json["api_project_id"].as_string() == principal.api_project_id,
    )
    if principal.workspace_id:
        query = query.filter(DataSource.workspace_id == principal.workspace_id)
    if provider:
        query = query.filter(DataSource.provider == provider)
    if source_status:
        query = query.filter(DataSource.status == source_status)
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, row_id = decoded
        query = query.filter(
            (DataSource.created_at < created_at)
            | ((DataSource.created_at == created_at) & (DataSource.id < row_id))
        )
    rows = query.order_by(DataSource.created_at.desc(), DataSource.id.desc()).limit(limit + 1).all()
    return _page(rows, limit, _source_public)


@router.get("/sources/{source_id}")
def get_source(
    source_id: str,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"sources:read"})
    enforce_resource_access(principal, resource_id=source_id, resource_type="source")
    row = (
        db.query(DataSource)
        .filter(
            DataSource.id == source_id,
            DataSource.tenant_id == principal.organization_id,
            DataSource.metadata_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {"source": _source_public(row)}


@router.post("/observations", status_code=status.HTTP_202_ACCEPTED)
def submit_observations(
    payload: ObservationBatch,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"observations:write"})
    _project(db, principal)
    for item in payload.observations:
        enforce_resource_access(principal, resource_id=item.field_id, resource_type="field")
    if payload.source_id:
        source = (
            db.query(DataSource)
            .filter(
                DataSource.id == payload.source_id,
                DataSource.tenant_id == principal.organization_id,
                DataSource.metadata_json["api_project_id"].as_string() == principal.api_project_id,
            )
            .first()
        )
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
    idem, replay = begin_idempotent_operation(db, principal=principal, operation="observations.ingest", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    reservation = reserve_credits(db, principal=principal, operation_id="observation_batch_processing", logical_operation_id=idempotency_key)
    job = _create_job(
        db,
        principal=principal,
        job_type="platform_observation_ingestion",
        payload={"observations": [item.model_dump(mode="json") for item in payload.observations]},
        idempotency_key=idempotency_key,
        source_id=payload.source_id,
    )
    body = {"job": _job_public(job)}
    complete_idempotent_operation(idem, response_status=202, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=202)
    db.commit()
    return body


@router.get("/observations")
def list_observations(
    field_id: str | None = None,
    observation_type: str | None = Query(default=None, alias="type"),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"observations:read"})
    project = _project(db, principal)
    if field_id:
        enforce_resource_access(principal, resource_id=field_id, resource_type="field")
    query = db.query(EvidenceRecord).filter(
        EvidenceRecord.tenant_id == principal.organization_id,
        EvidenceRecord.metadata_json["platform_api_project_id"].as_string() == principal.api_project_id,
    )
    if principal.workspace_id:
        query = query.filter(EvidenceRecord.workspace_id == principal.workspace_id)
    if field_id:
        query = query.filter(EvidenceRecord.field_id == field_id)
    if observation_type:
        query = query.filter(EvidenceRecord.evidence_type == observation_type)
    if start:
        query = query.filter(EvidenceRecord.occurred_at >= start)
    if end:
        query = query.filter(EvidenceRecord.occurred_at < end)
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, row_id = decoded
        query = query.filter(
            (EvidenceRecord.created_at < created_at)
            | ((EvidenceRecord.created_at == created_at) & (EvidenceRecord.id < row_id))
        )
    rows = query.order_by(EvidenceRecord.created_at.desc(), EvidenceRecord.id.desc()).limit(limit + 1).all()
    if project.environment == "test" and not rows:
        items = sandbox_dataset(project)["observations"]
        if field_id:
            items = [item for item in items if item["field_id"] == field_id]
        if observation_type:
            items = [item for item in items if item["type"] == observation_type]
        return {"items": items[:limit], "next_cursor": None, "has_more": len(items) > limit, "synthetic": True}

    def serialize(row: EvidenceRecord) -> dict:
        metadata = dict(row.metadata_json or {})
        return {
            "id": row.id,
            "field_id": row.field_id,
            "type": row.evidence_type,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "value": dict(row.value_json or {}).get("value"),
            "unit": row.units,
            "provenance": metadata.get("provenance") or {},
            "quality_flags": metadata.get("quality_flags") or [],
            "quality_status": row.quality_status,
            "synthetic": bool(metadata.get("synthetic")),
            "created_at": row.created_at.isoformat(),
        }

    return _page(rows, limit, serialize)


@router.post("/recommendations", status_code=status.HTTP_202_ACCEPTED)
def request_recommendation(
    payload: RecommendationRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"recommendations:write"})
    _project(db, principal)
    enforce_resource_access(principal, resource_id=payload.field_id, resource_type="field")
    idem, replay = begin_idempotent_operation(db, principal=principal, operation="recommendations.compute", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    reservation = reserve_credits(db, principal=principal, operation_id="recommendation_computation", logical_operation_id=idempotency_key)
    job = _create_job(
        db,
        principal=principal,
        job_type="platform_recommendation",
        payload=payload.model_dump(),
        idempotency_key=idempotency_key,
    )
    body = {"job": _job_public(job)}
    complete_idempotent_operation(idem, response_status=202, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=202)
    db.commit()
    return body


@router.get("/recommendations")
def list_recommendations(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"recommendations:read"})
    project = _project(db, principal)
    query = db.query(IntelligenceRun).filter(
        IntelligenceRun.tenant_id == principal.organization_id,
        IntelligenceRun.run_type == "platform_recommendation",
        IntelligenceRun.input_context_json["api_project_id"].as_string() == principal.api_project_id,
    )
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, row_id = decoded
        query = query.filter(
            (IntelligenceRun.created_at < created_at)
            | ((IntelligenceRun.created_at == created_at) & (IntelligenceRun.id < row_id))
        )
    rows = query.order_by(IntelligenceRun.created_at.desc(), IntelligenceRun.id.desc()).limit(limit + 1).all()
    if project.environment == "test" and not rows:
        return {"items": sandbox_dataset(project)["recommendations"], "next_cursor": None, "has_more": False, "synthetic": True}

    def serialize(row: IntelligenceRun) -> dict:
        return {
            "id": row.id,
            "status": row.status,
            "result": row.output_json or {},
            "evidence": row.citations_json or [],
            "provenance": row.provenance_json or {},
            "created_at": row.created_at.isoformat(),
        }

    return _page(rows, limit, serialize)


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(
    recommendation_id: str,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"recommendations:read"})
    project = _project(db, principal)
    row = (
        db.query(IntelligenceRun)
        .filter(
            IntelligenceRun.id == recommendation_id,
            IntelligenceRun.tenant_id == principal.organization_id,
            IntelligenceRun.run_type == "platform_recommendation",
            IntelligenceRun.input_context_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row:
        return {"recommendation": {"id": row.id, "status": row.status, "result": row.output_json or {}, "evidence": row.citations_json or [], "provenance": row.provenance_json or {}}}
    if project.environment == "test":
        item = next((item for item in sandbox_dataset(project)["recommendations"] if item["id"] == recommendation_id), None)
        if item:
            return {"recommendation": item}
    raise HTTPException(status_code=404, detail="Not found")


@router.post("/reports", status_code=status.HTTP_202_ACCEPTED)
def request_report(
    payload: ReportRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"reports:write"})
    _project(db, principal)
    for field_id in payload.field_ids:
        enforce_resource_access(principal, resource_id=field_id, resource_type="field")
    idem, replay = begin_idempotent_operation(db, principal=principal, operation="reports.generate", idempotency_key=idempotency_key, payload=payload.model_dump())
    if replay and idem and idem.response_json:
        return idem.response_json
    reservation = reserve_credits(db, principal=principal, operation_id="report_generation", logical_operation_id=idempotency_key)
    job = _create_job(db, principal=principal, job_type="platform_report", payload=payload.model_dump(), idempotency_key=idempotency_key)
    body = {"job": _job_public(job)}
    complete_idempotent_operation(idem, response_status=202, response_json=body)
    commit_credits(db, reservation, principal=principal, status_code=202)
    db.commit()
    return body


@router.get("/reports")
def list_reports(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"reports:read"})
    project = _project(db, principal)
    query = db.query(GeneratedArtifact).filter(
        GeneratedArtifact.tenant_id == principal.organization_id,
        GeneratedArtifact.artifact_type == "platform_report",
        GeneratedArtifact.metadata_json["platform_api_project_id"].as_string() == principal.api_project_id,
    )
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, row_id = decoded
        query = query.filter(
            (GeneratedArtifact.created_at < created_at)
            | ((GeneratedArtifact.created_at == created_at) & (GeneratedArtifact.id < row_id))
        )
    rows = query.order_by(GeneratedArtifact.created_at.desc(), GeneratedArtifact.id.desc()).limit(limit + 1).all()
    if project.environment == "test" and not rows:
        return {"items": sandbox_dataset(project)["reports"], "next_cursor": None, "has_more": False, "synthetic": True}

    def serialize(row: GeneratedArtifact) -> dict:
        return {
            "id": row.id,
            "title": row.title,
            "status": "ready",
            "content_type": row.content_type,
            "synthetic": bool((row.metadata_json or {}).get("synthetic")),
            "created_at": row.created_at.isoformat(),
        }

    return _page(rows, limit, serialize)


@router.get("/reports/{report_id}")
def get_report(
    report_id: str,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"reports:read"})
    row = (
        db.query(GeneratedArtifact)
        .filter(
            GeneratedArtifact.id == report_id,
            GeneratedArtifact.tenant_id == principal.organization_id,
            GeneratedArtifact.artifact_type == "platform_report",
            GeneratedArtifact.metadata_json["platform_api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "report": {
            "id": row.id,
            "title": row.title,
            "status": "ready",
            "content_type": row.content_type,
            "body": row.body_text,
            "download_url": f"/v1/platform/reports/{row.id}/download",
            "created_at": row.created_at.isoformat(),
        }
    }


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: str,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> Response:
    require_scopes(principal.scopes, {"reports:read"})
    row = (
        db.query(GeneratedArtifact)
        .filter(
            GeneratedArtifact.id == report_id,
            GeneratedArtifact.tenant_id == principal.organization_id,
            GeneratedArtifact.artifact_type == "platform_report",
            GeneratedArtifact.metadata_json["platform_api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row is None or row.body_text is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=row.body_text,
        media_type=row.content_type,
        headers={"Content-Disposition": f'attachment; filename="{row.filename.replace(chr(34), "")}"'},
    )


@router.get("/jobs")
def list_jobs(
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"jobs:read"})
    query = db.query(IngestionJob).filter(
        IngestionJob.tenant_id == principal.organization_id,
        IngestionJob.job_type.in_(["platform_observation_ingestion", "platform_recommendation", "platform_report"]),
        IngestionJob.input_json["api_project_id"].as_string() == principal.api_project_id,
    )
    if principal.workspace_id:
        query = query.filter(IngestionJob.workspace_id == principal.workspace_id)
    if job_status:
        query = query.filter(IngestionJob.status == job_status)
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, row_id = decoded
        query = query.filter(
            (IngestionJob.created_at < created_at)
            | ((IngestionJob.created_at == created_at) & (IngestionJob.id < row_id))
        )
    rows = query.order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc()).limit(limit + 1).all()
    return _page(rows, limit, _job_public)


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"jobs:read"})
    row = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == principal.organization_id,
            IngestionJob.input_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if row is None or row.job_type not in {"platform_observation_ingestion", "platform_recommendation", "platform_report"}:
        raise HTTPException(status_code=404, detail="Not found")
    return {"job": _job_public(row)}


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: str,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"jobs:read"})
    idem, replay = begin_idempotent_operation(
        db,
        principal=principal,
        operation=f"jobs.retry:{job_id}",
        idempotency_key=idempotency_key,
        payload={"job_id": job_id},
    )
    if replay and idem and idem.response_json:
        return idem.response_json
    row = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == principal.organization_id,
            IngestionJob.input_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .with_for_update()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    if row.status != "failed" or int(row.attempt_count or 0) >= int(row.max_attempts or 0):
        raise HTTPException(status_code=409, detail={"code": "job_not_retryable"})
    outbox = db.query(TaskOutbox).filter(TaskOutbox.job_id == row.id).first()
    if outbox is None:
        raise HTTPException(status_code=409, detail={"code": "job_outbox_missing"})
    row.status = "queued"
    row.error = None
    row.next_attempt_at = datetime.utcnow()
    outbox.status = "pending"
    outbox.next_attempt_at = datetime.utcnow()
    outbox.last_error = None
    body = {"job": _job_public(row)}
    complete_idempotent_operation(idem, response_status=200, response_json=body)
    db.commit()
    return body


@router.get("/usage")
def public_usage(
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"usage:read"})
    subscriptions = __import__("app.models.platform_product", fromlist=["PlatformApiSubscription"]).PlatformApiSubscription
    subscription = (
        db.query(subscriptions)
        .filter(subscriptions.organization_id == principal.organization_id, subscriptions.status_slot == "active")
        .first()
    )
    plan = db.get(PlatformApiPlan, subscription.plan_id) if subscription else None
    period_key = None
    used = reserved = 0
    if subscription:
        from app.platform_api.credits import billing_period

        period_key, _start, _end = billing_period(subscription)
        used = int(
            db.query(func.coalesce(func.sum(PlatformCreditReservation.committed_credits), 0))
            .filter(
                PlatformCreditReservation.organization_id == principal.organization_id,
                PlatformCreditReservation.billing_period_key == period_key,
                PlatformCreditReservation.state == "committed",
            )
            .scalar()
            or 0
        )
        reserved = int(
            db.query(func.coalesce(func.sum(PlatformCreditReservation.reserved_credits), 0))
            .filter(
                PlatformCreditReservation.organization_id == principal.organization_id,
                PlatformCreditReservation.billing_period_key == period_key,
                PlatformCreditReservation.state == "reserved",
            )
            .scalar()
            or 0
        )
    included = plan.included_credits if plan else None
    return {
        "plan": plan.plan_identifier if plan else None,
        "plan_status": plan.status if plan else None,
        "included_credits": included,
        "used_credits": used,
        "reserved_credits": reserved,
        "remaining_credits": None if included is None else max(0, int(included) - used - reserved),
        "overage_state": "enabled" if plan and plan.overages_allowed else "disabled",
        "billing_period_key": period_key,
        "project_limits": dict(plan.limits_json or {}) if plan else {},
    }


@router.get("/request-logs")
def request_logs(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(principal.scopes, {"request_logs:read"})
    effective_limit = min(limit, int(settings.PLATFORM_API_REQUEST_LOG_MAX_PAGE_SIZE))
    query = db.query(PlatformRequestLog).filter(
        PlatformRequestLog.organization_id == principal.organization_id,
        PlatformRequestLog.api_project_id == principal.api_project_id,
    )
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, row_id = decoded
        query = query.filter(
            (PlatformRequestLog.created_at < created_at)
            | ((PlatformRequestLog.created_at == created_at) & (PlatformRequestLog.id < row_id))
        )
    rows = (
        query.order_by(PlatformRequestLog.created_at.desc(), PlatformRequestLog.id.desc())
        .limit(effective_limit + 1)
        .all()
    )

    def serialize(row: PlatformRequestLog) -> dict:
        return {
            "request_id": row.request_id,
            "timestamp": row.created_at.isoformat(),
            "method": row.method,
            "operation_id": row.operation_id,
            "status_code": row.status_code,
            "latency_ms": row.latency_ms,
            "project_id": row.api_project_id,
            "environment": row.environment,
            "key_fingerprint": row.key_fingerprint,
            "usage_cost": row.usage_cost,
            "safe_error_code": row.safe_error_code,
        }

    return _page(rows, effective_limit, serialize)


@router.get("/developer/request-logs")
def portal_request_logs(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(PlatformRequestLog).filter(
        PlatformRequestLog.organization_id == ctx.organization.id,
    )
    if project_id:
        project = (
            db.query(ApiProject)
            .filter(
                ApiProject.id == project_id,
                ApiProject.organization_id == ctx.organization.id,
            )
            .first()
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Not found")
        query = query.filter(PlatformRequestLog.api_project_id == project.id)
    rows = (
        query.order_by(PlatformRequestLog.created_at.desc())
        .limit(min(limit, int(settings.PLATFORM_API_REQUEST_LOG_MAX_PAGE_SIZE)))
        .all()
    )
    return {
        "items": [
            {
                "request_id": row.request_id,
                "timestamp": row.created_at.isoformat(),
                "method": row.method,
                "operation_id": row.operation_id,
                "status_code": row.status_code,
                "latency_ms": row.latency_ms,
                "project_id": row.api_project_id,
                "environment": row.environment,
                "key_fingerprint": row.key_fingerprint,
                "usage_cost": row.usage_cost,
                "safe_error_code": row.safe_error_code,
            }
            for row in rows
        ],
        "next_cursor": None,
        "has_more": False,
    }


@router.get("/sandbox")
def get_sandbox(
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    require_scopes(principal.scopes, {"projects:read"})
    project = _project(db, principal)
    if project.environment != "test":
        raise HTTPException(status_code=403, detail={"code": "sandbox_test_project_required"})
    ensure_sandbox_state(db, project)
    db.commit()
    return sandbox_dataset(project)


@router.post("/developer/projects/{project_id}/sandbox/reset")
def portal_reset_sandbox(
    project_id: str,
    ctx=Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    project = (
        db.query(ApiProject)
        .filter(ApiProject.id == project_id, ApiProject.organization_id == ctx.organization.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Not found")
    row = reset_sandbox(db, project, user_id=ctx.user.id)
    db.commit()
    return {
        "status": "reset",
        "project_id": project.id,
        "fixture_version": row.fixture_version,
        "reset_counter": row.reset_counter,
        "synthetic": True,
    }
