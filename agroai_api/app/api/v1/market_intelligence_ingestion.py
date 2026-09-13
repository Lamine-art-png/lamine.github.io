"""Governed enterprise input surface for Market Intelligence.

These endpoints accept customer-owned commercial facts. They never infer an
organization from request payloads and never label customer-entered values as
live exchange data.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.api.v1.market_intelligence import enforce_market_intelligence_release
from app.db.base import get_db
from app.models.market_intelligence import MarketContractPosition, MarketObservation, MarketPosition

router = APIRouter(
    prefix="/market-intelligence",
    tags=["market-intelligence"],
    dependencies=[Depends(enforce_market_intelligence_release)],
)

WRITE_ROLES = {"owner", "admin", "operator", "analyst"}
SOURCE_STATES = {"LIVE", "DELAYED", "DEMO", "STALE", "UNAVAILABLE", "NOT_CONFIGURED", "MANUAL"}
MARKET_STRUCTURES = {"physical", "futures", "hybrid"}


def _scope(ctx: AuthContext) -> str:
    if ctx.organization is None or ctx.membership is None:
        raise HTTPException(status_code=403, detail="Organization membership required")
    if str(ctx.membership.role or "").lower() not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail={"code": "market_intelligence_read_only", "message": "This role has read-only Market Intelligence access."})
    return str(ctx.organization.id)


def _currency(value: str) -> str:
    code = str(value or "").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency must be a 3-letter ISO code")
    return code


class PositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    commodity: str = Field(min_length=1, max_length=120)
    season: str = Field(min_length=1, max_length=80)
    country_code: str = Field(min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=160)
    market_structure: Literal["physical", "futures", "hybrid"] = "physical"
    local_currency: str = Field(min_length=3, max_length=3)
    reporting_currency: str = Field(min_length=3, max_length=3)
    quantity_unit: str = Field(min_length=1, max_length=40)
    expected_production: Decimal = Field(ge=0)
    inventory_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    production_cost_per_unit: Decimal | None = Field(default=None, ge=0)
    current_realizable_price: Decimal | None = Field(default=None, ge=0)
    price_currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate_to_reporting: Decimal | None = Field(default=None, gt=0)
    freight_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    storage_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    workspace_id: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: str) -> str:
        code = value.strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueError("country_code must be ISO-3166 alpha-2")
        return code

    @field_validator("local_currency", "reporting_currency", "price_currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return _currency(value) if value else value


@router.post("/positions", status_code=status.HTTP_201_CREATED)
def create_position(payload: PositionInput, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = _scope(ctx)
    existing = db.query(MarketPosition).filter(MarketPosition.organization_id == org_id, MarketPosition.position_key == payload.position_key).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "position_key_exists", "message": "A market position already uses this key."})
    row = MarketPosition(
        id=str(uuid.uuid4()), organization_id=org_id, workspace_id=payload.workspace_id,
        position_key=payload.position_key, name=payload.name, commodity=payload.commodity.strip().lower(), season=payload.season,
        country_code=payload.country_code, region=payload.region, market_structure=payload.market_structure,
        local_currency=payload.local_currency, reporting_currency=payload.reporting_currency, quantity_unit=payload.quantity_unit,
        expected_production=payload.expected_production, inventory_quantity=payload.inventory_quantity,
        production_cost_per_unit=payload.production_cost_per_unit, current_realizable_price=payload.current_realizable_price,
        price_currency=payload.price_currency or payload.local_currency, fx_rate_to_reporting=payload.fx_rate_to_reporting,
        freight_per_unit=payload.freight_per_unit, storage_per_unit=payload.storage_per_unit,
        metadata_json={**payload.metadata, "input_source": "customer_structured_input"},
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "position_key": row.position_key, "status": "created"}


class ContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: str = Field(min_length=1, max_length=120)
    contract_code: str = Field(min_length=1, max_length=160)
    buyer: str | None = Field(default=None, max_length=240)
    quantity: Decimal = Field(gt=0)
    quantity_unit: str = Field(min_length=1, max_length=40)
    price: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    fx_rate_to_reporting: Decimal | None = Field(default=None, gt=0)
    delivery_start: datetime | None = None
    delivery_end: datetime | None = None
    delivery_location: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return _currency(value)


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
def create_contract(payload: ContractInput, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = _scope(ctx)
    position = db.query(MarketPosition).filter(MarketPosition.id == payload.position_id, MarketPosition.organization_id == org_id).first()
    if position is None:
        raise HTTPException(status_code=404, detail="Market position not found")
    existing = db.query(MarketContractPosition).filter(MarketContractPosition.organization_id == org_id, MarketContractPosition.contract_code == payload.contract_code).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "contract_code_exists", "message": "A commercial contract already uses this code."})
    if payload.delivery_start and payload.delivery_end and payload.delivery_end < payload.delivery_start:
        raise HTTPException(status_code=422, detail={"code": "invalid_delivery_window", "message": "delivery_end must not precede delivery_start"})
    row = MarketContractPosition(
        id=str(uuid.uuid4()), organization_id=org_id, position_id=position.id, contract_code=payload.contract_code,
        buyer=payload.buyer, status="active", quantity=payload.quantity, quantity_unit=payload.quantity_unit,
        price=payload.price, currency=payload.currency, fx_rate_to_reporting=payload.fx_rate_to_reporting,
        delivery_start=payload.delivery_start, delivery_end=payload.delivery_end, delivery_location=payload.delivery_location,
        metadata_json={**payload.metadata, "input_source": "customer_structured_input"},
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "contract_code": row.contract_code, "status": "created"}


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: str | None = Field(default=None, max_length=120)
    evidence_id: str = Field(min_length=1, max_length=200)
    observation_type: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=160)
    source_name: str = Field(min_length=1, max_length=240)
    source_status: str = Field(default="MANUAL", max_length=32)
    value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    observed_at: datetime
    delay_minutes: Decimal | None = Field(default=None, ge=0)
    quality: dict[str, Any] = Field(default_factory=dict)
    licensing: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_status")
    @classmethod
    def validate_state(cls, value: str) -> str:
        state = value.strip().upper()
        if state not in SOURCE_STATES:
            raise ValueError(f"source_status must be one of {sorted(SOURCE_STATES)}")
        return state

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return _currency(value) if value else value


@router.post("/observations", status_code=status.HTTP_201_CREATED)
def create_observation(payload: ObservationInput, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = _scope(ctx)
    if payload.position_id:
        exists = db.query(MarketPosition.id).filter(MarketPosition.id == payload.position_id, MarketPosition.organization_id == org_id).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Market position not found")
    duplicate = db.query(MarketObservation.id).filter(MarketObservation.organization_id == org_id, MarketObservation.evidence_id == payload.evidence_id).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail={"code": "evidence_id_exists", "message": "This evidence id has already been ingested."})
    # Client/customer input can carry a provider name for provenance, but it can
    # never grant itself LIVE authority. Only a configured MarketDataProvider
    # adapter is allowed to emit LIVE after verified upstream retrieval.
    source_state = "MANUAL" if payload.source_status == "LIVE" else payload.source_status
    row = MarketObservation(
        id=str(uuid.uuid4()), organization_id=org_id, position_id=payload.position_id, evidence_id=payload.evidence_id,
        observation_type=payload.observation_type, provider=payload.provider, source_name=payload.source_name,
        source_status=source_state, value=payload.value, unit=payload.unit, currency=payload.currency,
        observed_at=payload.observed_at, retrieved_at=datetime.utcnow(), delay_minutes=payload.delay_minutes,
        quality_json=payload.quality, licensing_json=payload.licensing,
        metadata_json={**payload.metadata, "input_source": "customer_structured_input", "requested_source_status": payload.source_status},
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "evidence_id": row.evidence_id, "source_status": row.source_status, "status": "created"}
