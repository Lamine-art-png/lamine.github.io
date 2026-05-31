"""Feature-flagged global compliance kernel endpoints preserving California routes."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status as http_status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.compliance.constants import TRUTH_LABELS
from app.compliance.fixtures import ORG_ID
from app.compliance.repository import ComplianceContext, ComplianceRepository
from app.compliance import services
from app.compliance.storage import decode_export_content
from app.core.config import settings
from app.db.base import get_db
from app.services.api_key_service import APIKeyService

router = APIRouter(prefix="/compliance", tags=["compliance"])


def _ensure_enabled() -> None:
    if not settings.CALIFORNIA_COMPLIANCE_PACK_ENABLED:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Compliance pack is not enabled")


def get_compliance_repo(
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    x_compliance_demo_token: str | None = Header(default=None, alias="X-Compliance-Demo-Token"),
) -> ComplianceRepository:
    _ensure_enabled()
    demo_mode = bool(settings.COMPLIANCE_DEMO_FIXTURES_ENABLED)
    actor = "compliance-api"
    tenant_id = None
    if x_api_key:
        key = APIKeyService.verify_api_key(db, x_api_key)
        if not key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        tenant_id = key.tenant_id
        actor = key.name
        if x_organization_id and x_organization_id != tenant_id:
            raise HTTPException(status_code=403, detail="Organization header does not match authenticated tenant")
    elif demo_mode:
        if x_compliance_demo_token != settings.COMPLIANCE_DEMO_TOKEN:
            raise HTTPException(status_code=401, detail="Missing or invalid non-production demo compliance token")
        tenant_id = x_organization_id or ORG_ID
        actor = "non-production-demo-fixture"
    else:
        raise HTTPException(status_code=401, detail="Missing API key or authenticated compliance session")
    repo = ComplianceRepository(db, ComplianceContext(tenant_id=tenant_id, actor=actor, demo_mode=demo_mode))
    if demo_mode:
        repo.seed_demo_fixture_if_empty()
    return repo


class MeasurementIn(BaseModel):
    asset_type: str
    asset_id: str
    measurement_type: str
    value: float
    unit: str
    method: str
    truth_label: str
    source_system: str
    source_timestamp: str
    reporting_period: str
    quality_status: str = "pending_review"
    confidence: float | None = Field(default=None, ge=0, le=1)
    correction_lineage: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("truth_label")
    @classmethod
    def valid_truth_label(cls, value: str) -> str:
        if value not in TRUTH_LABELS:
            raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
        return value


class EvidenceIn(BaseModel):
    artifact_type: str
    file_ref: str
    truth_label: str = "reported"
    review_status: str = "pending_review"
    notes: str | None = None

    @field_validator("truth_label")
    @classmethod
    def valid_truth_label(cls, value: str) -> str:
        if value not in TRUTH_LABELS:
            raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
        return value


class ExportIn(BaseModel):
    export_type: Literal["json", "csv", "xlsx", "pdf"] = "json"
    workflow_type: str = "gears_groundwater_extractor_readiness"


@router.get("/status")
def get_status(repo: ComplianceRepository = Depends(get_compliance_repo)) -> dict[str, Any]:
    return services.status_from_repository(repo)


@router.get("/jurisdictions")
def get_jurisdictions(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return repo.jurisdictions()


@router.get("/assets/parcels")
def get_parcels(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return repo.parcels()


@router.get("/assets/wells")
def get_wells(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return repo.wells()


@router.get("/assets/meters")
def get_meters(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return repo.meters()


@router.post("/measurements", status_code=201)
def create_measurement(payload: MeasurementIn, repo: ComplianceRepository = Depends(get_compliance_repo)) -> dict[str, Any]:
    try:
        return repo.add_measurement(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/measurements")
def get_measurements(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return repo.measurements()


@router.get("/reconciliation")
def get_reconciliation(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return repo.reconciliation()


@router.get("/water-budgets")
def get_water_budgets(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return services.water_budget_status_from_records(repo.water_budgets())


@router.get("/readiness")
def get_readiness(workflow_type: str = Query("gears_groundwater_extractor_readiness"), repo: ComplianceRepository = Depends(get_compliance_repo)) -> dict[str, Any]:
    return services.readiness_from_repository(repo, workflow_type)


@router.post("/evidence", status_code=201)
def create_evidence(payload: EvidenceIn, repo: ComplianceRepository = Depends(get_compliance_repo)) -> dict[str, Any]:
    try:
        return repo.add_evidence(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/audit-log")
def get_audit_log(repo: ComplianceRepository = Depends(get_compliance_repo)) -> list[dict[str, Any]]:
    return repo.audit_log()


@router.post("/exports", status_code=201)
def create_export(payload: ExportIn, repo: ComplianceRepository = Depends(get_compliance_repo)) -> dict[str, Any]:
    return services.compose_export_from_repository(repo, payload.export_type, payload.workflow_type)


@router.get("/exports/{export_id}")
def get_export(export_id: str, repo: ComplianceRepository = Depends(get_compliance_repo)) -> dict[str, Any]:
    package = repo.get_export(export_id)
    if not package:
        raise HTTPException(status_code=404, detail="Export package not found")
    return package


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, repo: ComplianceRepository = Depends(get_compliance_repo)) -> Response:
    package = repo.get_export(export_id)
    if not package:
        raise HTTPException(status_code=404, detail="Export package not found")
    try:
        content = decode_export_content(package)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=package.get("mime_type") or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={package.get('file_name') or export_id}"},
    )
