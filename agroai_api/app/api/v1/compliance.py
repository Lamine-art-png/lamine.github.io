"""Feature-flagged California Compliance Pack endpoints."""
from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, Header, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field, field_validator

from app.compliance.constants import TRUTH_LABELS
from app.compliance import services
from app.compliance.fixtures import ORG_ID, VINEYARD_FIXTURE
from app.core.config import settings

router = APIRouter(prefix="/compliance", tags=["compliance"])


def _ensure_enabled() -> None:
    if not settings.CALIFORNIA_COMPLIANCE_PACK_ENABLED:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Compliance pack is not enabled")


def _org(x_organization_id: str | None) -> str | None:
    return x_organization_id


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
def get_status(x_organization_id: str | None = Header(default=None)) -> dict[str, Any]:
    _ensure_enabled()
    return services.status(_org(x_organization_id))


@router.get("/jurisdictions")
def get_jurisdictions(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    return services.list_jurisdictions(_org(x_organization_id))


@router.get("/assets/parcels")
def get_parcels(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    return services.list_assets("parcels", _org(x_organization_id))


@router.get("/assets/wells")
def get_wells(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    return services.list_assets("wells", _org(x_organization_id))


@router.get("/assets/meters")
def get_meters(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    return services.list_assets("meters", _org(x_organization_id))


@router.post("/measurements", status_code=201)
def create_measurement(payload: MeasurementIn, x_organization_id: str | None = Header(default=None)) -> dict[str, Any]:
    _ensure_enabled()
    try:
        return services.add_measurement(payload.model_dump(), _org(x_organization_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/measurements")
def get_measurements(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    return services.list_measurements(_org(x_organization_id))


@router.get("/reconciliation")
def get_reconciliation(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    return services.reconciliation(_org(x_organization_id))


@router.get("/water-budgets")
def get_water_budgets(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    return services.water_budget_status(_org(x_organization_id))


@router.get("/readiness")
def get_readiness(workflow_type: str = Query("gears_groundwater_extractor_readiness"), x_organization_id: str | None = Header(default=None)) -> dict[str, Any]:
    _ensure_enabled()
    return services.readiness(workflow_type, _org(x_organization_id))


@router.post("/evidence", status_code=201)
def create_evidence(payload: EvidenceIn, x_organization_id: str | None = Header(default=None)) -> dict[str, Any]:
    _ensure_enabled()
    try:
        return services.add_evidence(payload.model_dump(), _org(x_organization_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/audit-log")
def get_audit_log(x_organization_id: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _ensure_enabled()
    org = _org(x_organization_id) or ORG_ID
    return [row for row in VINEYARD_FIXTURE["audit_log"] if row["organization_id"] == org]


@router.post("/exports", status_code=201)
def create_export(payload: ExportIn, x_organization_id: str | None = Header(default=None)) -> dict[str, Any]:
    _ensure_enabled()
    return services.compose_export(payload.export_type, payload.workflow_type, _org(x_organization_id))


@router.get("/exports/{export_id}")
def get_export(export_id: str, x_organization_id: str | None = Header(default=None)) -> dict[str, Any]:
    _ensure_enabled()
    package = services.get_export(export_id, _org(x_organization_id))
    if not package:
        raise HTTPException(status_code=404, detail="Export package not found")
    return package
