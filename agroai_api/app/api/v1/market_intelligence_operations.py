"""Management and provider-refresh endpoints for Market Intelligence."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.models.market_intelligence import MarketContractPosition, MarketPosition
from app.services.market_data_providers import registry
from app.services.market_intelligence_refresh import refresh_organization_market_data, refresh_position_market_data

router = APIRouter()
WRITE_ROLES = {"owner", "admin", "operator", "analyst"}


def _org_id(ctx: AuthContext) -> str:
    if ctx.organization is None or ctx.membership is None:
        raise HTTPException(status_code=403, detail="Organization membership required")
    return str(ctx.organization.id)


def _require_write(ctx: AuthContext) -> str:
    org_id = _org_id(ctx)
    role = str(ctx.membership.role or "").strip().lower() if ctx.membership else "viewer"
    if role not in WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail={"code": "market_intelligence_read_only", "message": "This role has read-only Market Intelligence access."},
        )
    return org_id


def _position(db: Session, org_id: str, position_id: str) -> MarketPosition:
    row = db.query(MarketPosition).filter(
        MarketPosition.id == position_id,
        MarketPosition.organization_id == org_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Market position not found")
    return row


def _currency(value: str | None) -> str | None:
    if value is None:
        return None
    code = str(value).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency must be a 3-letter ISO code")
    return code


class PositionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    commodity: str | None = Field(default=None, min_length=1, max_length=120)
    season: str | None = Field(default=None, min_length=1, max_length=80)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=160)
    market_structure: Literal["physical", "futures", "hybrid"] | None = None
    local_currency: str | None = Field(default=None, min_length=3, max_length=3)
    reporting_currency: str | None = Field(default=None, min_length=3, max_length=3)
    quantity_unit: str | None = Field(default=None, min_length=1, max_length=40)
    expected_production: Decimal | None = Field(default=None, ge=0)
    inventory_quantity: Decimal | None = Field(default=None, ge=0)
    production_cost_per_unit: Decimal | None = Field(default=None, ge=0)
    current_realizable_price: Decimal | None = Field(default=None, ge=0)
    price_currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate_to_reporting: Decimal | None = Field(default=None, gt=0)
    freight_per_unit: Decimal | None = Field(default=None, ge=0)
    storage_per_unit: Decimal | None = Field(default=None, ge=0)
    status: Literal["active", "archived"] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator(
        "name", "commodity", "season", "country_code", "market_structure",
        "local_currency", "reporting_currency", "quantity_unit", "expected_production",
        "inventory_quantity", "freight_per_unit", "storage_per_unit", "status",
    )
    @classmethod
    def reject_null_for_required_columns(cls, value: Any) -> Any:
        # Patch fields are optional only so callers may omit them.  Supplying
        # JSON null for a database-required column must fail at validation
        # instead of reaching the database as an integrity error/500.
        if value is None:
            raise ValueError("field cannot be null")
        return value

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueError("country_code must be ISO-3166 alpha-2")
        return code

    @field_validator("local_currency", "reporting_currency", "price_currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return _currency(value)


@router.patch("/positions/{position_id}")
def patch_position(
    position_id: str,
    payload: PositionPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _require_write(ctx)
    row = _position(db, org_id, position_id)
    changes = payload.model_dump(exclude_unset=True)
    metadata = changes.pop("metadata", None)
    for field_name, value in changes.items():
        if isinstance(value, str) and field_name in {"name", "commodity", "season", "quantity_unit", "region"}:
            value = " ".join(value.strip().split())
        if field_name == "commodity" and isinstance(value, str):
            value = value.lower()
        setattr(row, field_name, value)
    if metadata is not None:
        current = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        row.metadata_json = {**current, **metadata, "input_source": current.get("input_source", "customer_structured_input")}
    db.commit()
    return {"id": row.id, "status": row.status, "updated": sorted([*changes.keys(), *(["metadata"] if metadata is not None else [])])}


@router.delete(
    "/positions/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def archive_position(
    position_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    org_id = _require_write(ctx)
    row = _position(db, org_id, position_id)
    row.status = "archived"
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ContractPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyer: str | None = Field(default=None, max_length=240)
    status: Literal["active", "priced", "committed", "cancelled", "fulfilled"] | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    quantity_unit: str | None = Field(default=None, min_length=1, max_length=40)
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate_to_reporting: Decimal | None = Field(default=None, gt=0)
    delivery_location: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] | None = None

    @field_validator("status", "quantity", "quantity_unit", "price", "currency")
    @classmethod
    def reject_null_for_required_columns(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return _currency(value)


@router.patch("/contracts/{contract_id}")
def patch_contract(
    contract_id: str,
    payload: ContractPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _require_write(ctx)
    row = db.query(MarketContractPosition).filter(
        MarketContractPosition.id == contract_id,
        MarketContractPosition.organization_id == org_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Market contract not found")
    changes = payload.model_dump(exclude_unset=True)
    metadata = changes.pop("metadata", None)
    for field_name, value in changes.items():
        setattr(row, field_name, value)
    if metadata is not None:
        current = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        row.metadata_json = {**current, **metadata}
    db.commit()
    return {"id": row.id, "status": row.status, "updated": sorted([*changes.keys(), *(["metadata"] if metadata is not None else [])])}


@router.delete(
    "/contracts/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_contract(
    contract_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    org_id = _require_write(ctx)
    row = db.query(MarketContractPosition).filter(
        MarketContractPosition.id == contract_id,
        MarketContractPosition.organization_id == org_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Market contract not found")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/providers")
async def provider_status(
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    _org_id(ctx)
    return {
        "providers": await registry.status(),
        "policy": {
            "verified_upstream_required_for_live": True,
            "customer_input_cannot_self_assign_live": True,
        },
    }


@router.post("/positions/{position_id}/refresh")
async def refresh_position(
    position_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _require_write(ctx)
    row = _position(db, org_id, position_id)
    return await refresh_position_market_data(db, row)


@router.post("/refresh")
async def refresh_organization(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _require_write(ctx)
    return await refresh_organization_market_data(db, org_id)
