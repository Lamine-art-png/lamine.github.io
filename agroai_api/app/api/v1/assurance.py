"""Assurance Passport API routes."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.assurance.repository import AssuranceRepository
from app.assurance.rule_packs import DEFAULT_RULE_PACKS
from app.db.base import get_db
from app.services.api_key_service import APIKeyService

router = APIRouter(prefix="/assurance", tags=["assurance"])


class AssuranceContext:
    def __init__(self, repo: AssuranceRepository):
        self.repo = repo


def _reject_org_mismatch(header_value: str | None, tenant_id: str) -> None:
    if header_value and header_value != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="X-Organization-Id does not match authenticated assurance tenant")


def _context(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
) -> AssuranceContext:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assurance requires a verified server-side API key")
    api_key = APIKeyService.verify_api_key(db, x_api_key)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid assurance API key")
    _reject_org_mismatch(x_organization_id, str(api_key.tenant_id))
    repo = AssuranceRepository(db, str(api_key.tenant_id))
    repo.ensure_rule_packs()
    return AssuranceContext(repo)


class PassportIn(BaseModel):
    farm_name: str
    farm_location: str | None = None
    crop: str | None = None
    season: str | None = None
    reporting_period: str | None = None
    jurisdiction_id: str | None = None
    parcel_ids: list[str] = Field(default_factory=list)
    rule_pack_ids: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceIn(BaseModel):
    evidence_type: str
    proof_domain: str | None = None
    file_ref: str
    filename: str | None = None
    content_type: str | None = None
    checksum: str | None = None
    truth_label: str = "reported"
    review_status: str = "pending_review"
    source_system: str = "uploaded"
    compliance_evidence_id: str | None = None
    workbench_artifact_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("truth_label")
    @classmethod
    def _truth_label(cls, value: str) -> str:
        if value not in {"measured", "reported", "estimated", "calculated", "AI-inferred"}:
            raise ValueError("unsupported truth_label")
        return value


class InputApplicationIn(BaseModel):
    application_type: Literal["input", "pesticide", "fertilizer"] = "input"
    applied_at: str | None = None
    block_id: str | None = None
    parcel_id: str | None = None
    product_name: str
    quantity: float | None = None
    unit: str | None = None
    operator: str | None = None
    truth_label: str = "reported"
    evidence_artifact_id: str | None = None
    active_ingredient: str | None = None
    target_pest: str | None = None
    reentry_interval_hours: float | None = None
    preharvest_interval_days: float | None = None
    label_reference: str | None = None
    nutrient_profile: dict[str, Any] = Field(default_factory=dict)
    nitrogen_kg: float | None = None
    phosphorus_kg: float | None = None
    potassium_kg: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HarvestLotIn(BaseModel):
    lot_code: str
    crop: str | None = None
    variety: str | None = None
    harvested_at: str | None = None
    block_id: str | None = None
    parcel_id: str | None = None
    quantity: float | None = None
    unit: str | None = None
    destination: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceabilityEventIn(BaseModel):
    harvest_lot_id: str | None = None
    event_type: str
    occurred_at: str | None = None
    location: str | None = None
    actor: str | None = None
    evidence_artifact_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ExportIn(BaseModel):
    export_type: Literal["pdf"] = "pdf"


@router.get("/rule-packs")
def rule_packs(_: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    return {"rule_packs": DEFAULT_RULE_PACKS}


@router.post("/passports", status_code=201)
def create_passport(payload: PassportIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.create_passport(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/passports/{passport_id}")
def get_passport(passport_id: str, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.get_passport(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@router.post("/passports/{passport_id}/evidence", status_code=201)
def add_evidence(passport_id: str, payload: EvidenceIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_evidence(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/passports/{passport_id}/input-applications", status_code=201)
def add_input_application(passport_id: str, payload: InputApplicationIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_input_application(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/passports/{passport_id}/harvest-lots", status_code=201)
def add_harvest_lot(passport_id: str, payload: HarvestLotIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_harvest_lot(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@router.post("/passports/{passport_id}/traceability-events", status_code=201)
def add_traceability_event(passport_id: str, payload: TraceabilityEventIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_traceability_event(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/passports/{passport_id}/readiness")
def readiness(passport_id: str, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.readiness(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@router.post("/passports/{passport_id}/exports", status_code=201)
def create_export(passport_id: str, payload: ExportIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    if payload.export_type != "pdf":
        raise HTTPException(status_code=422, detail="Only PDF Assurance Passport export is available in this MVP")
    try:
        return context.repo.export_pdf(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc

