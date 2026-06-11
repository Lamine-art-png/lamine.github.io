"""Feature-flagged compliance kernel endpoints."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.compliance import services
from app.compliance.constants import APPROVED_FIXTURE_TENANT_ID, TRUTH_LABELS
from app.compliance.repository import ComplianceRepository
from app.core.config import settings
from app.db.base import get_db
from app.services.api_key_service import APIKeyService

router = APIRouter(prefix="/compliance", tags=["compliance"])


def _ensure_enabled() -> None:
    if not settings.CALIFORNIA_COMPLIANCE_PACK_ENABLED:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Compliance kernel is not enabled")


class ComplianceContext:
    def __init__(self, repo: ComplianceRepository, demo_mode: bool = False):
        self.repo = repo
        self.demo_mode = demo_mode


def _reject_organization_mismatch(header_value: str | None, tenant_id: str) -> None:
    if header_value and header_value != tenant_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="X-Organization-Id does not match authenticated compliance tenant",
        )


def _context(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_compliance_demo_token: str | None = Header(default=None, alias="X-Compliance-Demo-Token"),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
) -> ComplianceContext:
    _ensure_enabled()
    if settings.COMPLIANCE_DEMO_FIXTURES_ENABLED:
        expected = settings.COMPLIANCE_DEMO_TOKEN
        if expected and x_compliance_demo_token == expected:
            if settings.COMPLIANCE_DEMO_TENANT_ID != APPROVED_FIXTURE_TENANT_ID:
                raise HTTPException(status_code=500, detail="Compliance demo tenant is not approved")
            _reject_organization_mismatch(x_organization_id, APPROVED_FIXTURE_TENANT_ID)
            repo = ComplianceRepository(db, APPROVED_FIXTURE_TENANT_ID)
            repo.seed_demo_fixtures()
            return ComplianceContext(repo, demo_mode=True)

    if x_api_key:
        api_key = APIKeyService.verify_api_key(db, x_api_key)
        if api_key:
            tenant_id = str(api_key.tenant_id)
            _reject_organization_mismatch(x_organization_id, tenant_id)
            return ComplianceContext(ComplianceRepository(db, tenant_id))
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Invalid compliance API key")

    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail="Compliance requires a verified server-side API key or explicit non-production demo token",
    )


class MeasurementIn(BaseModel):
    asset_type: Literal["parcel", "well", "meter"]
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


class ReadinessSnapshotIn(BaseModel):
    workflow_type: str = "gears_groundwater_extractor_readiness"


def _raise_value(exc: ValueError) -> None:
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/status")
def get_status(workflow_type: str = Query("gears_groundwater_extractor_readiness"), context: ComplianceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return services.status(context.repo, workflow_type, demo_mode=context.demo_mode)
    except ValueError as exc:
        _raise_value(exc)


@router.get("/jurisdictions")
def get_jurisdictions(context: ComplianceContext = Depends(_context)) -> list[dict[str, Any]]:
    return services.list_jurisdictions(context.repo)


@router.get("/assets/parcels")
def get_parcels(context: ComplianceContext = Depends(_context)) -> list[dict[str, Any]]:
    return services.list_assets(context.repo, "parcels")


@router.get("/assets/wells")
def get_wells(context: ComplianceContext = Depends(_context)) -> list[dict[str, Any]]:
    return services.list_assets(context.repo, "wells")


@router.get("/assets/meters")
def get_meters(context: ComplianceContext = Depends(_context)) -> list[dict[str, Any]]:
    return services.list_assets(context.repo, "meters")


@router.post("/measurements", status_code=201)
def create_measurement(payload: MeasurementIn, context: ComplianceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return services.add_measurement(context.repo, payload.model_dump())
    except ValueError as exc:
        _raise_value(exc)


@router.get("/measurements")
def get_measurements(context: ComplianceContext = Depends(_context)) -> list[dict[str, Any]]:
    return services.list_measurements(context.repo)


@router.get("/reconciliation")
def get_reconciliation(context: ComplianceContext = Depends(_context)) -> list[dict[str, Any]]:
    return services.reconciliation(context.repo)


@router.get("/water-budgets")
def get_water_budgets(context: ComplianceContext = Depends(_context)) -> list[dict[str, Any]]:
    try:
        return services.water_budget_status(context.repo)
    except ValueError as exc:
        _raise_value(exc)


@router.get("/readiness")
def get_readiness(workflow_type: str = Query("gears_groundwater_extractor_readiness"), context: ComplianceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return services.readiness(context.repo, workflow_type)
    except ValueError as exc:
        _raise_value(exc)


@router.post("/readiness/snapshots", status_code=201)
def create_readiness_snapshot(
    payload: ReadinessSnapshotIn | None = Body(default=None),
    context: ComplianceContext = Depends(_context),
) -> dict[str, Any]:
    try:
        workflow_type = payload.workflow_type if payload else "gears_groundwater_extractor_readiness"
        return services.create_readiness_snapshot(context.repo, workflow_type)
    except ValueError as exc:
        _raise_value(exc)


@router.post("/evidence", status_code=201)
def create_evidence(payload: EvidenceIn, context: ComplianceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return services.add_evidence(context.repo, payload.model_dump())
    except ValueError as exc:
        _raise_value(exc)


@router.post("/exports", status_code=201)
def create_export(payload: ExportIn, context: ComplianceContext = Depends(_context)) -> dict[str, Any]:
    if settings.COMPLIANCE_OBJECT_STORAGE_BACKEND != "disabled":
        raise HTTPException(status_code=501, detail="Compliance object storage backend is not implemented")
    try:
        return services.compose_export(
            context.repo,
            payload.export_type,
            payload.workflow_type,
            storage_backend=settings.COMPLIANCE_OBJECT_STORAGE_BACKEND,
        )
    except ValueError as exc:
        _raise_value(exc)


@router.get("/exports/{export_id}")
def get_export(export_id: str, context: ComplianceContext = Depends(_context)) -> dict[str, Any]:
    package = services.get_export(context.repo, export_id)
    if not package:
        raise HTTPException(status_code=404, detail="Export package not found")
    return package
