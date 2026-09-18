"""Management and provider-refresh endpoints for Market Intelligence."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.models.market_intelligence import MarketContractPosition, MarketObservation, MarketPosition
from app.services.market_data_providers import registry
from app.services.market_intelligence import MarketCalculationError, convert_price_per_unit, convert_quantity
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

    if "commodity" in changes:
        proposed_commodity = " ".join(str(changes["commodity"]).strip().split()).lower()
        if proposed_commodity != str(row.commodity or "").strip().lower():
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "commodity_change_requires_new_position",
                    "message": "Changing commodity would reinterpret existing quantities and prices. Create a new position and archive the old one.",
                },
            )
    if "quantity_unit" in changes:
        proposed_unit = " ".join(str(changes["quantity_unit"]).strip().split())
        if proposed_unit.lower() != str(row.quantity_unit or "").strip().lower():
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "quantity_unit_change_requires_restatement",
                    "message": "Changing the position quantity unit requires restating production, inventory, costs, prices and contracts. Create a new position instead.",
                },
            )

    reporting_changed = (
        "reporting_currency" in changes
        and str(changes["reporting_currency"]).upper() != str(row.reporting_currency or "").upper()
    )
    price_currency_changed = (
        "price_currency" in changes
        and changes["price_currency"] is not None
        and str(changes["price_currency"]).upper() != str(row.price_currency or "").upper()
    )

    for field_name, value in changes.items():
        if isinstance(value, str) and field_name in {"name", "commodity", "season", "quantity_unit", "region"}:
            value = " ".join(value.strip().split())
        if field_name == "commodity" and isinstance(value, str):
            value = value.lower()
        setattr(row, field_name, value)

    if reporting_changed:
        # Every stored contract FX rate is quoted to the previous reporting
        # currency. Clear it immediately so no request can reuse the old quote.
        contracts = db.query(MarketContractPosition).filter(
            MarketContractPosition.organization_id == org_id,
            MarketContractPosition.position_id == row.id,
        ).all()
        for contract in contracts:
            contract.fx_rate_to_reporting = None

    if reporting_changed or price_currency_changed:
        reporting = str(row.reporting_currency or "").upper()
        price_currency = str(row.price_currency or row.local_currency or reporting).upper()
        if price_currency == reporting:
            row.fx_rate_to_reporting = None
        elif "fx_rate_to_reporting" not in changes:
            row.fx_rate_to_reporting = None

    if metadata is not None:
        current = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        row.metadata_json = {**current, **metadata, "input_source": current.get("input_source", "customer_structured_input")}

    if "current_realizable_price" in changes and changes["current_realizable_price"] is not None:
        price_currency = str(row.price_currency or row.local_currency or row.reporting_currency).upper()
        db.add(MarketObservation(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            position_id=row.id,
            evidence_id=f"manual-price-{row.id}-{uuid.uuid4().hex[:12]}",
            observation_type="cash_price",
            provider="customer",
            source_name="Customer managed market price",
            source_status="MANUAL",
            value=row.current_realizable_price,
            unit=f"{price_currency}/{row.quantity_unit}",
            currency=price_currency,
            observed_at=datetime.utcnow(),
            retrieved_at=datetime.utcnow(),
            quality_json={"grade": "customer_entered"},
            licensing_json={"display_allowed": True},
            metadata_json={"input_source": "customer_structured_input", "entry_surface": "position_patch"},
        ))

    db.commit()
    updated = [*changes.keys(), *(["metadata"] if metadata is not None else [])]
    if reporting_changed:
        updated.append("contract_fx_rate_to_reporting")
    return {"id": row.id, "status": row.status, "updated": sorted(set(updated))}


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
    position = _position(db, org_id, row.position_id)

    if "quantity_unit" in changes and str(changes["quantity_unit"]).strip().lower() != str(row.quantity_unit or "").strip().lower():
        if "quantity" not in changes or "price" not in changes:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "contract_unit_change_requires_restatement",
                    "message": "Changing a contract quantity unit requires restating both quantity and price in the same request.",
                },
            )

    proposed_quantity = changes.get("quantity", row.quantity)
    proposed_unit = changes.get("quantity_unit", row.quantity_unit)
    proposed_price = changes.get("price", row.price)
    try:
        convert_quantity(proposed_quantity, proposed_unit, position.quantity_unit, position.commodity)
        convert_price_per_unit(proposed_price, proposed_unit, position.quantity_unit, position.commodity)
    except MarketCalculationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "contract_unit_incompatible", "message": str(exc)},
        ) from exc

    currency_changed = (
        "currency" in changes
        and str(changes["currency"]).upper() != str(row.currency or "").upper()
    )
    for field_name, value in changes.items():
        setattr(row, field_name, value)
    if currency_changed:
        if str(row.currency or "").upper() == str(position.reporting_currency or "").upper():
            row.fx_rate_to_reporting = None
        elif "fx_rate_to_reporting" not in changes:
            row.fx_rate_to_reporting = None
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


class ManualPriceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    observed_at: datetime
    source_name: str = Field(default="Customer entered market price", min_length=1, max_length=240)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        validated = _currency(value)
        assert validated is not None
        return validated


@router.post("/positions/{position_id}/manual-price", status_code=status.HTTP_201_CREATED)
def set_manual_price(
    position_id: str,
    payload: ManualPriceUpdate,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _require_write(ctx)
    row = _position(db, org_id, position_id)
    evidence_id = f"manual-price-{row.id}-{uuid.uuid4().hex[:12]}"
    row.current_realizable_price = payload.value
    row.price_currency = payload.currency
    if payload.currency == str(row.reporting_currency or "").upper():
        row.fx_rate_to_reporting = None
    else:
        # A rate already on the row may describe a previous source currency.
        # Clear it and let the governed refresh path establish the new pair.
        row.fx_rate_to_reporting = None
    observation = MarketObservation(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        position_id=row.id,
        evidence_id=evidence_id,
        observation_type="cash_price",
        provider="customer",
        source_name=payload.source_name.strip(),
        source_status="MANUAL",
        value=payload.value,
        unit=f"{payload.currency}/{row.quantity_unit}",
        currency=payload.currency,
        observed_at=(payload.observed_at.astimezone(timezone.utc).replace(tzinfo=None) if payload.observed_at.tzinfo else payload.observed_at),
        retrieved_at=datetime.utcnow(),
        quality_json={"grade": "customer_entered"},
        licensing_json={"display_allowed": True},
        metadata_json={"input_source": "customer_structured_input", "entry_surface": "enterprise_portal"},
    )
    db.add(observation)
    db.commit()
    return {
        "position_id": row.id,
        "evidence_id": evidence_id,
        "source_status": "MANUAL",
        "status": "created",
    }


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
